"""
handlers/messages.py — Main incoming message handler.

Decision tree for every non-command message (text / photo / voice / audio):

    1. Extract text: transcribe voice, describe photo if no caption.
    2. Ignore messages shorter than min_words (after extraction).
    3. In PRIVATE chat: always reply at toxicity level 5, skip frequency gate.
    4. Is this a reply TO A BOT MESSAGE?
           → Check user cooldown.
           → If OK: collect reply chain → get_reply → respond.
    5. Is this a reply to any other message?
           → Collect reply chain for context.
           → Fall through to frequency check.
    6. Frequency check: increment per-chat counter, fire when
       counter >= random(freq_min, freq_max).
    7. If frequency check passes: get_reply → respond.

voice/audio → transcriber → plain text → normal pipeline
photo       → vision model → description → normal pipeline
"""

import asyncio
import logging
import random
from collections import defaultdict

from telegram import Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import ContextTypes

import ai.summarizer as summarizer
import db.chat_settings as settings_db
import db.history as history_db
import db.metrics as metrics_db
import db.untouchables as untouchables_db
import db.user_profiles as profiles_db
from ai.client import vision_completion
from ai.modes import BotMode
from ai.responder import get_reply
from ai.transcriber import transcribe
from ai.vision import build_vision_message, get_image_base64
from db.chats import upsert_chat
from i18n import get_text
from utils.rate_limiter import check_and_set, check_pm_media_quota, check_pm_text_quota
from utils.prompt_injection_guard import (
    build_injection_payload,
    detect_prompt_injection,
    log_injection_event,
    notify_superadmins_injection_event,
)
from utils.reply_chain import collect_chain
from utils.tg_sender import resolve_message_actor

logger = logging.getLogger(__name__)

