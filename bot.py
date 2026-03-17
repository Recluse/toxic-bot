"""
bot.py — Application entry point.

Responsibilities:
    - Load config and validate environment on startup
    - Run DB migrations
    - Initialise the DB connection pool
    - Register all command and message handlers
    - Register the single global CallbackQueryHandler
    - Start polling
"""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import config
from db.pool import init_pool, close_pool
from db.migrations import run_migrations

# --- Handlers ---
from handlers.commands_public import (
    cmd_start,
    cmd_help,
    cmd_about,
    cmd_reset,
    cmd_toxicity_demo,
    cmd_toxic,
    cmd_dont_touch_me,
)
from handlers.commands_explain import cmd_explain
from handlers.messages import handle_message
from handlers.admin_menu.router import route_callback
from handlers.lifecycle import handle_my_chat_member
from handlers.superadmin import (
    cmd_sa_chats,
    cmd_sa_stats,
    broadcast_conversation,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def _on_startup(application: Application) -> None:
    """
    Post-init hook: runs after the Application is built but before polling starts.
    Order matters: pool first, migrations second.
    """
    await init_pool()
    await run_migrations()
    logger.info(
        "Bot started — model=%s vision=%s whisper=%s gateway=%s superadmins=%s",
        config.groq.model,
        config.groq.vision_model,
        config.groq.whisper_model,
        config.groq.base_url,
        list(config.superadmin_ids),
    )


async def _on_shutdown(application: Application) -> None:
    """Graceful shutdown: drain the DB pool."""
    await close_pool()
    logger.info("Bot stopped, DB pool closed")


async def _error_handler(update: object, context) -> None:
    """
    Global error handler — catches all unhandled exceptions from any handler.
    Prevents silent crashes and missing tracebacks in logs.
    """
    logger.error(
        "Unhandled exception processing update: %s",
        context.error,
        exc_info=context.error,
    )


def _add_settings_command(app: Application) -> None:
    """
    Register /settings as an alias that opens the main admin menu directly.
    Defined here to avoid a circular import between bot.py and admin_menu/.
    """
    from handlers.admin_menu.main_menu import send_main_menu
    from handlers.pm_settings import send_pm_settings_menu
    import db.chat_settings as settings_db
    from utils.admin_check import is_chat_admin
    from i18n import get_text
    from telegram.constants import ChatType

    async def cmd_settings(update, context):
        if update.effective_chat.type == ChatType.PRIVATE:
            settings = await settings_db.get_or_create(update.effective_chat.id)
            await send_pm_settings_menu(update, context, lang=settings["lang"], edit=False)
            return

        if not await is_chat_admin(update):
            try:
                await update.message.delete()
            except Exception:
                pass
            return

        settings = await settings_db.get_or_create(update.effective_chat.id)
        await send_main_menu(update, context, lang=settings["lang"], edit=False)

        # Remove the /settings command message in group chats to keep chat clean.
        try:
            await update.message.delete()
        except Exception:
            pass

    app.add_handler(CommandHandler("settings", cmd_settings))


def main() -> None:
    """Build and run the bot application."""
    app = (
        Application.builder()
        .token(config.telegram_token)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )

    app.add_error_handler(_error_handler)

    # --- Track bot membership changes in all chats ---
    app.add_handler(
        ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # --- Superadmin commands (PM only) ---
    app.add_handler(broadcast_conversation)
    app.add_handler(CommandHandler("sa_chats",    cmd_sa_chats,    filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("sa_stats",    cmd_sa_stats,    filters=filters.ChatType.PRIVATE))

    # --- Public commands ---
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("help",          cmd_help))
    app.add_handler(CommandHandler("about",         cmd_about))
    app.add_handler(CommandHandler("reset",         cmd_reset))
    app.add_handler(CommandHandler("toxicity_demo", cmd_toxicity_demo))
    app.add_handler(CommandHandler("toxic",         cmd_toxic))
    app.add_handler(CommandHandler("dont_touch_me", cmd_dont_touch_me))
    app.add_handler(CommandHandler("explain",       cmd_explain))

    # --- Admin settings menu ---
    _add_settings_command(app)

    # --- All inline keyboard callbacks routed through a single handler ---
    app.add_handler(CallbackQueryHandler(route_callback))

    # --- Main message handler — text, photos, voice, audio ---
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO)
            & ~filters.COMMAND,
            handle_message,
        )
    )

    logger.info("Starting polling")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
