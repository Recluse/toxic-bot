"""
ai/responder.py — LLM reply pipeline for chat and explain modes.

get_reply()  — the single entry point for all LLM calls.
               Selects prompt, builds message list, saves to history.
"""

import logging

from ai.client import chat_completion, vision_completion
from ai.modes import BotMode
from ai.prompts import get_system_prompt, get_explain_prompt
from ai.vision import build_vision_message
import db.history as history_db

logger = logging.getLogger(__name__)


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
) -> str:
    """
    Build the full message list and call the appropriate Groq endpoint.

    In CHAT mode:    toxic persona, uses history, saves reply to history.
    In EXPLAIN mode: scientific pedant, no history read/write,
                     vision model used when image_base64 is provided.

    Args:
        image_base64: Base64-encoded image string from ai.vision.
                      When provided in EXPLAIN mode the vision model is used.
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
    )


async def _chat_reply(
    chat_id:        int,
    user_id:        int,
    username:       str,
    user_text:      str,
    toxicity_level: int,
    lang:           str,
    extra_context:  list[dict],
) -> str:
    # Load recent history and optional user profile for context window
    history       = await history_db.get_recent(chat_id)
    user_summary  = await history_db.get_user_summary(chat_id, user_id)
    system_prompt = get_system_prompt(toxicity_level, lang, user_summary)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.extend(extra_context)
    messages.append({"role": "user", "content": f"{username}: {user_text}"})

    reply = await chat_completion(messages)

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
    return await chat_completion(messages)
