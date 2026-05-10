"""
config.py — Central configuration loader.

Loads secrets from .env and non-secret defaults from config.ini.
Exposes a frozen AppConfig dataclass used as a module-level singleton.
"""

import os
import configparser
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class BotConfig:
    max_history_messages: int
    default_lang: str


@dataclass(frozen=True)
class DefaultChatConfig:
    """
    Fallback values applied to a new chat row before an admin
    customises anything via the inline settings menu.
    """
    toxicity_level:     int
    freq_min:           int
    freq_max:           int
    reply_cooldown_sec: int
    explain_cooldown_min: int
    reply_chain_depth:  int
    min_words:          int


@dataclass(frozen=True)
class GroqConfig:
    model:         str
    fallback_model: str
    vision_model:  str
    whisper_model: str
    temperature:   float
    max_tokens:    int
    top_p:         float
    api_key:       str
    base_url:      str


@dataclass(frozen=True)
class SummarizerConfig:
    """Separate model config for async background summary generation."""
    model:       str
    max_tokens:  int
    temperature: float


@dataclass(frozen=True)
class OwnerConfig:
    """
    Identity of the bot's creator/operator. When a message comes from
    owner_user_id (PM or group post) or is sent on behalf of owner_channel_id
    (sender_chat in a group), the bot drops its toxic persona and replies as
    a loyal, helpful assistant. Both fields default to 0 (= disabled).
    """
    user_id:    int
    channel_id: int


@dataclass(frozen=True)
class AppConfig:
    telegram_token: str
    superadmin_ids: frozenset   # frozenset[int]
    owner:          OwnerConfig
    bot:            BotConfig
    defaults:       DefaultChatConfig
    groq:           GroqConfig
    summarizer:     SummarizerConfig


def _require_env(name: str) -> str:
    """
    Read a required env variable.
    Raises EnvironmentError immediately on startup if any are missing.
    """
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Required environment variable is not set: {name}")
    return value


def _cf_groq_url(account_id: str, gateway_id: str) -> str:
    """
    Build the Cloudflare AI Gateway base URL for Groq,
    including the /openai/v1 path suffix required by the OpenAI SDK.
    The SDK appends /chat/completions etc. to this base.
    """
    return (
        f"https://gateway.ai.cloudflare.com/v1/"
        f"{account_id}/{gateway_id}/groq/openai/v1"
    )


def _parse_int_env(name: str) -> int:
    """
    Parse an optional integer env variable (e.g. OWNER_USER_ID,
    OWNER_CHANNEL_ID). Channel IDs in Telegram are negative, so we accept
    a leading '-'. Returns 0 when unset, empty, or unparseable — that
    sentinel disables the corresponding owner check downstream.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _parse_superadmin_ids() -> frozenset:
    """
    Parse SUPERADMIN_IDS env variable.
    Expects comma-separated integer Telegram user IDs.
    Returns empty frozenset if not set — superadmin commands will be silent.
    """
    raw = os.getenv("SUPERADMIN_IDS", "")
    return frozenset(
        int(x.strip())
        for x in raw.split(",")
        if x.strip().isdigit()
    )


def load_config(ini_path: str = "config.ini") -> AppConfig:
    """
    Parse config.ini and environment variables, validate all required fields,
    and return a fully populated immutable AppConfig.
    """
    ini = configparser.ConfigParser()
    ini.read(ini_path)

    telegram_token = _require_env("TELEGRAM_BOT_TOKEN")
    groq_api_key   = _require_env("GROQ_API_KEY")
    cf_account_id  = _require_env("CF_ACCOUNT_ID")
    cf_gateway_id  = _require_env("CF_GATEWAY_ID")
    _require_env("DATABASE_URL")

    superadmin_ids = _parse_superadmin_ids()
    if not superadmin_ids:
        import logging
        logging.getLogger(__name__).warning(
            "SUPERADMIN_IDS is not set — superadmin commands will be unavailable"
        )

    owner = OwnerConfig(
        user_id=_parse_int_env("OWNER_USER_ID"),
        channel_id=_parse_int_env("OWNER_CHANNEL_ID"),
    )

    return AppConfig(
        telegram_token=telegram_token,
        superadmin_ids=superadmin_ids,
        owner=owner,
        bot=BotConfig(
            max_history_messages=ini.getint("bot", "max_history_messages", fallback=20),
            default_lang=ini.get(          "bot", "default_lang",         fallback="en"),
        ),
        defaults=DefaultChatConfig(
            toxicity_level=    ini.getint("defaults", "toxicity_level",     fallback=3),
            freq_min=          ini.getint("defaults", "freq_min",            fallback=5),
            freq_max=          ini.getint("defaults", "freq_max",            fallback=15),
            reply_cooldown_sec=ini.getint("defaults", "reply_cooldown_sec",  fallback=60),
            explain_cooldown_min=ini.getint("defaults", "explain_cooldown_min", fallback=10),
            reply_chain_depth= ini.getint("defaults", "reply_chain_depth",   fallback=5),
            min_words=         ini.getint("defaults", "min_words",           fallback=5),
        ),
        groq=GroqConfig(
            model=        ini.get(      "groq", "model",         fallback="openai/gpt-oss-120b"),
            fallback_model=ini.get(     "groq", "fallback_model", fallback="llama-3.3-70b-versatile"),
            vision_model= ini.get(      "groq", "vision_model",  fallback="meta-llama/llama-4-scout-17b-16e-instruct"),
            whisper_model=ini.get(      "groq", "whisper_model", fallback="whisper-large-v3-turbo"),
            temperature=  ini.getfloat( "groq", "temperature",   fallback=0.85),
            max_tokens=   ini.getint(   "groq", "max_tokens",    fallback=1024),
            top_p=        ini.getfloat( "groq", "top_p",         fallback=0.95),
            api_key=groq_api_key,
            base_url=_cf_groq_url(cf_account_id, cf_gateway_id),
        ),
        summarizer=SummarizerConfig(
            model=      ini.get(     "summarizer", "model",       fallback="llama-3.3-70b-versatile"),
            max_tokens= ini.getint(  "summarizer", "max_tokens",  fallback=512),
            temperature=ini.getfloat("summarizer", "temperature", fallback=0.3),
        ),
    )


config: AppConfig = load_config()
