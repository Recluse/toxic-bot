"""
handlers/admin_menu/simple_choice_menus.py — Cooldown, chain depth, min_words.

All three follow the same pattern:
    - Fixed option buttons with current value marked ●
    - Press = save immediately + toast
    - Back button returns to main menu

They are combined in one file since the pattern is identical.
"""

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, RetryAfter
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db.chat_settings as settings_db
from i18n import get_text
from handlers.admin_menu.callbacks import (
    SET_COOLDOWN, SET_CHAIN, SET_MIN_WORDS, MENU_MAIN,
)

# Available option values for each setting
_COOLDOWN_OPTIONS  = [30, 60, 120, 300]   # seconds
_CHAIN_OPTIONS     = [3, 5, 7, 10]        # message depth
_MIN_WORDS_OPTIONS = [3, 5, 7, 10]        # word count


def _mark(value, current) -> str:
    """Prefix current value button with ● to indicate selection."""
    return f"● {value}" if value == current else str(value)


async def _safe_edit(update: Update, text: str, reply_markup) -> None:
    """
    Edit the callback query message safely.
    Handles two known Telegram API edge cases:
      - message is not modified: user tapped the already-selected option
      - RetryAfter: flood control triggered by rapid taps — wait and retry once
    """
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            await update.callback_query.answer()
        else:
            raise
    except RetryAfter as exc:
        # Flood control — wait the required delay then retry once
        await asyncio.sleep(exc.retry_after + 0.5)
        await update.callback_query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )


# ---------------------------------------------------------------------------
# Cooldown menu
# ---------------------------------------------------------------------------

def build_cooldown_keyboard(lang: str, current: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            _mark(v, current),
            callback_data=SET_COOLDOWN(v),
        )
        for v in _COOLDOWN_OPTIONS
    ]
    return InlineKeyboardMarkup([
        buttons,
        [InlineKeyboardButton(get_text("menu_back", lang), callback_data=MENU_MAIN)],
    ])


async def show_cooldown_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    current = settings["reply_cooldown_sec"]
    text    = get_text("cooldown_title", lang, val=current)
    await _safe_edit(update, text, build_cooldown_keyboard(lang, current))


async def handle_set_cooldown(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    value: int,
    settings: dict,
    lang: str,
) -> None:
    chat_id = update.effective_chat.id
    await settings_db.update_field(chat_id, "reply_cooldown_sec", value)
    await update.callback_query.answer(
        get_text("cooldown_saved", lang, val=value), show_alert=False
    )
    settings["reply_cooldown_sec"] = value
    await show_cooldown_menu(update, context, settings, lang)


# ---------------------------------------------------------------------------
# Reply chain depth menu
# ---------------------------------------------------------------------------

def build_chain_keyboard(lang: str, current: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            _mark(v, current),
            callback_data=SET_CHAIN(v),
        )
        for v in _CHAIN_OPTIONS
    ]
    return InlineKeyboardMarkup([
        buttons,
        [InlineKeyboardButton(get_text("menu_back", lang), callback_data=MENU_MAIN)],
    ])


async def show_chain_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    current = settings["reply_chain_depth"]
    text    = get_text("chain_title", lang, val=current)
    await _safe_edit(update, text, build_chain_keyboard(lang, current))


async def handle_set_chain(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    value: int,
    settings: dict,
    lang: str,
) -> None:
    chat_id = update.effective_chat.id
    await settings_db.update_field(chat_id, "reply_chain_depth", value)
    await update.callback_query.answer(
        get_text("chain_saved", lang, val=value), show_alert=False
    )
    settings["reply_chain_depth"] = value
    await show_chain_menu(update, context, settings, lang)


# ---------------------------------------------------------------------------
# Minimum words menu
# ---------------------------------------------------------------------------

def build_min_words_keyboard(lang: str, current: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            _mark(v, current),
            callback_data=SET_MIN_WORDS(v),
        )
        for v in _MIN_WORDS_OPTIONS
    ]
    return InlineKeyboardMarkup([
        buttons,
        [InlineKeyboardButton(get_text("menu_back", lang), callback_data=MENU_MAIN)],
    ])


async def show_min_words_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    current = settings["min_words"]
    text    = get_text("min_words_title", lang, val=current)
    await _safe_edit(update, text, build_min_words_keyboard(lang, current))


async def handle_set_min_words(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    value: int,
    settings: dict,
    lang: str,
) -> None:
    chat_id = update.effective_chat.id
    await settings_db.update_field(chat_id, "min_words", value)
    await update.callback_query.answer(
        get_text("min_words_saved", lang, val=value), show_alert=False
    )
    settings["min_words"] = value
    await show_min_words_menu(update, context, settings, lang)
