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
_explain_cache: dict[tuple[int, int], _Entry] = {}
_toxic_cache: dict[tuple[int, int], _Entry] = {}
_explain_pm_quota: dict[tuple[int, int], list[float]] = {}
_pm_media_quota: dict[tuple[int, int], list[float]] = {}
_pm_text_quota: dict[tuple[int, int], list[float]] = {}


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


def check_and_set_explain(chat_id: int, user_id: int, cooldown_sec: int) -> bool:
    """Check and set cooldown for /explain separately from normal replies."""
    if cooldown_sec <= 0:
        return True

    key = (chat_id, user_id)
    now = time.monotonic()
    entry = _explain_cache.get(key)

    if entry is not None:
        elapsed = now - entry.timestamp
        if elapsed < cooldown_sec:
            logger.debug(
                "Explain cooldown active chat_id=%d user_id=%d elapsed=%.1fs limit=%ds",
                chat_id, user_id, elapsed, cooldown_sec,
            )
            return False

    _explain_cache[key] = _Entry(timestamp=now)
    return True


def reset_chat_explain(chat_id: int) -> int:
    """Remove all /explain cooldown entries for a chat."""
    keys_to_remove = [k for k in _explain_cache if k[0] == chat_id]
    for k in keys_to_remove:
        del _explain_cache[k]
    return len(keys_to_remove)


def check_and_set_toxic(chat_id: int, user_id: int, cooldown_sec: int = 300) -> bool:
    """Check and set cooldown for /toxic command (default 5 minutes)."""
    if cooldown_sec <= 0:
        return True

    key = (chat_id, user_id)
    now = time.monotonic()
    entry = _toxic_cache.get(key)

    if entry is not None and (now - entry.timestamp) < cooldown_sec:
        return False

    _toxic_cache[key] = _Entry(timestamp=now)
    return True


def _check_quota(cache: dict[tuple[int, int], list[float]], chat_id: int, user_id: int, max_count: int, window_sec: int) -> bool:
    """Sliding-window quota check. Returns True if action is allowed."""
    key = (chat_id, user_id)
    now = time.monotonic()
    start = now - window_sec

    events = [t for t in cache.get(key, []) if t >= start]
    if len(events) >= max_count:
        cache[key] = events
        return False

    events.append(now)
    cache[key] = events
    return True


def check_pm_explain_quota(chat_id: int, user_id: int) -> bool:
    """Allow at most 5 /explain requests per hour in private chats."""
    return _check_quota(_explain_pm_quota, chat_id, user_id, max_count=5, window_sec=3600)


def check_pm_media_quota(chat_id: int, user_id: int) -> bool:
    """Allow at most 5 media (photo/voice/audio) messages per hour in private chats."""
    return _check_quota(_pm_media_quota, chat_id, user_id, max_count=5, window_sec=3600)


def check_pm_text_quota(chat_id: int, user_id: int) -> bool:
    """Allow at most 10 text requests per hour in private chats."""
    return _check_quota(_pm_text_quota, chat_id, user_id, max_count=10, window_sec=3600)