# Per-chat message counters for frequency gating.
# Resets to 0 each time the bot decides to reply.
_msg_counters: dict[int, int] = defaultdict(int)

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Core message handler — handles text, photo, voice, and audio messages.
    Applies all filtering and frequency logic before calling the LLM.
    """
    message = update.effective_message
    user    = update.effective_user
    chat    = update.effective_chat

    if not message or not chat:
        return

    chat_id = chat.id
    is_pm   = chat.type == ChatType.PRIVATE

    user_id, username, is_channel_sender = resolve_message_actor(message, user)
    if user_id is None:
        return

    # Ignore ordinary bot/service users, but keep channel-origin messages
    # (sender_chat) so each channel gets a distinct identity in history.
    if (not is_channel_sender) and user and (user_id == 777000 or user.is_bot):
        logger.debug("Ignored service/bot sender chat_id=%d user_id=%d", chat_id, user_id)
        return

    # --- Load settings and auto-register chat ---
    settings = await settings_db.get_or_create(chat_id)
    await upsert_chat(
        chat_id,
        chat.title or "",
        chat.type,
        username=getattr(chat, "username", None),
    )

    # Ensure the user is registered in the profile table so admins can see them.
    # This also gives a stable place to store the username even if no profile has
    # yet been generated via summarization.
    await profiles_db.get_or_create(chat_id, user_id, username)

    lang         = settings["lang"]
    toxicity     = settings["toxicity_level"]
    freq_min     = settings["freq_min"]
    freq_max     = settings["freq_max"]
    cooldown_sec = settings["reply_cooldown_sec"]
    chain_depth  = settings["reply_chain_depth"]
    min_words    = settings["min_words"]

    # Users in untouchable list are ignored in regular chat mode.
    # /explain is handled by a dedicated command handler and still works.
    if not is_pm and await untouchables_db.is_protected(chat_id, user_id):
        logger.debug("Ignored untouchable user chat_id=%d user_id=%d", chat_id, user_id)
        return

    if await untouchables_db.is_globally_protected(user_id):
        logger.debug("Ignored globally untouchable user chat_id=%d user_id=%d", chat_id, user_id)
        return

    # --- Extract text from different message types ---
    text:         str | None = None
    image_base64: str | None = None
    photo_file_id: str | None = None

    if message.text:
        await metrics_db.increment("processed_text")
        if is_pm and not check_pm_text_quota(chat_id, user_id):
            await message.reply_text(get_text("pm_text_hour_limit", lang))
            return
        text = message.text.strip()

    elif message.voice or message.audio:
        await metrics_db.increment("processed_voice")
        if is_pm and not check_pm_media_quota(chat_id, user_id):
            await message.reply_text(get_text("pm_media_hour_limit", lang))
            return

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        file_id  = (message.voice or message.audio).file_id
        is_voice = message.voice is not None
        try:
            text = await transcribe(context.bot, file_id, is_voice=is_voice)
            logger.debug("Transcribed voice chat_id=%d user_id=%d len=%d",
                         chat_id, user_id, len(text))
        except Exception as exc:
            logger.error("Transcription failed chat_id=%d: %s", chat_id, exc)
            return

    elif message.photo:
        await metrics_db.increment("processed_image")
        if is_pm and not check_pm_media_quota(chat_id, user_id):
            await message.reply_text(get_text("pm_media_hour_limit", lang))
            return

        # Do not call the vision model unless we decide to reply.
        # Determine word count from caption only (if any) for gating.
        photo_file_id = message.photo[-1].file_id
        text = (message.caption or "").strip()

    if not text and not photo_file_id:
        return

    bot_id          = context.bot.id
    is_reply_to_bot = (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == bot_id
    )

    detection = detect_prompt_injection(text)
    if detection.blocked:
        payload = build_injection_payload(
            chat=chat,
            actor_id=user_id,
            actor_username=getattr(user, "username", None),
            actor_full_name=(getattr(user, "full_name", None) if user else username),
            actor_is_channel_sender=is_channel_sender,
            message_text=text,
            source=detection.source or "unknown",
            reason=detection.reason or "unknown",
        )

        log_injection_event(
            chat=chat,
            actor_id=user_id,
            actor_username=getattr(user, "username", None),
            actor_full_name=(getattr(user, "full_name", None) if user else username),
            actor_is_channel_sender=is_channel_sender,
            message_text=text,
            source=detection.source or "unknown",
            reason=detection.reason or "unknown",
        )
        await notify_superadmins_injection_event(payload, context.bot)

        # In groups, only react when user directly replies to the bot.
        # For random chat messages, silently drop here.
        if is_pm or is_reply_to_bot:
            await context.bot.send_message(
                chat_id=chat_id,
                text=get_text("prompt_injection_blocked", lang),
                reply_to_message_id=message.message_id,
            )
        else:
            logger.debug(
                "Ignored prompt-injection-like text in group message chat_id=%d user_id=%d source=%s",
                chat_id,
                user_id,
                detection.source,
            )
        return

    # --- 1. Word count gate (skip in PM — PM always responds) ---
    word_count = len(text.split())
    logger.info(
        "Message received chat_id=%d user_id=%d words=%d min_words=%d type=%s",
        chat_id, user_id, word_count, min_words,
        "voice" if message.voice else "photo" if message.photo else "text",
    )

    if not is_pm and word_count < min_words and not photo_file_id:
        logger.debug("Too short (%d < %d) — ignored chat_id=%d", word_count, min_words, chat_id)
        return

    is_any_reply = message.reply_to_message is not None
    is_forwarded = any([
        getattr(message, "forward_origin", None),
        getattr(message, "forward_from", None),
        getattr(message, "forward_from_chat", None),
        getattr(message, "forward_sender_name", None),
        getattr(message, "forward_date", None),
    ])
    is_linked_channel_post = bool(getattr(message, "is_automatic_forward", False))
    is_forward_like = is_forwarded or is_linked_channel_post

    # --- Collect reply chain context ---
    extra_context: list[dict] = []
    if is_any_reply:
        extra_context = await collect_chain(message, bot_id, max_depth=chain_depth)

    should_reply = False
    llm_reason: str | None = None

    # --- In PM: always reply ---
    if is_pm:
        should_reply = True
        llm_reason = "pm_always_reply"

    # --- 2. Direct reply to bot → always reply if cooldown allows ---
    elif is_reply_to_bot:
        if check_and_set(chat_id, user_id, cooldown_sec):
            should_reply = True
            llm_reason = "direct_reply_to_bot_cooldown_passed"
            logger.debug("Direct reply, cooldown passed chat_id=%d user_id=%d", chat_id, user_id)
        else:
            logger.debug("Cooldown blocked chat_id=%d user_id=%d", chat_id, user_id)
            return

    # --- 3. Frequency gate for non-bot-reply group messages ---
    else:
        if is_forward_like:
            logger.debug(
                "Skipped random reply for forward/channel post chat_id=%d user_id=%d",
                chat_id,
                user_id,
            )
            return
        _msg_counters[chat_id] += 1
        threshold = random.randint(freq_min, freq_max)
        if _msg_counters[chat_id] >= threshold:
            _msg_counters[chat_id] = 0
            should_reply           = True
            llm_reason = f"frequency_gate_passed(threshold={threshold})"
            logger.debug("Frequency gate passed threshold=%d chat_id=%d", threshold, chat_id)

    if not should_reply:
        return

    # Update the user's profile only for messages that passed reply gating.
    if text and not history_db.is_noise(text):
        existing_summary = await history_db.get_user_summary(user_id)
        try:
            context.application.create_task(
                summarizer.update_profile(
                    chat_id=chat_id,
                    user_id=user_id,
                    username=username,
                    new_message=text,
                    existing_summary=existing_summary or "",
                )
            )
        except Exception:
            asyncio.create_task(
                summarizer.update_profile(
                    chat_id=chat_id,
                    user_id=user_id,
                    username=username,
                    new_message=text,
                    existing_summary=existing_summary or "",
                )
            )

    # --- Fire the LLM call ---
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    logger.info(
        "LLM request mode=chat chat_id=%d user_id=%d reason=%s type=%s channel_sender=%s forward_like=%s",
        chat_id,
        user_id,
        llm_reason or "unknown",
        "voice" if message.voice else "photo" if message.photo else "text",
        is_channel_sender,
        is_forward_like,
    )

    # If the selected message is a photo, describe it now (post-frequency gating).
    if photo_file_id:
        try:
            image_base64 = await get_image_base64(context.bot, photo_file_id)
            desc_messages = [build_vision_message(
                image_base64=image_base64,
                prompt=(text or "Describe this image briefly in one sentence."),
            )]
            _description = await vision_completion(desc_messages)
            text = f"[user sent a photo: {_description}]"
            logger.debug("Vision description chat_id=%d user_id=%d", chat_id, user_id)
        except Exception as exc:
            logger.error("Vision failed chat_id=%d: %s", chat_id, exc)
            return

    try:
        reply = await get_reply(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            user_text=text,
            toxicity_level=toxicity,
            lang=lang,
            extra_context=extra_context,
            mode=BotMode.CHAT,
            image_base64=image_base64,
        )
    except Exception as exc:
        logger.error("get_reply failed chat_id=%d: %s", chat_id, exc)
        reply = get_text("error_generic", lang)

    # Use explicit send_message with reply_to_message_id instead of
    # message.reply_text — if the triggering message was deleted before
    # this point (e.g. by a /toxic or /explain handler), reply_text silently
    # drops the reply_to_message_id and sends to chat without threading.
    await context.bot.send_message(
        chat_id=chat_id,
        text=reply,
        reply_to_message_id=message.message_id,
    )
