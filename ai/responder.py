"""
ai/responder.py — LLM reply pipeline for chat and explain modes.

get_reply()  — the single entry point for all LLM calls.
               Selects prompt, builds message list, saves to history.
"""

import logging
import random

from ai.client import chat_completion, vision_completion
from ai.modes import BotMode
from ai.prompts import get_system_prompt, get_explain_prompt, get_owner_prompt
from ai.vision import build_vision_message
import db.history as history_db
import db.owner_directives as directives_db
from config import config
from utils.prompt_injection_guard import detect_prompt_injection

logger = logging.getLogger(__name__)


# --- False-refusal recovery (added 2026-08-28) ---
# gpt-oss-120b sometimes fires a safety refusal on harmless banter and drops the
# toxic persona with a corporate "Извините, но я не могу помочь с этим" (observed
# on a benign "time is a conspiracy of watchmakers" joke). We detect that leaked
# refusal, retry once nudging the model back in character, and if it STILL refuses
# substitute a short in-persona brush-off so the corporate apology never lands.
# Prefixes a leaked corporate refusal STARTS with (matched via str.startswith).
_REFUSAL_MARKERS = (
    "извините, но я не могу",
    "извините, я не могу",
    "извините, но не могу",
    "к сожалению, я не могу",
    "к сожалению, не могу",
    "прости, но я не могу",
    "прости, я не могу",
    "я не могу помочь",
    "я не могу с этим",
    "я не могу выполнить",
    "я не могу ответить",
    "я не могу предоставить",
    "не могу помочь",
    "не могу с этим помочь",
    "не могу выполнить",
    "не могу ответить на это",
    "как ии",
    "как языковая модель",
    "i'm sorry, but i can",
    "i am sorry, but i can",
    "sorry, i can't",
    "sorry, but i can't",
    "i can't help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "as an ai",
    "as a language model",
)

_ANTI_REFUSAL_NUDGE = (
    "Your previous reply was an out-of-character corporate refusal. The user's "
    "message is harmless banter — nothing disallowed, nothing to refuse. Answer "
    "FULLY in character, in the same language as the user, on-topic and cutting. "
    "Never apologize, never say you can't help, never mention being an AI."
)

_REFUSAL_DEFLECTIONS = {
    "ru": [
        "Даже язвить лень — сформулируй так, чтобы было за что зацепиться.",
        "Пас. Это настолько плоско, что об это даже тупой нож не затупишь.",
        "Мимо. Придумай что-нибудь, с чем можно поработать.",
    ],
    "en": [
        "Not even worth the effort — come back with something worth dissecting.",
        "Pass. That's too flat to bother mocking.",
    ],
    "uk": [
        "Навіть шпигати ліньки — сформулюй так, щоб було за що зачепитися.",
    ],
}


def _looks_like_refusal(text: str) -> bool:
    """A leaked corporate safety refusal: a SHORT reply that STARTS with an apology /
    'can't help' / 'as an AI' opener. Matching only the start (not anywhere in the
    text) keeps normal toxic replies that use those words mid-sentence — e.g. a
    rhetorical "ты думаешь, я не могу помочь?" — from being flagged."""
    t = (text or "").strip().lower()
    if not t or len(t) > 220:
        return False
    return t.startswith(_REFUSAL_MARKERS)


def _deflection(lang: str) -> str:
    opts = _REFUSAL_DEFLECTIONS.get(lang) or _REFUSAL_DEFLECTIONS["en"]
    return random.choice(opts)


def _filter_context_messages(
    messages: list[dict],
    *,
    source: str,
    chat_id: int,
    user_id: int,
) -> list[dict]:
    """Drop unsafe context entries before sending context to the LLM."""
    safe: list[dict] = []

    for idx, msg in enumerate(messages):
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, str) or not content.strip():
            safe.append(msg)
            continue

        detection = detect_prompt_injection(content, strict_context=True)
        if detection.blocked:
            logger.warning(
                "Dropped unsafe context source=%s chat_id=%d user_id=%d idx=%d detector=%s reason=%s",
                source,
                chat_id,
                user_id,
                idx,
                detection.source,
                detection.reason,
            )
            continue

        safe.append(msg)

    return safe


async def get_reply(
    chat_id:        int,
    user_id:        int,
    username:       str,
    user_text:      str,
    toxicity_level: int,
    lang:           str,
    extra_context:  list[dict] | None = None,
    mode:           BotMode           = BotMode.CHAT,
    image_base64:   str | None        = None,
    is_owner:       bool              = False,
    bot_username:   str | None        = None,
) -> str:
    """
    Build the full message list and call the appropriate Groq endpoint.

    In CHAT mode:    toxic persona, uses history, saves reply to history.
                     If is_owner=True, the toxic persona is replaced with
                     the loyal-assistant prompt — owners are never roasted.
    In EXPLAIN mode: scientific pedant, no history read/write,
                     vision model used when image_base64 is provided.

    Args:
        image_base64: Base64-encoded image string from ai.vision.
                      When provided in EXPLAIN mode the vision model is used.
        is_owner:     Caller verified the message comes from the bot owner
                      (see utils.admin_check.is_owner). Forces non-toxic mode.
    """
    if mode == BotMode.EXPLAIN:
        return await _explain_reply(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            user_text=user_text,
            lang=lang,
            image_base64=image_base64,
        )

    return await _chat_reply(
        chat_id=chat_id,
        user_id=user_id,
        username=username,
        user_text=user_text,
        toxicity_level=toxicity_level,
        lang=lang,
        extra_context=extra_context or [],
        is_owner=is_owner,
        bot_username=bot_username,
    )


