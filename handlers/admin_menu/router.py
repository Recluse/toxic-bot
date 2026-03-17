"""
handlers/admin_menu/router.py — Central callback router for the settings menu.

All InlineKeyboardButton presses from the admin menu funnel through
route_callback(). It:
    1. Verifies admin status
    2. Loads current chat settings
    3. Dispatches to the correct submenu handler

This is the ONLY CallbackQueryHandler needed for the entire menu system.
Register it in bot.py with pattern=None (matches everything) and
let it filter internally — simpler than registering dozens of patterns.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

import db.chat_settings as settings_db
from i18n import get_text
from utils.admin_check import is_chat_admin
from handlers.language_select import handle_lang_callback
from handlers.admin_menu import callbacks as CB
from handlers.admin_menu.main_menu import send_main_menu
from handlers.admin_menu.toxicity_menu import (
    show_toxicity_menu, handle_set_toxicity,
)
from handlers.admin_menu.frequency_menu import (
    show_frequency_menu, handle_freq_adjust, handle_freq_save,
)
from handlers.admin_menu.simple_choice_menus import (
    show_cooldown_menu,   handle_set_cooldown,
    show_explain_cooldown_menu, handle_explain_cooldown_adjust, handle_explain_cooldown_save,
    show_chain_menu,      handle_set_chain,
    show_min_words_menu,  handle_set_min_words,
)
from handlers.admin_menu.user_management_menu import (
    show_user_mgmt_menu,
    handle_reset_chat, handle_reset_chat_confirm,
    handle_reset_user,  handle_view_summary,
)
from handlers.admin_menu.untouchables_menu import (
    show_untouchables_menu,
    handle_untouchable_remove,
)
from handlers.pm_settings import (
    send_pm_settings_menu,
    show_pm_toxicity_menu,
    handle_pm_set_toxicity,
    handle_pm_toggle_global_untouchable,
    handle_pm_show_dossier,
    handle_pm_reset_me_prompt,
    handle_pm_reset_me_confirm,
)

logger = logging.getLogger(__name__)


async def route_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Master callback dispatcher.

    Called for every CallbackQuery. Non-menu callbacks (e.g. language picker)
    are handled first by prefix, then menu callbacks by exact match or prefix.
    Unknown callbacks are silently acknowledged to stop the spinner.
    """
    query = update.callback_query
    if not query:
        return

    data    = query.data or ""
    chat_id = update.effective_chat.id

    # --- Language picker (available to all users, no admin check) ---
    if data.startswith(CB.PREFIX_LANG_SET):
        await handle_lang_callback(update, context)
        return

    # --- No-op buttons (used as static display labels in keyboards) ---
    if data == "noop":
        await query.answer()
        return

    # --- Private settings callbacks (no admin check) ---
    if data.startswith(CB.PREFIX_PM):
        settings = await settings_db.get_or_create(chat_id)
        lang = settings["lang"]

        if data == CB.PM_MENU_MAIN:
            await query.answer()
            await send_pm_settings_menu(update, context, lang, edit=True)
            return

        if data == CB.PM_MENU_TOXICITY:
            await query.answer()
            await show_pm_toxicity_menu(update, context, settings, lang)
            return

        if data.startswith(CB.PREFIX_PM_SET_TOXICITY):
            level = int(data.replace(CB.PREFIX_PM_SET_TOXICITY, ""))
            await handle_pm_set_toxicity(update, context, level, settings, lang)
            return

        if data == CB.PM_TOGGLE_GLOBAL_UNTOUCHABLE:
            await handle_pm_toggle_global_untouchable(update, context, lang)
            return

        if data == CB.PM_MY_DOSSIER:
            await handle_pm_show_dossier(update, context, lang)
            return

        if data == CB.PM_RESET_ME:
            await query.answer()
            await handle_pm_reset_me_prompt(update, context, lang)
            return

        if data == CB.PM_RESET_ME_CONFIRM:
            await handle_pm_reset_me_confirm(update, context, lang)
            return

        if data == CB.PM_EXIT:
            await query.answer()
            await query.message.delete()
            return

    # --- Admin check for everything else ---
    if not await is_chat_admin(update):
        await query.answer(get_text("admin_only", "en"), show_alert=True)
        return

    # Load fresh settings for every admin action
    settings = await settings_db.get_or_create(chat_id)
    lang     = settings["lang"]

    # --- Exit: delete the menu message ---
    if data == CB.MENU_EXIT:
        await query.answer()
        await query.message.delete()
        return

    # --- Main menu (navigate back) ---
    if data == CB.MENU_MAIN:
        await query.answer()
        await send_main_menu(update, context, lang, edit=True)
        return

    # --- Submenus: open ---
    if data == CB.MENU_TOXICITY:
        await query.answer()
        await show_toxicity_menu(update, context, settings, lang)
        return

    if data == CB.MENU_FREQUENCY:
        await query.answer()
        await show_frequency_menu(update, context, settings, lang)
        return

    if data == CB.MENU_COOLDOWN:
        await query.answer()
        await show_cooldown_menu(update, context, settings, lang)
        return

    if data == CB.MENU_CHAIN:
        await query.answer()
        await show_chain_menu(update, context, settings, lang)
        return

    if data == CB.MENU_EXPLAIN_COOLDOWN:
        await query.answer()
        await show_explain_cooldown_menu(update, context, settings, lang)
        return

    if data == CB.MENU_MIN_WORDS:
        await query.answer()
        await show_min_words_menu(update, context, settings, lang)
        return

    if data == CB.MENU_USER_MGMT:
        await query.answer()
        await show_user_mgmt_menu(update, context, settings, lang)
        return

    if data == CB.MENU_UNTOUCHABLES:
        await query.answer()
        await show_untouchables_menu(update, context, settings, lang)
        return

    # --- Toxicity: set value ---
    if data.startswith(CB.PREFIX_SET_TOXICITY):
        level = int(data.replace(CB.PREFIX_SET_TOXICITY, ""))
        await handle_set_toxicity(update, context, level, settings, lang)
        return

    # --- Frequency: adjust + save ---
    if data in (CB.FREQ_MIN_UP, CB.FREQ_MIN_DOWN, CB.FREQ_MAX_UP, CB.FREQ_MAX_DOWN):
        await handle_freq_adjust(update, context, data, settings, lang)
        return

    if data == CB.FREQ_SAVE:
        await handle_freq_save(update, context, settings, lang)
        return

    # --- Cooldown: set value ---
    if data.startswith(CB.PREFIX_SET_COOLDOWN):
        value = int(data.replace(CB.PREFIX_SET_COOLDOWN, ""))
        await handle_set_cooldown(update, context, value, settings, lang)
        return

    # --- Chain depth: set value ---
    if data.startswith(CB.PREFIX_SET_CHAIN):
        value = int(data.replace(CB.PREFIX_SET_CHAIN, ""))
        await handle_set_chain(update, context, value, settings, lang)
        return

    # --- Min words: set value ---
    if data.startswith(CB.PREFIX_SET_MIN_WORDS):
        value = int(data.replace(CB.PREFIX_SET_MIN_WORDS, ""))
        await handle_set_min_words(update, context, value, settings, lang)
        return

    # --- Explain cooldown: adjust + save ---
    if data in (CB.EXPLAIN_CD_DOWN, CB.EXPLAIN_CD_UP):
        await handle_explain_cooldown_adjust(update, context, data, settings, lang)
        return

    if data == CB.EXPLAIN_CD_SAVE:
        await handle_explain_cooldown_save(update, context, settings, lang)
        return

    # --- User management: actions ---
    if data == CB.RESET_CHAT:
        await handle_reset_chat(update, context, settings, lang)
        return

    if data == CB.RESET_CHAT_CONFIRM:
        await handle_reset_chat_confirm(update, context, settings, lang)
        return

    if data.startswith(CB.PREFIX_RESET_USER):
        user_id = int(data.replace(CB.PREFIX_RESET_USER, ""))
        await handle_reset_user(update, context, user_id, settings, lang)
        return

    if data.startswith(CB.PREFIX_VIEW_SUMMARY):
        user_id = int(data.replace(CB.PREFIX_VIEW_SUMMARY, ""))
        await handle_view_summary(update, context, user_id, settings, lang)
        return

    if data.startswith(CB.PREFIX_UNTOUCHABLE_REMOVE):
        user_id = int(data.replace(CB.PREFIX_UNTOUCHABLE_REMOVE, ""))
        await handle_untouchable_remove(update, context, user_id, settings, lang)
        return

    # --- Unknown callback — acknowledge silently to stop spinner ---
    logger.warning("Unhandled callback_data=%r chat_id=%d", data, chat_id)
    await query.answer()
