"""
handlers/commands_explain.py — /explain command handler.

Accepts a reply to any message (text / photo / voice / audio),
or inline text: /explain some topic — works without a reply in any chat.
In private chat: works on the /explain message itself (no reply needed).

Pipeline:
    voice/audio → transcribe → text
    photo       → vision model → text  (or pass image directly for explain)
    text        → pass through

Then calls get_reply() in EXPLAIN mode — no toxicity, no history,
scientific pedant persona with peer-reviewed source references.
"""

import logging
import re

import html

from telegram import Update, ReplyParameters
from telegram.constants import ParseMode, ChatAction, ChatType
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ai.modes import BotMode
from ai.responder import get_reply
from ai.transcriber import transcribe
from ai.vision import get_image_base64
import db.chat_settings as settings_db
from i18n import get_text
from utils.rate_limiter import check_and_set_explain

logger = logging.getLogger(__name__)


async def cmd_explain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /explain command."""
    message = update.effective_message
    chat    = update.effective_chat
    user    = update.effective_user

    if not message or not chat or not user:
        return

    settings    = await settings_db.get_or_create(chat.id)
    lang        = settings["lang"]
    is_pm       = chat.type == ChatType.PRIVATE

    if not is_pm:
        explain_cd_min = int(settings.get("explain_cooldown_min", 10))
        if not check_and_set_explain(chat.id, user.id, explain_cd_min * 60):
            await message.reply_text(get_text("explain_cooldown_active", lang, minutes=explain_cd_min))
            return

    # Text typed inline after the command: "/explain ядерная физика"
    inline_text = " ".join(context.args).strip() if context.args else ""
    # In PM with no reply and no inline text — show usage description
    if is_pm and not message.reply_to_message and not inline_text:
        await message.reply_text(
            get_text("explain_help", lang),
            parse_mode=ParseMode.HTML,
        )
        return
    # In groups: require a reply OR inline text after the command.
    # /explain some text  → use that text directly, no reply needed.
    # /explain            → must be a reply to something.
    if not is_pm and not message.reply_to_message and not inline_text:
        await message.reply_text(get_text("explain_reply_required", lang))
        return

    # Priority: explicit reply target > inline text > message itself (PM fallback)
    if message.reply_to_message:
        target = message.reply_to_message
    else:
        # inline text or PM — target is the /explain message itself
        target = message

    # --- Extract content from the target message ---
    # Inline text overrides whatever is on the target message
    content_text: str | None = inline_text or target.text or target.caption or None
    image_base64: str | None = None

    if target.voice or target.audio:
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        file_id      = (target.voice or target.audio).file_id
        is_voice     = target.voice is not None
        content_text = await transcribe(context.bot, file_id, is_voice=is_voice)
        logger.debug("explain: transcribed voice chat_id=%d len=%d", chat.id, len(content_text or ""))

        if not content_text:
            await message.reply_text(get_text("explain_transcribe_failed", lang))
            return

    elif target.photo:
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
        image_base64 = await get_image_base64(context.bot, target.photo[-1].file_id)
        logger.debug("explain: downloaded image chat_id=%d", chat.id)

    elif not content_text:
        await message.reply_text(get_text("explain_empty", lang))
        return

    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)

    # When explaining a photo with no caption or inline text, inject a language
    # instruction so the LLM does not default to English — without any user_text
    # the model has no signal about the desired response language.
    if image_base64 and not content_text:
        content_text = f"Explain this image. Respond strictly in language code: {lang}."
        logger.debug("explain: injected language prompt for image chat_id=%d lang=%s", chat.id, lang)

    try:
        reply = await get_reply(
            chat_id=chat.id,
            user_id=user.id,
            username=user.username or user.full_name,
            user_text=content_text or "",
            toxicity_level=0,  # ignored in EXPLAIN mode
            lang=lang,
            mode=BotMode.EXPLAIN,
            image_base64=image_base64,
        )
    except Exception as exc:
        logger.error("explain get_reply failed chat_id=%d: %s", chat.id, exc)
        reply = get_text("error_generic", lang)

    # Reply to the TARGET message (the one being explained), not to the
    # /explain command — that message may already be deleted at this point,
    # so message.reply_text() would silently drop reply_to_message_id.
    # Send explain response — auto-splits if too long (Telegram 4096 limit)
    await _send_explain_parts(
        context.bot,
        chat.id,
        reply,
        target.message_id,
    )

    # Clean up command messages in group chats.
    if chat.type != ChatType.PRIVATE:
        try:
            await message.delete()
        except Exception:
            pass


def _sanitize_telegram_html(text: str) -> str:
    """Sanitize HTML output for Telegram's limited HTML subset.

    Telegram supports only a small set of HTML tags. Some LLMs (and the user’s
    prompt) may produce tags like <sup>/<sub> which are rejected.

    This function:
    - Converts <sup>...</sup> to ^... and <sub>...</sub> to _... to preserve
      math-like notation.
    - Removes any unsupported HTML tags while keeping their text content.
    """

    # Convert common math-style tags into text-friendly notations.
    text = re.sub(r"<sup>(.*?)</sup>", lambda m: f"^{m.group(1)}", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<sub>(.*?)</sub>", lambda m: f"_{m.group(1)}", text, flags=re.IGNORECASE | re.DOTALL)

    # Telegram supports only the following tags in HTML parse mode.
    allowed = {"b", "i", "u", "s", "strong", "em", "code", "pre", "a"}

    def _keep_tag(m: re.Match) -> str:
        tag = m.group(1).lower()
        if tag in allowed:
            return m.group(0)
        return ""

    # Strip unsupported tags but keep their inner text unchanged.
    return re.sub(r"</?([a-zA-Z0-9]+)(?:\s+[^>]*)?>", _keep_tag, text)


def _repair_html_tags(text: str) -> str:
    """Make HTML tags balanced so Telegram can parse them.

    Telegram rejects messages with mismatched tags (e.g. <b>...</i>). This
    tries to fix simple cases by ignoring a mismatched closing tag and by
    automatically closing any remaining open tags at the end.

    Supported tags are those that Telegram accepts (and a few we generate
    ourselves): <b>, <i>, <u>, <s>, <strong>, <em>, <code>, <pre>, <a>.
    """

    supported_tags = {"b", "i", "u", "s", "strong", "em", "code", "pre", "a"}

    tags: list[str] = []
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "<":
            end = text.find(">", i + 1)
            if end == -1:
                out.append(text[i:])
                break

            tag = text[i + 1:end].strip()
            is_closing = tag.startswith("/")
            tag_name = tag[1:] if is_closing else tag
            tag_name = tag_name.split()[0].lower()

            if tag_name in supported_tags:
                if is_closing:
                    if tags and tags[-1] == tag_name:
                        tags.pop()
                        out.append(text[i:end + 1])
                    else:
                        # Ignore mismatched closing tag (Telegram will reject it)
                        pass
                else:
                    tags.append(tag_name)
                    out.append(text[i:end + 1])
            else:
                # Drop unsupported tag entirely.
                pass

            i = end + 1
        else:
            out.append(text[i])
            i += 1

    while tags:
        out.append(f"</{tags.pop()}>")

    return "".join(out)


def _chunk_html_text(text: str, max_len: int = 3500) -> list[str]:
    """Split HTML text into smaller chunks while respecting basic tag boundaries.

    Telegram enforces a 4096-character limit on the final rendered message,
    so we use a conservative max_len to allow for markup overhead and the
    "Continued..." prefix.
    """

    parts: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            parts.append(remaining)
            break

        # Prefer splitting at a '>' to avoid cutting inside an HTML tag.
        chunk = remaining[:max_len]
        cut = chunk.rfind(">")
        if cut <= 0:
            cut = max_len
        else:
            cut += 1

        # Try to cut at a newline or space if available near the split point.
        for sep in ("\n", " "):
            sep_pos = remaining.rfind(sep, 0, cut)
            if sep_pos != -1 and sep_pos > cut - 200:
                cut = sep_pos + 1
                break

        # Ensure we are not splitting inside an HTML tag.
        while True:
            prefix = remaining[:cut]
            if prefix.count("<") > prefix.count(">"):
                next_gt = remaining.find(">", cut)
                if next_gt == -1:
                    cut = len(remaining)
                    break
                cut = next_gt + 1
                continue
            break

        parts.append(remaining[:cut])
        remaining = remaining[cut:]

    return parts


async def _send_explain_parts(bot, chat_id: int, text: str, reply_to: int) -> None:
    """Split long explain responses into multiple HTML-formatted messages."""

    # Sanitize LLM output for Telegram HTML parse mode.
    sanitized = _sanitize_telegram_html(text)
    repaired = _repair_html_tags(sanitized)

    chunks = _chunk_html_text(repaired, max_len=3500)

    for chunk in chunks:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                reply_parameters=ReplyParameters(
                    message_id=reply_to,
                    chat_id=chat_id,
                ),
            )
        except BadRequest as exc:
            err = str(exc)
            if "Can't parse entities" in err or "unsupported start tag" in err:
                # Fallback to a safer format without HTML tags.
                safe_text = html.escape(payload)
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=safe_text,
                        reply_parameters=ReplyParameters(
                            message_id=reply_to,
                            chat_id=chat_id,
                        ),
                    )
                except BadRequest as exc2:
                    # If it is still too long, split further and retry.
                    if "Message is too long" in str(exc2):
                        smaller_chunks = _chunk_html_text(safe_text, max_len=3800)
                        for sub in smaller_chunks:
                            try:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=sub,
                                    reply_parameters=ReplyParameters(
                                        message_id=reply_to,
                                        chat_id=chat_id,
                                    ),
                                )
                            except BadRequest as exc3:
                                if "Message is too long" in str(exc3):
                                    # Last resort: hard-split by size until it fits.
                                    hard_chunks = _chunk_html_text(sub, max_len=1500)
                                    for hard in hard_chunks:
                                        await bot.send_message(
                                            chat_id=chat_id,
                                            text=hard,
                                            reply_parameters=ReplyParameters(
                                                message_id=reply_to,
                                                chat_id=chat_id,
                                            ),
                                        )
                                else:
                                    raise
                    else:
                        raise
            elif "Message is too long" in err:
                # Split the chunk smaller and resend.
                smaller_chunks = _chunk_html_text(chunk, max_len=3800)
                for sub in smaller_chunks:
                    try:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=sub,
                            parse_mode=ParseMode.HTML,
                            reply_parameters=ReplyParameters(
                                message_id=reply_to,
                                chat_id=chat_id,
                            ),
                        )
                    except BadRequest as exc3:
                        if "Message is too long" in str(exc3):
                            hard_chunks = _chunk_html_text(sub, max_len=1500)
                            for hard in hard_chunks:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=hard,
                                    parse_mode=ParseMode.HTML,
                                    reply_parameters=ReplyParameters(
                                        message_id=reply_to,
                                        chat_id=chat_id,
                                    ),
                                )
                        else:
                            raise
            else:
                raise
