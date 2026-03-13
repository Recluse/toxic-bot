"""
ai/summarizer.py — Background user profile update.

After each user message the bot fires update_profile() as an asyncio task.
It sends the existing summary + the new message to a lighter/cheaper model
and overwrites the stored summary with the result.

The summary is a short psychological/behavioural note used by the main
responder to make replies more precisely targeted.  It is never shown
to the user directly (unless an admin requests it via the settings menu).
"""

import logging
from ai.client import groq_client
import db.user_profiles as profiles_db
from config import config

logger = logging.getLogger(__name__)

_SUMMARIZER_SYSTEM = """You are a silent background analyst.
Your job is to maintain a short (max 150 words), clinically precise
psychological and behavioural profile of a Telegram user based on
their messages.

Update the profile by integrating the new message with the existing notes.
Focus on:
- Communication style and patterns
- Recurring insecurities or emotional triggers
- Cognitive tendencies (black-and-white thinking, victim framing, etc.)
- What kind of validation or reaction they seem to seek
- Anything that could make a sharp, personalised response more effective

Output ONLY the updated profile text. No preamble, no labels, no commentary.
Write in English regardless of the user's language."""


async def update_profile(
    chat_id: int,
    user_id: int,
    username: str | None,
    new_message: str,
    existing_summary: str,
) -> None:
    """
    Generate an updated user summary and write it to the DB.

    This runs as a fire-and-forget asyncio.create_task() — exceptions
    are caught and logged so a summarizer failure never affects the
    main bot reply flow.
    """
    try:
        messages = [
            {"role": "system", "content": _SUMMARIZER_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Existing profile:\n{existing_summary or '(none yet)'}\n\n"
                    f"New message from user:\n{new_message}"
                ),
            },
        ]

        response = await groq_client.chat.completions.create(
            model=config.summarizer.model,
            messages=messages,
            temperature=config.summarizer.temperature,
            max_tokens=config.summarizer.max_tokens,
        )

        new_summary = response.choices[0].message.content.strip()

        await profiles_db.update_summary(
            chat_id=chat_id,
            user_id=user_id,
            summary=new_summary,
            username=username,
        )

        logger.debug(
            "Profile updated chat_id=%d user_id=%d len=%d",
            chat_id, user_id, len(new_summary),
        )

    except Exception as exc:
        # Summarizer errors are non-fatal — log and move on
        logger.warning(
            "Summarizer failed chat_id=%d user_id=%d: %s",
            chat_id, user_id, exc,
        )
