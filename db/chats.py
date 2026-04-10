"""
db/chats.py — Chat membership tracking CRUD and statistics.
"""

import logging

from db.pool import get_pool

logger = logging.getLogger(__name__)


async def upsert_chat(
    chat_id:   int,
    title:     str,
    chat_type: str,
    username:  str | None = None,
) -> bool:
    """
    Insert or update a chat record.
    Returns True if this is a newly inserted row (backfill detection).
    Uses xmax trick: xmax == 0 means INSERT, non-zero means UPDATE.
    """
    pool   = get_pool()
    is_new = await pool.fetchval(
        """
        INSERT INTO chats (chat_id, title, chat_type, username, active)
        VALUES ($1, $2, $3, $4, TRUE)
        ON CONFLICT (chat_id) DO UPDATE
            SET title     = EXCLUDED.title,
                chat_type = EXCLUDED.chat_type,
                username  = EXCLUDED.username,
                active    = TRUE
        RETURNING (xmax = 0)
        """,
        chat_id, title, chat_type, username,
    )
    return bool(is_new)


async def set_active(chat_id: int, active: bool) -> None:
    """Set the active flag for a chat. Called on kick/leave (False) or re-join (True)."""
    pool = get_pool()
    await pool.execute(
        "UPDATE chats SET active = $1 WHERE chat_id = $2",
        active, chat_id,
    )


async def list_chats(active_only: bool = True) -> list[dict]:
    """
    Return chats ordered by joined_at DESC.
    active_only=True  — only chats where bot is currently a member.
    active_only=False — full history including kicked chats.
    """
    pool  = get_pool()
    query = "SELECT chat_id, title, username, chat_type, active, joined_at FROM chats"
    if active_only:
        query += " WHERE active = TRUE"
    query += " ORDER BY joined_at DESC"
    rows = await pool.fetch(query)
    return [dict(r) for r in rows]


async def list_chats_with_stats(active_only: bool = True) -> list[dict]:
    """Return chats enriched with per-chat activity, history, and settings data."""
    pool = get_pool()
    query = """
    SELECT
        c.chat_id,
        c.title,
        c.username,
        c.chat_type,
        c.active,
        c.joined_at,
        cs.lang,
        cs.toxicity_level,
        cs.freq_min,
        cs.freq_max,
        cs.reply_cooldown_sec,
        cs.explain_cooldown_min,
        cs.reply_chain_depth,
        cs.min_words,
        COALESCE(hist.history_rows, 0) AS history_rows,
        COALESCE(hist.history_user_rows, 0) AS history_user_rows,
        COALESCE(hist.history_assistant_rows, 0) AS history_assistant_rows,
        COALESCE(hist.distinct_users, 0) AS distinct_users,
        hist.last_history_at,
        COALESCE(cm.processed_text, 0) AS processed_text,
        COALESCE(cm.processed_voice, 0) AS processed_voice,
        COALESCE(cm.processed_image, 0) AS processed_image,
        COALESCE(cm.processed_total, 0) AS processed_total,
        COALESCE(cm.chat_llm_requests, 0) AS chat_llm_requests,
        COALESCE(cm.chat_replies_sent, 0) AS chat_replies_sent,
        COALESCE(cm.explain_commands, 0) AS explain_commands,
        COALESCE(cm.explain_llm_requests, 0) AS explain_llm_requests,
        COALESCE(cm.explain_replies_sent, 0) AS explain_replies_sent,
        COALESCE(cm.toxic_commands, 0) AS toxic_commands,
        COALESCE(cm.toxic_llm_requests, 0) AS toxic_llm_requests,
        COALESCE(cm.toxic_replies_sent, 0) AS toxic_replies_sent,
        COALESCE(cm.prompt_injection_blocked, 0) AS prompt_injection_blocked,
        COALESCE(cm.prompt_injection_visible, 0) AS prompt_injection_visible,
        COALESCE(cm.prompt_injection_silent, 0) AS prompt_injection_silent,
        cm.last_metric_at,
        GREATEST(
            COALESCE(hist.last_history_at, TO_TIMESTAMP(0)),
            COALESCE(cm.last_metric_at, TO_TIMESTAMP(0)),
            COALESCE(c.joined_at, TO_TIMESTAMP(0))
        ) AS last_activity_at
    FROM chats c
    LEFT JOIN chat_settings cs
           ON cs.chat_id = c.chat_id
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) AS history_rows,
            COUNT(*) FILTER (WHERE role = 'user') AS history_user_rows,
            COUNT(*) FILTER (WHERE role = 'assistant') AS history_assistant_rows,
            COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL) AS distinct_users,
            MAX(created_at) AS last_history_at
        FROM message_history
        WHERE chat_id = c.chat_id
    ) hist ON TRUE
    LEFT JOIN LATERAL (
        SELECT
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'processed_text'), 0) AS processed_text,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'processed_voice'), 0) AS processed_voice,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'processed_image'), 0) AS processed_image,
            COALESCE(SUM(value) FILTER (WHERE metric_key IN ('processed_text', 'processed_voice', 'processed_image')), 0) AS processed_total,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'chat_llm_requests'), 0) AS chat_llm_requests,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'chat_replies_sent'), 0) AS chat_replies_sent,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'explain_commands'), 0) AS explain_commands,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'explain_llm_requests'), 0) AS explain_llm_requests,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'explain_replies_sent'), 0) AS explain_replies_sent,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'toxic_commands'), 0) AS toxic_commands,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'toxic_llm_requests'), 0) AS toxic_llm_requests,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'toxic_replies_sent'), 0) AS toxic_replies_sent,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'prompt_injection_blocked'), 0) AS prompt_injection_blocked,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'prompt_injection_visible'), 0) AS prompt_injection_visible,
            COALESCE(SUM(value) FILTER (WHERE metric_key = 'prompt_injection_silent'), 0) AS prompt_injection_silent,
            MAX(updated_at) AS last_metric_at
        FROM chat_metrics
        WHERE chat_id = c.chat_id
    ) cm ON TRUE
    """

    if active_only:
        query += " WHERE c.active = TRUE"

    query += """
    ORDER BY
        COALESCE(cm.processed_total, 0) DESC,
        COALESCE(hist.history_user_rows, 0) DESC,
        GREATEST(
            COALESCE(hist.last_history_at, TO_TIMESTAMP(0)),
            COALESCE(cm.last_metric_at, TO_TIMESTAMP(0)),
            COALESCE(c.joined_at, TO_TIMESTAMP(0))
        ) DESC,
        c.joined_at DESC
    """

    rows = await pool.fetch(query)
    return [dict(r) for r in rows]