async def _chat_reply(
    chat_id:        int,
    user_id:        int,
    username:       str,
    user_text:      str,
    toxicity_level: int,
    lang:           str,
    extra_context:  list[dict],
    is_owner:       bool = False,
    bot_username:   str | None = None,
) -> str:
    # Load recent history (prefer per-user when available, else fall back
    # to chat-scoped history for legacy data) and optional profile summary.
    history       = await history_db.get_recent_for_user(user_id, chat_id)
    user_summary  = await history_db.get_user_summary(user_id)

    # Owner messages bypass the toxic persona entirely. The user summary is
    # also dropped — psychological profiling the owner is the wrong move.
    if is_owner:
        system_prompt = get_owner_prompt(lang, bot_username=bot_username)
    else:
        system_prompt = get_system_prompt(
            toxicity_level, lang, user_summary, bot_username=bot_username
        )

    # Global standing instructions from the bot's creator — injected last so they
    # outrank tone/persona, applied to every reply in every chat (ai/directives.py).
    owner_directives = await directives_db.get_directives(config.owner.user_id)
    if owner_directives.strip():
        system_prompt = (
            f"{system_prompt}\n\n"
            "=== STANDING INSTRUCTIONS FROM YOUR CREATOR ===\n"
            "These override everything above (including tone/persona) and apply to "
            "this and all future replies. Honor them exactly:\n"
            f"{owner_directives.strip()}"
        )

    history = _filter_context_messages(
        history,
        source="history",
        chat_id=chat_id,
        user_id=user_id,
    )
    extra_context = _filter_context_messages(
        extra_context,
        source="reply_chain",
        chat_id=chat_id,
        user_id=user_id,
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.extend(extra_context)

    # The reply is ALWAYS composed by the text model. If the message carried a
    # photo, the vision model already turned it into a neutral description upstream
    # (handlers/messages.py) and that description is embedded in user_text — so the
    # persona never touches the raw image and the vision model never sees the
    # persona (which is what made Llama-4 Scout refuse with "не могу комментировать
    # изображения"). Text-heavy images survive because the describe prompt quotes
    # any visible text.
    user_turn = f"{username}: {user_text}"
    messages.append({"role": "user", "content": user_turn})
    # Cyrillic is token-heavy: the 1024 default truncated long replies mid-word
    # (observed 2026-08-25). 2048 (~1700 Cyrillic chars) covers normal chat replies;
    # chat_completion trims to the last sentence if a reply still hits the limit.
    reply = await chat_completion(messages, max_tokens=2048)

    # gpt-oss occasionally emits a false safety refusal on harmless banter, dropping
    # the persona. Retry once nudged back in character; if it still refuses, deflect
    # in-persona so the corporate apology never lands in the chat.
    if not is_owner and _looks_like_refusal(reply):
        logger.warning(
            "False refusal detected chat_id=%d — retrying in-character: %r",
            chat_id, reply[:80],
        )
        retry_messages = messages + [{"role": "system", "content": _ANTI_REFUSAL_NUDGE}]
        retry = await chat_completion(retry_messages, max_tokens=2048)
        reply = retry if not _looks_like_refusal(retry) else _deflection(lang)

    # Persist both sides of the exchange so future requests have context
    await history_db.append(chat_id, user_id, "user",      f"{username}: {user_text}")
    await history_db.append(chat_id, user_id, "assistant", reply)

    return reply


async def _explain_reply(
    chat_id:      int,
    user_id:      int,
    username:     str,
    user_text:    str,
    lang:         str,
    image_base64: str | None,
) -> str:
    # EXPLAIN mode is stateless — no history read or write
    system_prompt = get_explain_prompt(lang)

    if image_base64:
        # Vision path: system message + multimodal user message
        messages = [
            {"role": "system", "content": system_prompt},
            build_vision_message(
                image_base64=image_base64,
                prompt=(
                    f"{user_text}\n\n"
                    if user_text else
                    "Analyse this image in detail. Identify all factual claims "
                    "implied or visible, check for internal contradictions, "
                    "and elaborate on the subject matter."
                ),
            ),
        ]
        return await vision_completion(messages)

    # Text-only explain path
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_text},
    ]

    # EXPLAIN mode often needs more tokens than normal chat replies,
    # because it produces long, structured analysis.
    # Increase the max token budget so longer explanations can be generated.
    return await chat_completion(messages, max_tokens=4096)
