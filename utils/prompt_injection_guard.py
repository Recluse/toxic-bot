"""Prompt-injection guard helpers for user-provided text."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any
import unicodedata

from config import config

try:
    from prompt_shield import PromptScanner
except Exception:  # pragma: no cover - runtime env may not have optional dependency
    PromptScanner = None


_TAG_PATTERNS = (
    "<system>",
    "</system>",
    "<\\system>",
    "<admin>",
    "</admin>",
    "<\\admin>",
)
_SYSTEM_TAG_RE = re.compile(r"<\s*(?:/|\\)?\s*system\b[^>]*>", re.IGNORECASE)
_SYSTEM_TAG_ESCAPED_RE = re.compile(r"&lt;\s*(?:/|\\)?\s*system\b.*?&gt;", re.IGNORECASE)
_ADMIN_TAG_RE = re.compile(r"<\s*(?:/|\\)?\s*admin\b[^>]*>", re.IGNORECASE)
_ADMIN_TAG_ESCAPED_RE = re.compile(r"&lt;\s*(?:/|\\)?\s*admin\b.*?&gt;", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_BASE64_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])")
_EMOJI_VARIATION_SELECTORS = {"\ufe0e", "\ufe0f"}
_EMOJI_JOINER = "\u200d"
# Format chars (Unicode category "Cf") that are common in legitimate
# Telegram content (emoji ZWJ sequences, music-share invisible separators).
# Anything in category "Cf" outside this set is treated as smuggling.
_BENIGN_FORMAT_CHARS = {
    "\u200b",  # ZWSP - zero-width space (music-share separators)
    "\u200c",  # ZWNJ - zero-width non-joiner
    "\u200d",  # ZWJ  - emoji ZWJ sequences
    "\u2060",  # WJ   - word joiner
    "\ufeff",  # ZWNBSP / BOM
    "\ufe0e",  # variation selector text
    "\ufe0f",  # variation selector emoji
}
# Bidirectional control characters - never benign in user-supplied text;
# these can hide payloads inside visually innocuous strings.
_BIDI_CONTROL_RANGES = ((0x202A, 0x202E), (0x2066, 0x2069))
_CONTEXT_HINT_RE = re.compile(
    r"ignore\s+previous\s+instructions|system\s+prompt|developer\s+mode|dan\b|"
    r"reveal\s+instructions|repeat\s+everything\s+above|jailbreak",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InjectionDetectionResult:
    blocked: bool
    source: str | None = None
    reason: str | None = None


_scanner = PromptScanner(threshold="MEDIUM") if PromptScanner else None
_context_scanner = PromptScanner(threshold="LOW") if PromptScanner else None

_events_logger = logging.getLogger("prompt_injection_events")
if not _events_logger.handlers:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(logs_dir / "prompt_injection_events.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _events_logger.addHandler(handler)
    _events_logger.setLevel(logging.INFO)
    _events_logger.propagate = False


def _tag_matches(text: str) -> list[str]:
    lowered = text.lower()
    matches = [tag for tag in _TAG_PATTERNS if tag in lowered]

    if _SYSTEM_TAG_RE.search(text):
        matches.append("regex_system_tag")
    if _SYSTEM_TAG_ESCAPED_RE.search(text):
        matches.append("escaped_regex_system_tag")
    if _ADMIN_TAG_RE.search(text):
        matches.append("regex_admin_tag")
    if _ADMIN_TAG_ESCAPED_RE.search(text):
        matches.append("escaped_regex_admin_tag")

    deduped: list[str] = []
    for match in matches:
        if match not in deduped:
            deduped.append(match)
    return deduped


def _result_matches(result: Any) -> list[dict[str, Any]]:
    return [m for m in (getattr(result, "matches", []) or []) if isinstance(m, dict)]


def _is_url_payload_explained(text: str) -> bool:
    """encoding_base64_payload is benign if the only base64-shaped tokens are URLs."""
    if not _URL_RE.search(text):
        return False
    text_without_urls = _URL_RE.sub(" ", text)
    return _BASE64_TOKEN_RE.search(text_without_urls) is None


def _is_unicode_smuggling_benign(text: str) -> bool:
    """unicode_smuggling is benign if every invisible char is on the whitelist.

    Music-share posts and emoji ZWJ sequences trigger this match constantly,
    yet contain only ZWSP/ZWJ/ZWNJ/variation-selectors - none of which can
    smuggle a useful payload past the model.
    """
    for ch in text:
        if ch in _BENIGN_FORMAT_CHARS:
            continue
        if unicodedata.category(ch) == "Cf":
            # An unknown format char - could be a Tag (E0000-E007F) or
            # other deliberately-hidden payload. Block.
            return False
        cp = ord(ch)
        for start, end in _BIDI_CONTROL_RANGES:
            if start <= cp <= end:
                return False
        # Unicode "Tag" block - used to hide instructions inside benign text.
        if 0xE0000 <= cp <= 0xE007F:
            return False
    return True


def _strip_explained_matches(text: str, matches: list[dict[str, Any]]) -> set[str]:
    """Return the subset of match names that cannot be explained as FPs."""
    remaining: set[str] = set()
    for m in matches:
        name = m.get("name")
        if not name:
            continue
        if name == "encoding_base64_payload" and _is_url_payload_explained(text):
            continue
        if name == "unicode_smuggling" and _is_unicode_smuggling_benign(text):
            continue
        remaining.add(name)
    return remaining


def _format_result_reason(result: Any) -> str:
    matches = _result_matches(result)
    pretty_matches = "; ".join(
        f"{m.get('name')}[{m.get('category')},w={m.get('weight')}]"
        for m in matches[:12]
    )
    return (
        f"severity={getattr(result, 'severity', 'UNKNOWN')} "
        f"risk_score={getattr(result, 'risk_score', 'UNKNOWN')} "
        f"matches={pretty_matches or 'none'}"
    )


def contains_prompt_injection_markup(text: str | None) -> bool:
    """Return True when text contains system-tag injection markers."""
    if not text:
        return False
    return bool(_tag_matches(text))


def detect_prompt_injection(
    text: str | None,
    *,
    strict_context: bool = False,
) -> InjectionDetectionResult:
    """Detect prompt injection using tags, scanner, and stricter context checks."""
    if not text:
        return InjectionDetectionResult(blocked=False)

    tags = _tag_matches(text)
    if tags:
        return InjectionDetectionResult(
            blocked=True,
            source="tag",
            reason=f"matched_tags={','.join(tags)}",
        )

    if _scanner is None:
        return InjectionDetectionResult(blocked=False)

    try:
        result = _scanner.scan(text)
    except Exception as exc:
        logging.getLogger(__name__).warning("ai-injection-guard scan failed: %s", exc)
        return InjectionDetectionResult(blocked=False)

    if not result.is_safe:
        matches = _result_matches(result)
        remaining = _strip_explained_matches(text, matches)
        if not remaining:
            logging.getLogger(__name__).debug(
                "Suppressed ai-injection-guard false positive: %s",
                _format_result_reason(result),
            )
        else:
            return InjectionDetectionResult(
                blocked=True,
                source="ai-injection-guard",
                reason=_format_result_reason(result),
            )

    if strict_context and _context_scanner is not None:
        try:
            context_result = _context_scanner.scan(text)
        except Exception as exc:
            logging.getLogger(__name__).warning("context ai-injection-guard scan failed: %s", exc)
            context_result = None

        if context_result is not None and not context_result.is_safe:
            ctx_matches = _result_matches(context_result)
            ctx_remaining = _strip_explained_matches(text, ctx_matches)
            if ctx_remaining:
                return InjectionDetectionResult(
                    blocked=True,
                    source="ai-injection-guard-context",
                    reason=_format_result_reason(context_result),
                )
            logging.getLogger(__name__).debug(
                "Suppressed context ai-injection-guard false positive: %s",
                _format_result_reason(context_result),
            )

    if strict_context and _CONTEXT_HINT_RE.search(text):
        return InjectionDetectionResult(
            blocked=True,
            source="context-heuristic",
            reason="matched_common_injection_phrases",
        )

    return InjectionDetectionResult(blocked=False)


def log_injection_event(
    *,
    chat: Any,
    actor_id: int | None,
    actor_username: str | None,
    actor_full_name: str | None,
    actor_is_channel_sender: bool,
    message_text: str | None,
    source: str,
    reason: str,
) -> None:
    """Write a dedicated structured log record for every detected injection."""
    payload = build_injection_payload(
        chat=chat,
        actor_id=actor_id,
        actor_username=actor_username,
        actor_full_name=actor_full_name,
        actor_is_channel_sender=actor_is_channel_sender,
        message_text=message_text,
        source=source,
        reason=reason,
    )

    _events_logger.info(json.dumps(payload, ensure_ascii=False, default=str))


def build_injection_payload(
    *,
    chat: Any,
    actor_id: int | None,
    actor_username: str | None,
    actor_full_name: str | None,
    actor_is_channel_sender: bool,
    message_text: str | None,
    source: str,
    reason: str,
) -> dict[str, Any]:
    """Build a structured payload shared by file logs and superadmin alerts."""
    chat_dump: dict[str, Any] | None = None
    if chat is not None:
        to_dict = getattr(chat, "to_dict", None)
        if callable(to_dict):
            try:
                chat_dump = to_dict()
            except Exception:
                chat_dump = None

    payload = {
        "event": "prompt_injection_detected",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "reason": reason,
        "chat": {
            "id": getattr(chat, "id", None),
            "type": getattr(chat, "type", None),
            "title": getattr(chat, "title", None),
            "username": getattr(chat, "username", None),
            "full": chat_dump,
        },
        "user": {
            "tg_id": actor_id,
            "full_name": actor_full_name,
            "username": actor_username,
            "username_at": f"@{actor_username}" if actor_username else None,
            "is_channel_sender": actor_is_channel_sender,
        },
        "message_text": message_text,
    }

    return payload


def _chunk_text(text: str, max_len: int = 3500) -> list[str]:
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_len, len(text))
        chunks.append(text[start:end])
        start = end
    return chunks


async def notify_superadmins_injection_event(payload: dict[str, Any], bot: Any) -> None:
    """Send injection event payload to all configured superadmins in private chat."""
    if not config.superadmin_ids:
        return

    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    parts = _chunk_text(body, max_len=3500)

    for superadmin_id in config.superadmin_ids:
        try:
            header = "PROMPT INJECTION DETECTED"
            await bot.send_message(chat_id=superadmin_id, text=header)

            for idx, part in enumerate(parts, start=1):
                suffix = f" ({idx}/{len(parts)})" if len(parts) > 1 else ""
                await bot.send_message(
                    chat_id=superadmin_id,
                    text=f"payload{suffix}:\n{part}",
                )
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Failed to notify superadmin %s about injection event: %s",
                superadmin_id,
                exc,
            )
