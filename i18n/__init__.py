"""
i18n/__init__.py — Internationalisation helper.

Loads all JSON locale files once at import time.
get_text(key, lang, **kwargs) is the single public API used everywhere in the bot.

Supported language codes: 'en', 'ru', 'ua'
Fallback chain: requested lang -> 'en' -> raw key (so nothing crashes if a key is missing).
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Absolute path to the directory this file lives in
_I18N_DIR = Path(__file__).parent

# Supported language codes — must match JSON filenames
SUPPORTED_LANGS: tuple[str, ...] = ("en", "ru", "ua")

# Master dict: { 'en': { 'key': 'value', ... }, 'ru': {...}, 'ua': {...} }
_strings: dict[str, dict[str, str]] = {}


def _load_all() -> None:
    """
    Read every supported locale file into _strings.
    Called once at module import. Missing files raise immediately so
    the operator notices before the bot processes a single message.
    """
    for code in SUPPORTED_LANGS:
        path = _I18N_DIR / f"{code}.json"
        with path.open(encoding="utf-8") as fh:
            _strings[code] = json.load(fh)
        logger.debug("Loaded locale file: %s (%d keys)", path.name, len(_strings[code]))


_load_all()


def get_text(key: str, lang: str = "en", **kwargs) -> str:
    """
    Return localised string for key in the given language.

    Fallback chain:
      1. Exact lang match
      2. English
      3. Raw key (so callers never crash on a missing translation)

    kwargs are passed to str.format_map() for template substitution.
    Example: get_text('toxicity_saved', 'ru', level=3)
    """
    lang = lang if lang in SUPPORTED_LANGS else "en"

    # Try requested language, then English, then return key as last resort
    text = (
        _strings.get(lang, {}).get(key)
        or _strings.get("en", {}).get(key)
        or key
    )

    if kwargs:
        try:
            text = text.format_map(kwargs)
        except (KeyError, ValueError) as exc:
            logger.warning("i18n format error key=%r lang=%r: %s", key, lang, exc)

    return text
