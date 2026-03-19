"""
handlers/admin_menu/untouchables_menu.py — Untouchable users submenu.

Admins can inspect and remove users from the untouchable list.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db.untouchables as untouchables_db
from i18n import get_text
from utils.tg_safe import safe_edit
from handlers.admin_menu.callbacks import MENU_MAIN, UNTOUCHABLE_REMOVE


async def show_untouchables_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    chat_id = update.effective_chat.id
    users = await untouchables_db.list_for_chat(chat_id)

    rows = []
    if not users:
        rows.append([
            InlineKeyboardButton(
                get_text("untouchables_list_empty", lang),
                callback_data="noop",
            )
        ])
    else:
        for user in users[:25]:
            if user.get("username"):
                name = f"@{str(user['username']).lstrip('@')}"
            else:
                name = f"id:{user['user_id']}"
            rows.append([
                InlineKeyboardButton(
                    f"✕ {name}",
                    callback_data=UNTOUCHABLE_REMOVE(user["user_id"]),
                )
            ])

    rows.append([InlineKeyboardButton(get_text("menu_back", lang), callback_data=MENU_MAIN)])

    await safe_edit(update, get_text("untouchables_title", lang), InlineKeyboardMarkup(rows))


async def handle_untouchable_remove(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    settings: dict,
    lang: str,
) -> None:
    chat_id = update.effective_chat.id
    deleted = await untouchables_db.remove(chat_id, user_id)

    if deleted > 0:
        await update.callback_query.answer(get_text("untouchable_removed", lang), show_alert=False)
    else:
        await update.callback_query.answer(get_text("untouchable_not_found", lang), show_alert=False)

    await show_untouchables_menu(update, context, settings, lang)
