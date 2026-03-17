"""
handlers/language_select.py — First-run language picker.

Sends an inline keyboard asking which language the chat should use.
Called from cmd_start when no settings row exists yet for a chat.

The language choice is persisted immediately on button press and the
keyboard message is deleted after confirmation.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import db.chat_settings as settings_db
from i18n import get_text

logger = logging.getLogger(__name__)

# Callback data constants for language selection
_CB_LANG_EN = "lang:set:en"
_CB_LANG_RU = "lang:set:ru"
_CB_LANG_UA = "lang:set:ua"

# Language display labels shown on the keyboard
_LANG_LABELS = {
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "ua": "🇺🇦 Українська",
}


def _build_keyboard() -> InlineKeyboardMarkup:
    """Build the 1×3 language selection keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_LANG_LABELS["en"], callback_data=_CB_LANG_EN),
            InlineKeyboardButton(_LANG_LABELS["ru"], callback_data=_CB_LANG_RU),
            InlineKeyboardButton(_LANG_LABELS["ua"], callback_data=_CB_LANG_UA),
        ]
    ])


async def send_language_picker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    default_lang: str = "en",
) -> None:
    """
    Send the language selection keyboard to the chat.
    Uses the default_lang to localise the prompt text itself.
    """
    text = get_text("start_lang_prompt", default_lang)
    await update.effective_message.reply_text(
        text,
        reply_markup=_build_keyboard(),
    )


async def handle_lang_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Handle lang:set:* callback queries.

    Saves the chosen language, answers with a toast,
    and edits the original message to a plain confirmation
    (removes the keyboard so it cannot be clicked twice).
    """
    query = update.callback_query
    await query.answer()  # acknowledge immediately to stop the spinner

    # Extract language code from callback data, e.g. "lang:set:ru" → "ru"
    lang = query.data.split(":")[-1]

    if lang not in ("en", "ru", "ua"):
        logger.warning("Unknown language callback: %s", query.data)
        return

    chat_id = update.effective_chat.id
    await settings_db.get_or_create(chat_id)   # ensure row exists first
    await settings_db.set_language(chat_id, lang)

    logger.info("Language set to %s for chat_id=%d", lang, chat_id)

    # Edit the keyboard message to a plain confirmation text
    confirmation = get_text("lang_set", lang)
    try:
        await query.edit_message_text(confirmation)
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            # User tapped the same language again; this is harmless.
            await query.answer()
            return
        raise
