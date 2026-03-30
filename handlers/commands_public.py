"""
handlers/commands_public.py — Public commands available to all users.

Commands:
    /start         — Greet + language picker on first run
    /help          — Short in-group, full in DMs
    /about         — Current chat personality summary
    /reset         — Clear caller's own history
    /toxic         — Admin-only: force bot to reply to a specific message (reply to use)
"""

import logging
from telegram import Update, ReplyParameters
from telegram.ext import ContextTypes
from telegram.constants import ParseMode, ChatAction, ChatType
from ai.vision import get_image_base64

import db.chat_settings as settings_db
import db.history as history_db
import db.untouchables as untouchables_db
from ai.responder import get_reply
from i18n import get_text
from handlers.language_select import send_language_picker
from utils.admin_check import is_chat_admin
from utils.prompt_injection_guard import (
    build_injection_payload,
    detect_prompt_injection,
    log_injection_event,
    notify_superadmins_injection_event,
)
from utils.rate_limiter import check_and_set_toxic
from utils.reply_chain import collect_chain
from utils.tg_sender import resolve_message_actor
from utils.tg_safe import send_ephemeral_text

logger = logging.getLogger(__name__)


async def _maybe_delete_command(update: Update) -> None:
    """Delete a command message if it was sent in a non-private chat."""
    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        try:
            await update.message.delete()
        except Exception:
            pass


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start — Greet the user and offer language selection on first run.

    On first run (no DB row yet) the language picker is sent before the greeting.
    On subsequent runs the chat's current language is used.
    """
    chat_id = update.effective_chat.id
    is_pm   = update.effective_chat.type == update.effective_chat.PRIVATE

    settings = await settings_db.get_or_create(chat_id)
    lang     = settings["lang"]

    greeting_key = "start_pm" if is_pm else "start_group"
    await update.message.reply_text(get_text(greeting_key, lang))

    # Always show language picker on /start so it can be changed any time
    await send_language_picker(update, context, default_lang=lang)

    await _maybe_delete_command(update)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /help — Short version in groups, full version in private messages.
    """
    chat_id = update.effective_chat.id
    is_pm   = update.effective_chat.type == update.effective_chat.PRIVATE

    settings = await settings_db.get_or_create(chat_id)
    lang     = settings["lang"]

    key = "help_full" if is_pm else "help_short"
    await update.message.reply_text(get_text(key, lang), parse_mode=ParseMode.HTML)

    await _maybe_delete_command(update)


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /about — Display current personality settings for this chat.
    """
    chat_id    = update.effective_chat.id
    chat_title = update.effective_chat.title or "this chat"

    settings   = await settings_db.get_or_create(chat_id)
    lang       = settings["lang"]
    level_name = get_text(f"level_name_{settings['toxicity_level']}", lang)

    text = get_text(
        "about", lang,
        chat_title=chat_title,
        level=settings["toxicity_level"],
        level_name=level_name,
        chat_lang=lang.upper(),
        freq_min=settings["freq_min"],
        freq_max=settings["freq_max"],
        cooldown=settings["reply_cooldown_sec"],
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    await _maybe_delete_command(update)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /reset — Delete the calling user's own message history in this chat.
    Does not affect other users and does not clear the user profile summary.
    """
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    settings = await settings_db.get_or_create(chat_id)
    lang     = settings["lang"]

    deleted = await history_db.delete_for_user(chat_id, user_id)
    key = "reset_done" if deleted > 0 else "reset_no_history"
    await update.message.reply_text(get_text(key, lang))

    await _maybe_delete_command(update)


