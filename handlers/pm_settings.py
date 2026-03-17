"""
handlers/pm_settings.py — Private chat settings menu.

Allows user to configure PM-specific behavior and account-level actions.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db.chat_settings as settings_db
import db.history as history_db
import db.user_profiles as profiles_db
import db.untouchables as untouchables_db
from i18n import get_text
from utils.tg_safe import safe_edit
from handlers.admin_menu import callbacks as CB


def _pm_main_keyboard(lang: str, is_global_untouchable: bool) -> InlineKeyboardMarkup:
    toggle_label = get_text("pm_global_untouchable_on", lang) if is_global_untouchable else get_text("pm_global_untouchable_off", lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("pm_menu_toxicity", lang), callback_data=CB.PM_MENU_TOXICITY)],
        [InlineKeyboardButton(toggle_label, callback_data=CB.PM_TOGGLE_GLOBAL_UNTOUCHABLE)],
        [InlineKeyboardButton(get_text("pm_menu_dossier", lang), callback_data=CB.PM_MY_DOSSIER)],
        [InlineKeyboardButton(get_text("pm_menu_reset_me", lang), callback_data=CB.PM_RESET_ME)],
        [InlineKeyboardButton(get_text("menu_exit", lang), callback_data=CB.PM_EXIT)],
    ])


def _pm_toxicity_keyboard(lang: str, current: int) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for level in range(1, 6):
        text = f"● {level}" if level == current else str(level)
        row.append(InlineKeyboardButton(text, callback_data=CB.PM_SET_TOXICITY(level)))
    rows.append(row)
    rows.append([InlineKeyboardButton(get_text("menu_back", lang), callback_data=CB.PM_MENU_MAIN)])
    return InlineKeyboardMarkup(rows)


async def send_pm_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, edit: bool = False) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    global_flag = await untouchables_db.is_globally_protected(user.id)
    text = get_text("pm_menu_title", lang)
    keyboard = _pm_main_keyboard(lang, global_flag)

    if edit and update.callback_query:
        await safe_edit(update, text, keyboard)
    else:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def show_pm_toxicity_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, settings: dict, lang: str) -> None:
    await safe_edit(
        update,
        get_text("pm_toxicity_title", lang, current=settings["toxicity_level"]),
        _pm_toxicity_keyboard(lang, settings["toxicity_level"]),
    )


async def handle_pm_set_toxicity(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    level: int,
    settings: dict,
    lang: str,
) -> None:
    chat_id = update.effective_chat.id
    await settings_db.set_toxicity(chat_id, level)
    settings["toxicity_level"] = level
    await update.callback_query.answer(get_text("toxicity_saved", lang, level=level), show_alert=False)
    await show_pm_toxicity_menu(update, context, settings, lang)


async def handle_pm_toggle_global_untouchable(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> None:
    user = update.effective_user
    if not user:
        return

    is_on = await untouchables_db.is_globally_protected(user.id)
    if is_on:
        await untouchables_db.remove_global(user.id)
        await update.callback_query.answer(get_text("pm_global_untouchable_disabled", lang), show_alert=False)
    else:
        await untouchables_db.add_global(user.id, user.username or user.full_name)
        await update.callback_query.answer(get_text("pm_global_untouchable_enabled", lang), show_alert=False)

    await send_pm_settings_menu(update, context, lang, edit=True)


async def handle_pm_show_dossier(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user:
        return

    summary = await history_db.get_user_summary(user.id)
    if not summary:
        text = get_text("pm_dossier_none", lang)
        if chat:
            recent = await history_db.get_recent_for_user(user.id, chat.id, limit=5)
            user_msgs = [m["content"] for m in recent if m["role"] == "user"]
            if user_msgs:
                snippet = "\n".join(f"• {m}" for m in user_msgs[-3:])
                text += "\n\n" + get_text("view_summary_recent_messages", lang) + "\n" + snippet
    else:
        text = get_text("pm_dossier", lang, summary=summary)

    plain = text
    if len(plain) > 200:
        plain = plain[:197] + "..."
    await update.callback_query.answer(plain, show_alert=True)


async def handle_pm_reset_me_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> None:
    await safe_edit(
        update,
        get_text("pm_reset_confirm_text", lang),
        InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text("pm_reset_confirm_btn", lang), callback_data=CB.PM_RESET_ME_CONFIRM)],
            [InlineKeyboardButton(get_text("menu_back", lang), callback_data=CB.PM_MENU_MAIN)],
        ]),
    )


async def handle_pm_reset_me_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> None:
    user = update.effective_user
    if not user:
        return

    await history_db.delete_everywhere_for_user(user.id)
    await profiles_db.delete_everywhere_for_user(user.id)
    await untouchables_db.delete_everywhere_for_user(user.id)
    await untouchables_db.remove_global(user.id)

    await update.callback_query.answer(get_text("pm_reset_done", lang), show_alert=True)
    await send_pm_settings_menu(update, context, lang, edit=True)
