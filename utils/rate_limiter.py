"""
utils/rate_limiter.py — In-memory per-user cooldown tracker.

Stores the timestamp of the last bot reply to each (chat_id, user_id) pair.
Uses a plain dict — no external dependency, no persistence across restarts
(which is fine: cooldowns are short-lived UX guards, not business logic).

check_and_set() is the single public API:
    - Returns True  → cooldown has passed, reply is allowed, timestamp updated
    - Returns False → still cooling down, caller should skip the reply
"""

import time
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


class _Entry(NamedTuple):
    timestamp: float   # unix time of last reply


# Key: (chat_id, user_id) → _Entry
_cache: dict[tuple[int, int], _Entry] = {}


def check_and_set(chat_id: int, user_id: int, cooldown_sec: int) -> bool:
    """
    Check whether the cooldown for (chat_id, user_id) has expired.

    If yes  → record current time and return True  (reply is allowed).
    If no   → return False without updating the timestamp.

    A cooldown_sec of 0 disables rate limiting entirely for that chat.
    """
    if cooldown_sec <= 0:
        return True

    key = (chat_id, user_id)
    now = time.monotonic()
    entry = _cache.get(key)

    if entry is not None:
        elapsed = now - entry.timestamp
        if elapsed < cooldown_sec:
            logger.debug(
                "Cooldown active chat_id=%d user_id=%d elapsed=%.1fs limit=%ds",
                chat_id, user_id, elapsed, cooldown_sec,
            )
            return False

    _cache[key] = _Entry(timestamp=now)
    return True


def reset(chat_id: int, user_id: int) -> None:
    """Remove the cooldown entry for a user, allowing an immediate reply."""
    _cache.pop((chat_id, user_id), None)


def reset_chat(chat_id: int) -> int:
    """
    Remove all cooldown entries for an entire chat.
    Returns the number of entries removed.
    """
    keys_to_remove = [k for k in _cache if k[0] == chat_id]
    for k in keys_to_remove:
        del _cache[k]
    return len(keys_to_remove)