async def cmd_toxic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /toxic — Admin-only command to force the bot to reply to a specific message.

    Usage: reply to any message with /toxic.
    Supports text, captions, and photo messages.
    The /toxic command message itself is deleted after triggering.
    Non-admins: command is silently deleted.
    """
    message = update.effective_message
    chat    = update.effective_chat

    if not message or not chat:
        return

    caller_user_id, _, _ = resolve_message_actor(message, update.effective_user)
    if caller_user_id is None:
        return

    chat_id  = chat.id
    settings = await settings_db.get_or_create(chat_id)
    lang     = settings["lang"]

    if not check_and_set_toxic(chat_id, caller_user_id, cooldown_sec=300):
        await send_ephemeral_text(
            context,
            chat_id=chat_id,
            text=get_text("toxic_cooldown_active", lang),
            reply_to_message_id=message.message_id,
            delay_sec=30,
        )
        return

    if not message.reply_to_message:
        await send_ephemeral_text(
            context,
            chat_id=chat_id,
            text=get_text("toxic_no_reply", lang),
            reply_to_message_id=message.message_id,
            delay_sec=30,
        )
        return

    # Admin check — silently delete if caller is not an admin
    if not await is_chat_admin(update):
        try:
            await message.delete()
        except Exception:
            pass
        return

    target = message.reply_to_message
    text   = (target.text or target.caption or "").strip()

    detection = detect_prompt_injection(text)
    if detection.blocked:
        target_user_id, target_username, target_is_channel_sender = resolve_message_actor(
            target,
            target.from_user,
        )
        payload = build_injection_payload(
            chat=chat,
            actor_id=target_user_id,
            actor_username=getattr(target.from_user, "username", None),
            actor_full_name=(
                getattr(target.from_user, "full_name", None)
                if target.from_user
                else target_username
            ),
            actor_is_channel_sender=target_is_channel_sender,
            message_text=text,
            source=detection.source or "unknown",
            reason=detection.reason or "unknown",
        )

        log_injection_event(
            chat=chat,
            actor_id=target_user_id,
            actor_username=getattr(target.from_user, "username", None),
            actor_full_name=(
                getattr(target.from_user, "full_name", None)
                if target.from_user
                else target_username
            ),
            actor_is_channel_sender=target_is_channel_sender,
            message_text=text,
            source=detection.source or "unknown",
            reason=detection.reason or "unknown",
        )
        await notify_superadmins_injection_event(payload, context.bot)

        try:
            await message.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=chat_id,
            text=get_text("prompt_injection_blocked", lang),
            reply_parameters=ReplyParameters(
                message_id=target.message_id,
                chat_id=chat_id,
            ),
        )
        return

    # --- Handle photo target ---
    image_base64: str | None = None
    if target.photo:
        try:
            image_base64 = await get_image_base64(context.bot, target.photo[-1].file_id)
            # Frame the content so the LLM treats this as a user-sent photo,
            # not as a bot-generated description — keeps persona response natural
            if not text:
                text = "[user sent a photo with no caption]"
            else:
                text = f"[user sent a photo with caption: {text}]"
        except Exception as exc:
            logger.error("cmd_toxic: failed to download photo chat_id=%d: %s", chat_id, exc)
            await message.reply_text(get_text("error_generic", lang))
            return

    elif not text:
        await send_ephemeral_text(
            context,
            chat_id=chat_id,
            text=get_text("toxic_no_text", lang),
            reply_to_message_id=message.message_id,
            delay_sec=30,
        )
        return

    # Delete the /toxic command message to keep the chat clean
    try:
        await message.delete()
    except Exception:
        pass

    target_user_id, target_username, _ = resolve_message_actor(target, target.from_user)
    if target_user_id is None:
        target_user_id = caller_user_id
    if not target_username:
        target_username = "user"

    extra_context = await collect_chain(
        target,
        context.bot.id,
        max_depth=settings["reply_chain_depth"],
    )

    # Do not reply to users that opted out via /dont_touch_me.
    if await untouchables_db.is_protected(chat_id, target_user_id):
        await send_ephemeral_text(
            context,
            chat_id=chat_id,
            text=get_text("untouchable_blocked_toxic", lang),
            reply_to_message_id=target.message_id,
            delay_sec=30,
        )
        return

    if await untouchables_db.is_globally_protected(target_user_id):
        await send_ephemeral_text(
            context,
            chat_id=chat_id,
            text=get_text("untouchable_blocked_toxic", lang),
            reply_to_message_id=target.message_id,
            delay_sec=30,
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    logger.info(
        "LLM request mode=chat chat_id=%d user_id=%d reason=admin_toxic_command target_message_id=%d",
        chat_id,
        target_user_id,
        target.message_id,
    )

    try:
        reply = await get_reply(
            chat_id=chat_id,
            user_id=target_user_id,
            username=target_username,
            user_text=text,
            toxicity_level=settings["toxicity_level"],
            lang=lang,
            extra_context=extra_context,
            image_base64=image_base64,
        )
    except Exception as exc:
        logger.error("cmd_toxic get_reply failed chat_id=%d: %s", chat_id, exc)
        reply = get_text("error_generic", lang)

    await context.bot.send_message(
        chat_id=chat_id,
        text=reply,
        reply_parameters=ReplyParameters(
            message_id=target.message_id,
            chat_id=chat_id,
        ),
    )


async def cmd_dont_touch_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add caller to untouchable list for this group chat."""
    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return

    settings = await settings_db.get_or_create(chat.id)
    lang = settings["lang"]

    if chat.type == ChatType.PRIVATE:
        await message.reply_text(get_text("group_only", lang))
        return

    actor_id, actor_name, _ = resolve_message_actor(message, update.effective_user)
    if actor_id is None:
        return

    inserted = await untouchables_db.add(chat.id, actor_id, actor_name)

    if inserted:
        await send_ephemeral_text(
            context,
            chat_id=chat.id,
            text=get_text("dont_touch_me_added", lang),
            reply_to_message_id=message.message_id,
            delay_sec=30,
        )
    else:
        await send_ephemeral_text(
            context,
            chat_id=chat.id,
            text=get_text("dont_touch_me_already", lang),
            reply_to_message_id=message.message_id,
            delay_sec=30,
        )

    await _maybe_delete_command(update)
