"""
handlers/admin_menu/main_menu.py — Root settings menu.

Renders the top-level inline keyboard with one button per settings category.
The Exit button deletes the menu message entirely.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from i18n import get_text
from utils.tg_safe import safe_edit
from handlers.admin_menu.callbacks import (
    MENU_TOXICITY, MENU_FREQUENCY, MENU_COOLDOWN,
    MENU_CHAIN, MENU_MIN_WORDS, MENU_USER_MGMT, MENU_EXIT,
)


def build_main_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Return the main menu inline keyboard in the given language."""
    t = lambda key: get_text(key, lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("menu_toxicity"),    callback_data=MENU_TOXICITY)],
        [InlineKeyboardButton(t("menu_frequency"),   callback_data=MENU_FREQUENCY)],
        [InlineKeyboardButton(t("menu_cooldown"),    callback_data=MENU_COOLDOWN)],
        [InlineKeyboardButton(t("menu_reply_chain"), callback_data=MENU_CHAIN)],
        [InlineKeyboardButton(t("menu_min_words"),   callback_data=MENU_MIN_WORDS)],
        [InlineKeyboardButton(t("menu_user_mgmt"),   callback_data=MENU_USER_MGMT)],
        [InlineKeyboardButton(t("menu_exit"),        callback_data=MENU_EXIT)],
    ])


async def send_main_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
    edit: bool = False,
) -> None:
    """
    Send or edit-in-place the main settings menu.

    Args:
        edit: If True, edit the existing callback message instead of sending new.
              Used when navigating back to the main menu from a submenu.
    """
    text     = get_text("menu_title", lang)
    keyboard = build_main_keyboard(lang)

    if edit and update.callback_query:
        await safe_edit(update, text, keyboard)
    else:
        await update.effective_message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
