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

from telegram import Update, ReplyParameters
from telegram.constants import ParseMode, ChatAction, ChatType
from telegram.ext import ContextTypes

from ai.modes import BotMode
from ai.responder import get_reply
from ai.transcriber import transcribe
from ai.vision import get_image_base64
import db.chat_settings as settings_db
from i18n import get_text

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


async def _send_explain_parts(bot, chat_id: int, text: str, reply_to: int) -> None:
    """
    Split long explain responses into multiple HTML-formatted messages.
    Telegram limit: 4096 chars per message. Preserves formatting and threading.
    """
    # Split on double newlines (paragraphs) first, then characters if needed
    paragraphs = text.split("\n\n")
    current_part = ""
    parts = []

    for para in paragraphs:
        # Test if paragraph fits in current part
        test_part = current_part + (para + "\n\n" if current_part else para)
        if len(test_part) <= 4000:  # margin for safety
            current_part = test_part
        else:
            # Paragraph too long — split by single newlines, then chars
            if len(para) > 4000:
                # Single paragraph exceeds limit — split by sentences
                sentences = para.split(". ")
                subpart = ""
                for sent in sentences:
                    if len(subpart + sent + ". ") <= 4000:
                        subpart += sent + ". "
                    else:
                        if subpart:
                            parts.append(subpart.strip())
                        subpart = sent + ". "
                if subpart:
                    current_part = subpart
            else:
                if current_part:
                    parts.append(current_part.strip())
                current_part = para + "\n\n"

    if current_part:
        parts.append(current_part.strip())

    # Send parts sequentially with same reply_to threading
    for i, part in enumerate(parts, 1):
        if i == 1:
            await bot.send_message(
                chat_id=chat_id,
                text=part,
                parse_mode=ParseMode.HTML,
                reply_parameters=ReplyParameters(
                    message_id=reply_to,
                    chat_id=chat_id,
                ),
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=f"<b>Continued...</b>\n\n{part}",
                parse_mode=ParseMode.HTML,
                reply_parameters=ReplyParameters(
                    message_id=reply_to,
                    chat_id=chat_id,
                ),
            )
