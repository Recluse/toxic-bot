"""
handlers/admin_menu/frequency_menu.py — Reply frequency submenu.

Uses ▲/▼ increment/decrement buttons for min and max values.
Changes are staged in context.user_data until the Save button is pressed.
This is the only submenu that requires an explicit Save action —
because min and max are interdependent and must be validated together.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db.chat_settings as settings_db
from i18n import get_text
from handlers.admin_menu.callbacks import (
    FREQ_MIN_UP, FREQ_MIN_DOWN,
    FREQ_MAX_UP, FREQ_MAX_DOWN,
    FREQ_SAVE, MENU_MAIN,
)

# Hard limits to prevent nonsensical values
_FREQ_MIN_FLOOR   = 1
_FREQ_MAX_CEILING = 100
_FREQ_STEP        = 10

# Keys for staging unsaved changes in context.user_data
_KEY_STAGED_MIN = "freq_staged_min"
_KEY_STAGED_MAX = "freq_staged_max"


def _get_staged(context: ContextTypes.DEFAULT_TYPE, settings: dict) -> tuple[int, int]:
    """
    Return the currently staged (unsaved) frequency values.
    Falls back to the DB values if nothing is staged yet.
    """
    staged_min = context.user_data.get(_KEY_STAGED_MIN, settings["freq_min"])
    staged_max = context.user_data.get(_KEY_STAGED_MAX, settings["freq_max"])
    return staged_min, staged_max


def build_frequency_keyboard(
    lang: str,
    staged_min: int,
    staged_max: int,
) -> InlineKeyboardMarkup:
    """Build the ▲/▼ adjustment keyboard with current staged values displayed."""
    t = lambda k, **kw: get_text(k, lang, **kw)
    return InlineKeyboardMarkup([
        # Min row
        [
            InlineKeyboardButton(t("freq_decrease"),                  callback_data=FREQ_MIN_DOWN),
            InlineKeyboardButton(t("freq_min_label", val=staged_min), callback_data="noop"),
            InlineKeyboardButton(t("freq_increase"),                  callback_data=FREQ_MIN_UP),
        ],
        # Max row
        [
            InlineKeyboardButton(t("freq_decrease"),                  callback_data=FREQ_MAX_DOWN),
            InlineKeyboardButton(t("freq_max_label", val=staged_max), callback_data="noop"),
            InlineKeyboardButton(t("freq_increase"),                  callback_data=FREQ_MAX_UP),
        ],
        [InlineKeyboardButton(t("freq_save"),  callback_data=FREQ_SAVE)],
        [InlineKeyboardButton(t("menu_back"),  callback_data=MENU_MAIN)],
    ])


async def show_frequency_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    """
    Render or refresh the frequency submenu with current staged values.
    Silently ignores Telegram's 'Message is not modified' error —
    this happens when the menu is refreshed with identical content.
    """
    staged_min, staged_max = _get_staged(context, settings)
    text     = get_text("freq_title", lang, min=staged_min, max=staged_max)
    keyboard = build_frequency_keyboard(lang, staged_min, staged_max)

    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        # Telegram raises BadRequest when content is identical to existing message.
        # This is not an error — it means the displayed values are already correct.
        if "Message is not modified" in str(exc):
            pass
        else:
            raise


async def handle_freq_adjust(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    settings: dict,
    lang: str,
) -> None:
    """
    Handle ▲/▼ presses — adjust the staged value and refresh the menu.
    No DB write yet; that happens on FREQ_SAVE.
    """
    staged_min, staged_max = _get_staged(context, settings)

    if action == FREQ_MIN_UP:
        staged_min = min(staged_min + _FREQ_STEP, staged_max)
    elif action == FREQ_MIN_DOWN:
        staged_min = max(_FREQ_MIN_FLOOR, staged_min - _FREQ_STEP)
    elif action == FREQ_MAX_UP:
        staged_max = min(_FREQ_MAX_CEILING, staged_max + _FREQ_STEP)
    elif action == FREQ_MAX_DOWN:
        staged_max = max(staged_min, staged_max - _FREQ_STEP)

    context.user_data[_KEY_STAGED_MIN] = staged_min
    context.user_data[_KEY_STAGED_MAX] = staged_max

    await update.callback_query.answer()
    await show_frequency_menu(update, context, settings, lang)


async def handle_freq_save(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    """Persist staged frequency values to DB and show a toast."""
    staged_min, staged_max = _get_staged(context, settings)

    if staged_min > staged_max:
        await update.callback_query.answer(
            get_text("freq_invalid", lang), show_alert=True
        )
        return

    chat_id = update.effective_chat.id
    await settings_db.set_frequency(chat_id, staged_min, staged_max)

    # Clear staged values — they are now persisted in DB
    context.user_data.pop(_KEY_STAGED_MIN, None)
    context.user_data.pop(_KEY_STAGED_MAX, None)

    toast = get_text("freq_saved", lang, min=staged_min, max=staged_max)
    await update.callback_query.answer(toast, show_alert=False)

    settings["freq_min"] = staged_min
    settings["freq_max"] = staged_max
    await show_frequency_menu(update, context, settings, lang)
