"""
handlers/commands_public.py — Public commands available to all users.

Commands:
    /start         — Greet + language picker on first run
    /help          — Short in-group, full in DMs
    /about         — Current chat personality summary
    /reset         — Clear caller's own history
    /toxicity_demo — Show all 5 toxicity levels on a sample input
    /toxic         — Admin-only: force bot to reply to a specific message (reply to use)
"""

import logging
from telegram import Update, ReplyParameters
from telegram.ext import ContextTypes
from telegram.constants import ParseMode, ChatAction

import db.chat_settings as settings_db
import db.history as history_db
from ai.responder import get_reply
from ai.prompts import get_system_prompt
from ai.client import groq_client
from i18n import get_text
from config import config
from handlers.language_select import send_language_picker
from utils.admin_check import is_chat_admin
from utils.reply_chain import collect_chain

logger = logging.getLogger(__name__)

# Sample question used for /toxicity_demo — deliberately mild so the
# contrast between levels is clear and funny
_DEMO_QUESTION = "I think I'm pretty smart."


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start — Greet the user and offer language selection on first encounter.

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


async def cmd_toxicity_demo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    /toxicity_demo — Run the demo question through all five toxicity levels
    and send the results as a single formatted message.

    Each level gets its own API call so the responses are genuinely different.
    A typing action is shown while all calls are in-flight.
    """
    chat_id = update.effective_chat.id

    settings = await settings_db.get_or_create(chat_id)
    lang     = settings["lang"]

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    header = get_text("demo_header", lang)
    parts  = [header]

    for level in range(1, 6):
        level_name    = get_text(f"level_name_{level}", lang)
        label         = get_text("demo_level_label", lang, n=level, name=level_name)
        system_prompt = get_system_prompt(level=level, lang=lang)

        response = await groq_client.chat.completions.create(
            model=config.groq.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": _DEMO_QUESTION},
            ],
            temperature=config.groq.temperature,
            max_tokens=300,
        )
        reply = response.choices[0].message.content.strip()
        parts.append(f"{label}{reply}")

    await update.message.reply_text(
        "\n".join(parts),
        parse_mode=ParseMode.HTML,
    )


async def cmd_toxic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /toxic — Admin-only command to force the bot to reply to a specific message.

    Usage: reply to any message with /toxic
    The bot responds to the target message regardless of frequency counter
    or user cooldown. The /toxic command message itself is deleted after
    triggering to keep the chat clean.

    Non-admins: command is silently deleted — no public "admin only" message
    to avoid noise and prevent trolling.
    """
    chat_id  = update.effective_chat.id
    settings = await settings_db.get_or_create(chat_id)
    lang     = settings["lang"]

    # Must be used as a reply to another message
    if not update.message.reply_to_message:
        await update.message.reply_text(get_text("toxic_no_reply", lang))
        return

    # Admin check — silently delete the command if caller is not an admin.
    # Replying publicly with "admin only" is noisy and invites trolling.
    if not await is_chat_admin(update):
        try:
            await update.message.delete()
        except Exception:
            pass  # no delete permission — just ignore silently
        return

    target = update.message.reply_to_message
    text   = (target.text or target.caption or "").strip()

    if not text:
        await update.message.reply_text(get_text("toxic_no_text", lang))
        return

    # Delete the /toxic command message to keep the chat clean
    try:
        await update.message.delete()
    except Exception:
        pass  # bot may lack delete permission — non-critical

    target_user     = target.from_user
    target_user_id  = target_user.id if target_user else update.effective_user.id
    target_username = (
        target_user.username or target_user.full_name
        if target_user else "user"
    )

    extra_context = await collect_chain(
        target,
        context.bot.id,
        max_depth=settings["reply_chain_depth"],
    )

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        reply = await get_reply(
            chat_id=chat_id,
            user_id=target_user_id,
            username=target_username,
            user_text=text,
            toxicity_level=settings["toxicity_level"],
            lang=lang,
            extra_context=extra_context,
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