async def get_stats() -> dict:
    """
    Return aggregate statistics for the superadmin /sa_stats command.
    Includes total/active/inactive counts and breakdown by chat type.
    """
    pool = get_pool()

    totals = dict(await pool.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE active = TRUE)  AS active,
            COUNT(*) FILTER (WHERE active = FALSE) AS inactive,
            COUNT(*)                               AS total
        FROM chats
        """,
    ))

    type_rows = await pool.fetch(
        """
        SELECT chat_type, COUNT(*) AS cnt
        FROM chats
        WHERE active = TRUE
        GROUP BY chat_type
        ORDER BY cnt DESC
        """,
    )
    totals["by_type"] = {r["chat_type"]: r["cnt"] for r in type_rows}

    has_history_user_id = bool(await pool.fetchval(
        """
        SELECT EXISTS (
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'message_history'
               AND column_name = 'user_id'
        )
        """
    ))

    has_user_summaries = bool(await pool.fetchval(
        "SELECT to_regclass('public.user_summaries') IS NOT NULL"
    ))
    has_user_profiles = bool(await pool.fetchval(
        "SELECT to_regclass('public.user_profiles') IS NOT NULL"
    ))

    users_in_history = 0
    if has_history_user_id:
        users_in_history = int(await pool.fetchval(
            """
            SELECT COUNT(DISTINCT user_id)
              FROM message_history
             WHERE user_id IS NOT NULL
            """
        ) or 0)

    if has_user_summaries:
        users_in_profiles = int(await pool.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM user_summaries"
        ) or 0)
    elif has_user_profiles:
        users_in_profiles = int(await pool.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM user_profiles"
        ) or 0)
    else:
        users_in_profiles = 0

    history_rows = int(await pool.fetchval("SELECT COUNT(*) FROM message_history") or 0)
    totals["users_in_history"] = users_in_history
    totals["users_in_profiles"] = users_in_profiles
    totals["history_rows"] = history_rows

    sizes = await pool.fetchrow(
        """
        SELECT
            pg_database_size(current_database()) AS db_total_bytes,
            CASE WHEN to_regclass('public.message_history') IS NULL
                 THEN 0
                 ELSE pg_total_relation_size(to_regclass('public.message_history'))
            END AS message_history_bytes,
            CASE
                WHEN to_regclass('public.user_summaries') IS NOT NULL
                    THEN pg_total_relation_size(to_regclass('public.user_summaries'))
                WHEN to_regclass('public.user_profiles') IS NOT NULL
                    THEN pg_total_relation_size(to_regclass('public.user_profiles'))
                ELSE 0
            END AS user_summaries_bytes,
            CASE WHEN to_regclass('public.chats') IS NULL
                 THEN 0
                 ELSE pg_total_relation_size(to_regclass('public.chats'))
            END AS chats_bytes,
            CASE WHEN to_regclass('public.bot_metrics') IS NULL
                 THEN 0
                 ELSE pg_total_relation_size(to_regclass('public.bot_metrics'))
            END AS bot_metrics_bytes,
              CASE WHEN to_regclass('public.chat_metrics') IS NULL
                  THEN 0
                  ELSE pg_total_relation_size(to_regclass('public.chat_metrics'))
              END AS chat_metrics_bytes,
            CASE WHEN to_regclass('public.untouchable_users') IS NULL
                 THEN 0
                 ELSE pg_total_relation_size(to_regclass('public.untouchable_users'))
            END AS untouchable_users_bytes
        """
    )
    totals["db_total_bytes"] = int(sizes["db_total_bytes"] or 0)
    totals["message_history_bytes"] = int(sizes["message_history_bytes"] or 0)
    totals["user_summaries_bytes"] = int(sizes["user_summaries_bytes"] or 0)
    totals["chats_bytes"] = int(sizes["chats_bytes"] or 0)
    totals["bot_metrics_bytes"] = int(sizes["bot_metrics_bytes"] or 0)
    totals["chat_metrics_bytes"] = int(sizes["chat_metrics_bytes"] or 0)
    totals["untouchable_users_bytes"] = int(sizes["untouchable_users_bytes"] or 0)
    return totals
