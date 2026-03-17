"""
handlers/admin_menu/simple_choice_menus.py — Cooldown, chain depth, min_words.

All three follow the same pattern:
    - Fixed option buttons with current value marked ●
    - Press = save immediately + toast
    - Back button returns to main menu

They are combined in one file since the pattern is identical.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db.chat_settings as settings_db
from i18n import get_text
from utils.tg_safe import safe_edit
from handlers.admin_menu.callbacks import (
    SET_COOLDOWN, SET_CHAIN, SET_MIN_WORDS,
    EXPLAIN_CD_DOWN, EXPLAIN_CD_UP, EXPLAIN_CD_SAVE,
    MENU_MAIN,
)

# Available option values for each setting
_COOLDOWN_OPTIONS  = [30, 60, 120, 300]   # seconds
_CHAIN_OPTIONS     = [3, 5, 7, 10]        # message depth
_MIN_WORDS_OPTIONS = [3, 5, 7, 10]        # word count

# /explain cooldown options (minutes), adjustable by +/-10
_EXPLAIN_CD_MIN = 10
_EXPLAIN_CD_MAX = 600
_EXPLAIN_CD_STEP = 10
_KEY_STAGED_EXPLAIN_CD = "explain_cd_staged"


def _mark(value, current) -> str:
    """Prefix current value button with ● to indicate selection."""
    return f"● {value}" if value == current else str(value)


# ---------------------------------------------------------------------------
# Cooldown menu
# ---------------------------------------------------------------------------

def build_cooldown_keyboard(lang: str, current: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(_mark(v, current), callback_data=SET_COOLDOWN(v))
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
    await safe_edit(update, get_text("cooldown_title", lang, val=current),
                    build_cooldown_keyboard(lang, current))


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
        InlineKeyboardButton(_mark(v, current), callback_data=SET_CHAIN(v))
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
    await safe_edit(update, get_text("chain_title", lang, val=current),
                    build_chain_keyboard(lang, current))


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
        InlineKeyboardButton(_mark(v, current), callback_data=SET_MIN_WORDS(v))
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
    await safe_edit(update, get_text("min_words_title", lang, val=current),
                    build_min_words_keyboard(lang, current))


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


def _get_staged_explain_cd(context: ContextTypes.DEFAULT_TYPE, settings: dict) -> int:
    return int(context.user_data.get(_KEY_STAGED_EXPLAIN_CD, settings["explain_cooldown_min"]))


def build_explain_cooldown_keyboard(lang: str, current: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▼", callback_data=EXPLAIN_CD_DOWN),
            InlineKeyboardButton(f"{current} min", callback_data="noop"),
            InlineKeyboardButton("▲", callback_data=EXPLAIN_CD_UP),
        ],
        [InlineKeyboardButton(get_text("freq_save", lang), callback_data=EXPLAIN_CD_SAVE)],
        [InlineKeyboardButton(get_text("menu_back", lang), callback_data=MENU_MAIN)],
    ])


async def show_explain_cooldown_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    current = _get_staged_explain_cd(context, settings)
    await safe_edit(
        update,
        get_text("explain_cooldown_title", lang, val=current),
        build_explain_cooldown_keyboard(lang, current),
    )


async def handle_explain_cooldown_adjust(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    settings: dict,
    lang: str,
) -> None:
    value = _get_staged_explain_cd(context, settings)

    if action == EXPLAIN_CD_UP:
        value = min(_EXPLAIN_CD_MAX, value + _EXPLAIN_CD_STEP)
    elif action == EXPLAIN_CD_DOWN:
        value = max(_EXPLAIN_CD_MIN, value - _EXPLAIN_CD_STEP)

    context.user_data[_KEY_STAGED_EXPLAIN_CD] = value
    await update.callback_query.answer()
    await show_explain_cooldown_menu(update, context, settings, lang)


async def handle_explain_cooldown_save(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    value = _get_staged_explain_cd(context, settings)
    chat_id = update.effective_chat.id

    await settings_db.set_explain_cooldown(chat_id, value)
    context.user_data.pop(_KEY_STAGED_EXPLAIN_CD, None)
    settings["explain_cooldown_min"] = value

    await update.callback_query.answer(
        get_text("explain_cooldown_saved", lang, val=value), show_alert=False
    )
    await show_explain_cooldown_menu(update, context, settings, lang)
