"""
handlers/messages.py — Main incoming message handler.

Decision tree for every non-command text message:

    1. Ignore messages shorter than min_words.
    2. Is this a reply TO A BOT MESSAGE?
           → Check user cooldown.
           → If OK: collect reply chain → get_reply → respond.
    3. Is this a reply to any other message?
           → Collect reply chain for context.
           → Fall through to frequency check.
    4. Frequency check: increment per-chat counter, fire when
       counter % random(freq_min, freq_max) == 0.
    5. If frequency check passes: get_reply → respond.

All settings are loaded fresh from DB on each message so admin changes
take effect immediately without a restart.
"""

import logging
import random
from collections import defaultdict

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

import db.chat_settings as settings_db
from db.chats import upsert_chat
import db.history as history_db
from ai.responder import get_reply
from i18n import get_text
from utils.rate_limiter import check_and_set
from utils.reply_chain import collect_chain

logger = logging.getLogger(__name__)

# Per-chat message counters for frequency gating.
# Key: chat_id, Value: int (rolling count since last bot reply)
# Reset to 0 each time the bot decides to reply.
_msg_counters: dict[int, int] = defaultdict(int)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Core message handler — applies all filtering and frequency logic
    before deciding whether to call the LLM.
    """
    message = update.effective_message
    user    = update.effective_user
    chat    = update.effective_chat

    if not message or not message.text or not user or not chat:
        return

    text     = message.text.strip()
    chat_id  = chat.id
    user_id  = user.id
    username = user.username or user.full_name

    # --- Load current chat settings ---
    settings     = await settings_db.get_or_create(chat_id)
    # Auto-register chat — backfills chats that predate lifecycle tracking
    await upsert_chat(chat_id, chat.title or "", chat.type)
    lang         = settings["lang"]
    toxicity     = settings["toxicity_level"]
    freq_min     = settings["freq_min"]
    freq_max     = settings["freq_max"]
    cooldown_sec = settings["reply_cooldown_sec"]
    chain_depth  = settings["reply_chain_depth"]
    min_words    = settings["min_words"]

    # --- 1. Word count gate ---
    word_count = len(text.split())
    logger.info(
        "Message received chat_id=%d user_id=%d words=%d min_words=%d",
        chat_id, user_id, word_count, min_words,
    )
    if word_count < min_words:
        logger.debug(
            "Message too short (%d words < %d) — ignored chat_id=%d user_id=%d",
            word_count, min_words, chat_id, user_id,
        )
        return

    bot_id = context.bot.id
    is_reply_to_bot = (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == bot_id
    )
    is_any_reply = message.reply_to_message is not None

    # --- Collect reply chain context if this is any kind of reply ---
    extra_context: list[dict] = []
    if is_any_reply:
        extra_context = await collect_chain(message, bot_id, max_depth=chain_depth)

    should_reply = False

    # --- 2. Direct reply to the bot → always reply if cooldown allows ---
    if is_reply_to_bot:
        if check_and_set(chat_id, user_id, cooldown_sec):
            should_reply = True
            logger.debug(
                "Direct reply to bot, cooldown passed chat_id=%d user_id=%d",
                chat_id, user_id,
            )
        else:
            logger.debug(
                "Direct reply to bot blocked by cooldown chat_id=%d user_id=%d",
                chat_id, user_id,
            )
            return

    # --- 3. Frequency check for non-bot-reply messages ---
    if not is_reply_to_bot:
        _msg_counters[chat_id] += 1
        threshold = random.randint(freq_min, freq_max)

        if _msg_counters[chat_id] >= threshold:
            _msg_counters[chat_id] = 0
            should_reply = True
            logger.debug(
                "Frequency gate passed threshold=%d chat_id=%d",
                threshold, chat_id,
            )

    if not should_reply:
        return

    # --- Fire the LLM call ---
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        reply = await get_reply(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            user_text=text,
            toxicity_level=toxicity,
            lang=lang,
            extra_context=extra_context,
        )
    except Exception as exc:
        logger.error("get_reply failed chat_id=%d: %s", chat_id, exc)
        reply = get_text("error_generic", lang)

    await message.reply_text(reply)
