"""
ai/responder.py — Assembles LLM context and executes the main chat completion.

Flow:
    1. Load recent message history for the chat from DB
    2. Build system prompt (level + lang + user profile)
    3. Call Groq via CF gateway
    4. Persist both the user turn and the assistant reply to DB
    5. Fire-and-forget summarizer update
    6. Return reply text to the caller
"""

import asyncio
import logging
from openai import AsyncOpenAI

from ai.client import groq_client
from ai.prompts import get_system_prompt
from ai import summarizer
import db.history as history_db
import db.user_profiles as profiles_db
from config import config

logger = logging.getLogger(__name__)


async def get_reply(
    chat_id: int,
    user_id: int,
    username: str | None,
    user_text: str,
    toxicity_level: int,
    lang: str,
    extra_context: list[dict] | None = None,
) -> str:
    """
    Generate a bot reply for user_text in the context of chat_id.

    Args:
        chat_id:         Telegram chat ID.
        user_id:         Telegram user ID of the message author.
        username:        Telegram @username or display name (for logging / profile).
        user_text:       The user's message text.
        toxicity_level:  1–5 from chat_settings.
        lang:            Chat language code: 'en' | 'ru' | 'ua'.
        extra_context:   Optional list of {role, content} dicts from a reply chain,
                         prepended before the recent DB history.

    Returns:
        The assistant reply string.
    """
    # Fetch the stored user profile for personalised targeting
    profile = await profiles_db.get_or_create(chat_id, user_id, username)
    user_summary = profile.get("summary") or ""

    # Build system prompt with level, language, and user context
    system_prompt = get_system_prompt(
        level=toxicity_level,
        lang=lang,
        user_summary=user_summary,
    )

    # Load recent DB history (oldest first, ready for LLM)
    db_history = await history_db.get_recent(chat_id)

    # Assemble full message list:
    #   [system] + [reply chain context] + [db history] + [current user turn]
    # Reply chain context (if any) is injected before the stored history
    # so the model sees the thread being replied to as background, then
    # the ongoing conversation, then the new message.
    chain = extra_context or []
    messages = (
        [{"role": "system", "content": system_prompt}]
        + chain
        + db_history
        + [{"role": "user", "content": user_text}]
    )

    logger.info(
        "Calling Groq model=%s chat_id=%d user_id=%d level=%d lang=%s "
        "history=%d chain=%d",
        config.groq.model, chat_id, user_id,
        toxicity_level, lang, len(db_history), len(chain),
    )

    response = await groq_client.chat.completions.create(
        model=config.groq.model,
        messages=messages,
        temperature=config.groq.temperature,
        max_tokens=config.groq.max_tokens,
        top_p=config.groq.top_p,
    )

    reply_text = response.choices[0].message.content.strip()

    logger.info(
        "Groq reply received chat_id=%d tokens=%d",
        chat_id,
        response.usage.total_tokens if response.usage else -1,
    )

    # Persist conversation turns — both the incoming user message and the reply
    await history_db.append(chat_id, user_id, "user",      user_text)
    await history_db.append(chat_id, user_id, "assistant", reply_text)

    # Update the user's profile summary asynchronously.
    # We do not await this — it must never block the reply.
    asyncio.create_task(
        summarizer.update_profile(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            new_message=user_text,
            existing_summary=user_summary,
        )
    )

    return reply_text
