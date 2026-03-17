"""
db/chat_settings.py — CRUD for the chat_settings table.

All public functions are async and use the global pool from db/pool.py.
`get_or_create` is the main entry point — call it on every incoming update
to ensure a settings row exists before reading any field.
"""

import logging
from db.pool import get_pool
from config import config

logger = logging.getLogger(__name__)

# The set of columns that may be updated via update_field().
# Acts as a whitelist to prevent SQL injection if a column name
# were ever constructed from external input.
_ALLOWED_FIELDS = frozenset({
    "lang",
    "toxicity_level",
    "freq_min",
    "freq_max",
    "reply_cooldown_sec",
    "explain_cooldown_min",
    "reply_chain_depth",
    "min_words",
})


async def get_or_create(chat_id: int) -> dict:
    """
    Return settings for a chat, inserting a defaults row on first encounter.

    Uses INSERT ... ON CONFLICT DO NOTHING so concurrent coroutines won't
    produce duplicate-key errors; in case of a race the second coroutine
    falls through to a plain SELECT.
    """
    pool = get_pool()
    d = config.defaults

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM chat_settings WHERE chat_id = $1",
            chat_id,
        )

        if row is None:
            row = await conn.fetchrow(
                """
                INSERT INTO chat_settings
                    (chat_id, lang, toxicity_level, freq_min, freq_max,
                     reply_cooldown_sec, explain_cooldown_min, reply_chain_depth, min_words)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (chat_id) DO NOTHING
                RETURNING *
                """,
                chat_id,
                config.bot.default_lang,
                d.toxicity_level,
                d.freq_min,
                d.freq_max,
                d.reply_cooldown_sec,
                d.explain_cooldown_min,
                d.reply_chain_depth,
                d.min_words,
            )

            if row is None:
                # Another coroutine won the race — just read the existing row
                row = await conn.fetchrow(
                    "SELECT * FROM chat_settings WHERE chat_id = $1",
                    chat_id,
                )

            logger.info("Inserted default settings for chat_id=%d", chat_id)

    return dict(row)


async def update_field(chat_id: int, field: str, value) -> None:
    """
    Update a single field in chat_settings.
    Only fields listed in _ALLOWED_FIELDS are accepted.
    """
    if field not in _ALLOWED_FIELDS:
        raise ValueError(f"Attempt to update unknown field: {field!r}")

    pool = get_pool()
    async with pool.acquire() as conn:
        # f-string is safe here because field is validated against _ALLOWED_FIELDS
        await conn.execute(
            f"""
            UPDATE chat_settings
               SET {field} = $1,
                   updated_at = now()
             WHERE chat_id = $2
            """,
            value, chat_id,
        )
    logger.info("chat_id=%d field=%s new_value=%s", chat_id, field, value)


async def set_language(chat_id: int, lang: str) -> None:
    """Set the chat language. Accepted values: 'en', 'ru', 'ua'."""
    if lang not in ("en", "ru", "ua"):
        raise ValueError(f"Unknown language code: {lang!r}")
    await update_field(chat_id, "lang", lang)


async def set_toxicity(chat_id: int, level: int) -> None:
    """Set toxicity level 1–5."""
    if not 1 <= level <= 5:
        raise ValueError("toxicity_level must be between 1 and 5")
    await update_field(chat_id, "toxicity_level", level)


async def set_frequency(chat_id: int, freq_min: int, freq_max: int) -> None:
    """Update freq_min and freq_max in a single transaction."""
    if freq_min < 1 or freq_max < freq_min:
        raise ValueError(f"Invalid frequency range: min={freq_min} max={freq_max}")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE chat_settings
               SET freq_min = $1,
                   freq_max = $2,
                   updated_at = now()
             WHERE chat_id = $3
            """,
            freq_min, freq_max, chat_id,
        )
    logger.info("chat_id=%d frequency set to %d–%d", chat_id, freq_min, freq_max)


async def set_explain_cooldown(chat_id: int, minutes: int) -> None:
    """Set /explain cooldown in minutes for group chats (10..600, step 10)."""
    if minutes < 10 or minutes > 600 or minutes % 10 != 0:
        raise ValueError("explain_cooldown_min must be in range 10..600 with step 10")
    await update_field(chat_id, "explain_cooldown_min", minutes)
