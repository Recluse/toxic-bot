"""
handlers/admin_menu/toxicity_menu.py — Toxicity level submenu.

Displays five buttons (one per level).
The current level is marked with ● in the button label.
Pressing a button saves immediately and shows a toast notification.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db.chat_settings as settings_db
from i18n import get_text
from handlers.admin_menu.callbacks import SET_TOXICITY, MENU_MAIN


def build_toxicity_keyboard(lang: str, current: int) -> InlineKeyboardMarkup:
    """
    Build the toxicity keyboard.
    The button for the current level is prefixed with ● to indicate selection.
    """
    def label(level: int) -> str:
        text = get_text(f"toxicity_level_{level}", lang)
        return f"● {text}" if level == current else text

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label(1), callback_data=SET_TOXICITY(1))],
        [InlineKeyboardButton(label(2), callback_data=SET_TOXICITY(2))],
        [InlineKeyboardButton(label(3), callback_data=SET_TOXICITY(3))],
        [InlineKeyboardButton(label(4), callback_data=SET_TOXICITY(4))],
        [InlineKeyboardButton(label(5), callback_data=SET_TOXICITY(5))],
        [InlineKeyboardButton(get_text("menu_back", lang), callback_data=MENU_MAIN)],
    ])


async def show_toxicity_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    """Render or refresh the toxicity submenu."""
    current    = settings["toxicity_level"]
    level_name = get_text(f"level_name_{current}", lang)
    text       = get_text("toxicity_title", lang,
                          current=current, level_name=level_name)
    keyboard   = build_toxicity_keyboard(lang, current)

    await update.callback_query.edit_message_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def handle_set_toxicity(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    level: int,
    settings: dict,
    lang: str,
) -> None:
    """
    Persist the selected toxicity level and show a toast, then refresh the menu.
    The toast (answer_callback_query with show_alert=False) acts as the
    "modal confirmation" — it appears as a brief overlay notification.
    """
    chat_id = update.effective_chat.id
    await settings_db.set_toxicity(chat_id, level)

    # Toast notification
    toast = get_text("toxicity_saved", lang, level=level)
    await update.callback_query.answer(toast, show_alert=False)

    # Refresh menu to show updated ● marker
    settings["toxicity_level"] = level
    await show_toxicity_menu(update, context, settings, lang)
