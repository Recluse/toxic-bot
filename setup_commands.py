"""
setup_commands.py — One-time Telegram bot command registration script.

Reads BOT_TOKEN and SUPERADMIN_IDS from .env, registers commands for all
scopes and languages via the Telegram Bot API, then writes COMMANDS_REGISTERED=1
back to .env to prevent accidental re-runs.

Re-run manually anytime by removing COMMANDS_REGISTERED from .env or
passing --force flag.
"""

import json
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv, set_key, get_key
import os

ENV_PATH = Path(".env")
ENV_FLAG = "COMMANDS_REGISTERED"

load_dotenv(ENV_PATH)


def _check_already_done() -> None:
    """Abort if commands were already registered and --force was not passed."""
    if get_key(ENV_PATH, ENV_FLAG) == "1" and "--force" not in sys.argv:
        print("Commands already registered. Use --force to re-run.")
        sys.exit(0)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Required variable not set in .env: {name}")
    return value


def _parse_superadmin_ids() -> list[int]:
    raw = os.getenv("SUPERADMIN_IDS", "")
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


def _post(base_url: str, body: dict) -> str:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        return "OK" if result.get("result") else f"FAIL: {result}"


# ---------------------------------------------------------------------------
# Command definitions
# ---------------------------------------------------------------------------

_COMMANDS_PUBLIC = {
    "en": [
        {"command": "start",         "description": "Wake me up. I'll try to contain my disappointment"},
        {"command": "help",          "description": "Full manual in DMs, short version in groups"},
        {"command": "about",         "description": "Current personality settings for this chat"},
        {"command": "reset",         "description": "Erase your conversation history with me"},
        {"command": "toxicity_demo", "description": "Watch me dismantle someone five different ways"},
        {"command": "toxic",         "description": "Admins: force a reply to a message — use as a reply"},
        {"command": "settings",      "description": "Admins: open settings menu"},
    ],
    "ru": [
        {"command": "start",         "description": "Разбудить меня. Постараюсь сдержать разочарование"},
        {"command": "help",          "description": "Полное руководство в личке, краткое в группе"},
        {"command": "about",         "description": "Текущие настройки личности для этого чата"},
        {"command": "reset",         "description": "Удалить свою историю разговора со мной"},
        {"command": "toxicity_demo", "description": "Пять уровней презрения на одном примере"},
        {"command": "toxic",         "description": "Админы: натравить бота на сообщение реплаем"},
        {"command": "settings",      "description": "Админы: открыть меню настроек"},
    ],
    "uk": [
        {"command": "start",         "description": "Розбудити мене. Спробую стримати розчарування"},
        {"command": "help",          "description": "Повний посібник в особистих, коротко в групі"},
        {"command": "about",         "description": "Поточні налаштування особистості для цього чату"},
        {"command": "reset",         "description": "Видалити свою історію розмови зі мною"},
        {"command": "toxicity_demo", "description": "П'ять рівнів зневаги на одному прикладі"},
        {"command": "toxic",         "description": "Адміни: натравити бота на повідомлення реплаєм"},
        {"command": "settings",      "description": "Адміни: відкрити меню налаштувань"},
    ],
}

_COMMANDS_SUPERADMIN = {
    "en": [
        {"command": "sa_chats",     "description": "List all active chats the bot is in"},
        {"command": "sa_stats",     "description": "Aggregate statistics"},
        {"command": "sa_broadcast", "description": "Broadcast a message to all group chats"},
    ],
    "ru": [
        {"command": "sa_chats",     "description": "Список активных чатов бота"},
        {"command": "sa_stats",     "description": "Агрегированная статистика"},
        {"command": "sa_broadcast", "description": "Рассылка во все групповые чаты"},
    ],
    "uk": [
        {"command": "sa_chats",     "description": "Список активних чатів бота"},
        {"command": "sa_stats",     "description": "Агрегована статистика"},
        {"command": "sa_broadcast", "description": "Розсилка в усі групові чати"},
    ],
}


def main() -> None:
    _check_already_done()

    bot_token      = _require_env("TELEGRAM_BOT_TOKEN")
    superadmin_ids = _parse_superadmin_ids()
    base_url       = f"https://api.telegram.org/bot{bot_token}/setMyCommands"

    # --- Global scopes ---
    global_setups = [
        ("all_private_chats", None),
        ("all_private_chats", "en"),
        ("all_private_chats", "ru"),
        ("all_private_chats", "uk"),
        ("all_group_chats",   None),
        ("all_group_chats",   "en"),
        ("all_group_chats",   "ru"),
        ("all_group_chats",   "uk"),
    ]

    for scope_type, lang in global_setups:
        cmds = _COMMANDS_PUBLIC.get(lang or "en")
        body = {"commands": cmds, "scope": {"type": scope_type}}
        if lang:
            body["language_code"] = lang
        label = lang or "default"
        status = _post(base_url, body)
        print(f"scope={scope_type:<20} lang={label:<8} {status}")

    # --- Per-superadmin scopes (PM only — full command list including sa_*) ---
    for uid in superadmin_ids:
        for lang in (None, "en", "ru", "uk"):
            key = lang or "en"
            cmds = _COMMANDS_PUBLIC[key] + _COMMANDS_SUPERADMIN[key]
            body = {
                "commands": cmds,
                "scope": {"type": "chat", "chat_id": uid},
            }
            if lang:
                body["language_code"] = lang
            label = lang or "default"
            status = _post(base_url, body)
            print(f"scope=chat uid={uid:<12} lang={label:<8} {status}")

    # Mark as done in .env
    set_key(ENV_PATH, ENV_FLAG, "1")
    print(f"\nAll done. {ENV_FLAG}=1 written to {ENV_PATH}")
    print("To re-run: python setup_commands.py --force")


if __name__ == "__main__":
    main()
