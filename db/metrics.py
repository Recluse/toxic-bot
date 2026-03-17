"""
db/metrics.py — Simple persistent counters for bot analytics.
"""

from db.pool import get_pool


async def increment(metric_key: str, delta: int = 1) -> None:
    """Increase metric value by delta (creates row if missing)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_metrics (metric_key, value)
            VALUES ($1, $2)
            ON CONFLICT (metric_key)
            DO UPDATE SET value = bot_metrics.value + EXCLUDED.value
            """,
            metric_key,
            delta,
        )


async def get_all() -> dict[str, int]:
    """Return all metric counters as a dictionary."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT metric_key, value FROM bot_metrics"
        )
    return {r["metric_key"]: int(r["value"]) for r in rows}
