# toxic-bot

A Telegram group bot with a toxic personality inspired by Wednesday Addams.
Responds to messages with cold sarcasm, logical pressure, and psychological
precision — powered by Groq LLM via a Cloudflare AI Gateway.

**Author:** [Recluse](https://github.com/Recluse) — [me@recluse.ru](mailto:me@recluse.ru) — [t.me/recluseru](https://t.me/recluseru)
**License:** [Unlicense](https://unlicense.org)

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Database](#database)
- [Running](#running)
- [Command Reference](#command-reference)
- [Superadmin Features](#superadmin-features)
- [Admin Settings Menu](#admin-settings-menu)
- [Personality System](#personality-system)
- [Project Structure](#project-structure)
- [Translations](#translations)

---

## Features

- Responds in group chats with configurable frequency and toxicity level
- Detects logical fallacies and psychological weakness in messages
- Replies with sharp, wit-first sarcasm — never dumb insults
- Per-chat settings managed via inline keyboard (admins only)
- Conversation history with PostgreSQL-backed memory
- Background summarisation to keep context window lean
- Multilingual interface: English, Russian, Ukrainian
- Auto-registers chats on first message — no manual setup needed
- Superadmin PM notifications and broadcast system
- Cloudflare AI Gateway integration for observability and rate limiting
- Global error handler — no silent crashes
- Flood control handling — retries automatically on Telegram rate limits
- Multimodal support: `/explain` works on text, photos, voice messages

---

## Architecture

```
Telegram  ←→  python-telegram-bot  ←→  handlers/
                                       ├── commands_public.py
                                       ├── commands_explain.py
                                       ├── messages.py
                                       ├── lifecycle.py
                                       ├── superadmin.py
                                       ├── language_select.py
                                       └── admin_menu/
                                           ├── callbacks.py
                                           ├── main_menu.py
                                           ├── frequency_menu.py
                                           ├── toxicity_menu.py
                                           ├── simple_choice_menus.py
                                           ├── user_management_menu.py
                                           └── router.py
                               ←→  ai/
                                       ├── client.py
                                       ├── prompts.py
                                       ├── responder.py
                                       ├── summarizer.py
                                       ├── transcriber.py
                                       └── vision.py
                               ←→  db/
                                       ├── pool.py
                                       ├── migrations.py
                                       ├── chat_settings.py
                                       ├── history.py
                                       ├── chats.py
                                       └── user_profiles.py
```

LLM requests go through:
```
bot  →  Cloudflare AI Gateway  →  Groq API  →  LLM model
```

---

## Requirements

- Python 3.12
- PostgreSQL 14+
- Cloudflare account with AI Gateway configured for Groq
- Groq API key
- Telegram bot token from [@BotFather](https://t.me/BotFather)

---

## Installation

```bash
git clone https://github.com/Recluse/toxic-bot
cd toxic-bot
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
```

---

## Configuration

### `.env`

```dotenv
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Groq
GROQ_API_KEY=your_groq_api_key_here

# Cloudflare AI Gateway
CF_ACCOUNT_ID=your_cloudflare_account_id
CF_GATEWAY_ID=your_gateway_id

# PostgreSQL
DATABASE_URL=postgresql://user:password@localhost:5432/toxicbot

# Superadmin Telegram user IDs (comma-separated)
SUPERADMIN_IDS=123456789,987654321

# Set automatically by setup_commands.py after first run — do not edit manually
# COMMANDS_REGISTERED=1
```

### `config.ini`

All values are optional — shown with defaults:

```ini
[bot]
max_history_messages = 20
default_lang = en

[defaults]
toxicity_level = 3
freq_min = 5
freq_max = 15
reply_cooldown_sec = 60
reply_chain_depth = 5
min_words = 5

[groq]
model = moonshotai/kimi-k2-instruct-0905  # or llama3-groq-70b-8192-tool-use-preview
temperature = 0.85
max_tokens = 1024
top_p = 0.95

[summarizer]
model = llama-3.3-70b-versatile
max_tokens = 512
temperature = 0.3
```

---

## Database

Migrations run automatically on every startup via `db/migrations.py`.
No manual SQL required. Tables created:

| Table            | Purpose                                                |
|------------------|--------------------------------------------------------|
| `chat_settings`  | Per-chat configuration (toxicity, frequency, lang)     |
| `message_history`| Conversation message history per chat                  |
| `chats`          | Membership tracking (joined, active, kicked)           |
| `user_profiles`  | Per-user psychological/behavioral summaries            |

Chats are auto-registered on the first incoming message.

---

## Running

### Development

```bash
source .venv/bin/activate
python bot.py
```

### systemd (production)

```ini
[Unit]
Description=Toxic Wednesday Telegram Bot
After=network.target postgresql.service

[Service]
User=youruser
WorkingDirectory=/home/youruser/toxic-bot
EnvironmentFile=/home/youruser/toxic-bot/.env
ExecStart=/home/youruser/toxic-bot/.venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable toxic-bot
sudo systemctl start toxic-bot
journalctl -u toxic-bot -f
```

### Register bot commands (one-time)

```bash
python setup_commands.py

# Re-run after adding superadmin IDs or changing descriptions:
python setup_commands.py --force
```

---

## Command Reference

### Public (all chats)

| Command            | Where       | Description                                      |
|--------------------|-------------|--------------------------------------------------|
| `/start`           | PM + groups | Greeting from the bot                            |
| `/help`            | PM + groups | Usage instructions                               |
| `/about`           | PM + groups | Current personality settings for this chat       |
| `/reset`           | PM + groups | Clear your personal conversation history         |
| `/toxicity_demo`   | PM + groups | Demo all toxicity levels                         |

### Admin (group admins only)

| Command     | Where  | Description                                 |
|-------------|--------|---------------------------------------------|
| `/toxic`    | Groups | Reply to a message to force the bot to respond |
| `/settings` | Groups | Open the inline settings menu                |

Admin commands are silently deleted if caller is not admin.

### Explain (reply to message)

| Command  | Where       | Description                                      |
|----------|-------------|--------------------------------------------------|
| `/explain` | PM + groups | Scientific/factual analysis of text/photo/voice  |

---

## Superadmin Features

Superadmins (`SUPERADMIN_IDS` in `.env`). Commands work **only in private chat** with bot.

### Commands

| Command          | Description                                      |
|------------------|--------------------------------------------------|
| `/sa_chats`      | List all active chats with IDs and join dates    |
| `/sa_stats`      | Total/active/inactive chat counts by type        |
| `/sa_broadcast`  | Send message to all active groups (conversation) |
| `/cancel`        | Abort in-progress broadcast                      |

### Automatic PM notifications

- **Added to chat** — title, chat ID, type
- **Kicked from chat** — title, chat ID, type

---

## Admin Settings Menu

Group admins: `/settings` → inline keyboard. Changes apply immediately.

| Setting            | Range / Options     | Description                                      |
|--------------------|---------------------|--------------------------------------------------|
| Toxicity level     | 1–5                 | 1=mild, 5=nuclear                                |
| Reply frequency    | min–max (random)    | How often bot responds                           |
| User cooldown      | 30/60/120/300 sec   | Time between replies to same user                |
| Reply chain depth  | 3/5/7/10            | Messages back in reply chain                     |
| Minimum words      | 3/5/7/10            | Ignore shorter messages                          |
| User management    | List/reset profiles | View/delete user summaries                       |

---

## Personality System

Wednesday Addams × analytical toxicity:

- **Logical dissection** — names fallacies, cites facts
- **Psychological pressure** — targets specific weaknesses
- **Wit-first** — precise, never generic insults
- **Context-aware** — uses history + user profiles

| Level | Name                     | Style                              |
|-------|--------------------------|------------------------------------|
| 1     | Cold Disappointment      | Dry, distant observation           |
| 2     | Logical Dissection       | Forensic reasoning takedown        |
| 3     | Psychological Pressure   | Surgical insecurity probing (def)  |
| 4     | Weaponised Wit           | Compliment → twist → dagger        |
| 5     | Nuclear Wednesday        | Full verdict, documented           |

---

## Project Structure

```
toxic-bot/
├── .env*                 # Secrets (not committed)
├── .env.example          # Template
├── .gitignore
├── README.{md,ru.md,uk.md}
├── config.ini            # Non-secret defaults
├── config.py             # Config loader dataclasses
├── bot.py                # Entrypoint, handlers, migrations
├── setup_commands.py     # Telegram command registration
├── requirements.txt
├── ai/
│   ├── client.py             # AsyncOpenAI → CF Gateway → Groq
│   ├── prompts.py            # 5 levels × 3 langs + injection guard
│   ├── responder.py          # Main get_reply() pipeline
│   ├── summarizer.py         # Background user profile summaries
│   ├── transcriber.py        # Voice → text (Whisper)
│   └── vision.py             # Photo → base64 multimodal
├── db/
│   ├── pool.py               # asyncpg pool
│   ├── migrations.py         # Idempotent DDL
│   ├── chat_settings.py      # Per-chat CRUD
│   ├── history.py            # Message history CRUD
│   ├── chats.py              # Chat tracking CRUD
│   └── user_profiles.py      # User psych profiles CRUD
├── handlers/
│   ├── commands_public.py    # /start /help /about /reset /toxicity_demo /toxic
│   ├── commands_explain.py   # /explain (multimodal)
│   ├── messages.py           # Main handler + freq/cooldown logic
│   ├── lifecycle.py          # Join/leave + superadmin PMs
│   ├── superadmin.py         # /sa_* commands
│   ├── language_select.py    # Language picker
│   └── admin_menu/
│       ├── callbacks.py          # Callback constants
│       ├── main_menu.py          # Settings entry
│       ├── frequency_menu.py     # Freq min/max
│       ├── toxicity_menu.py      # Toxicity levels
│       ├── simple_choice_menus.py# Cooldown/chain/minwords
│       ├── user_management_menu.py# User profiles UI
│       └── router.py             # Callback dispatcher
├── i18n/
│   ├── __init__.py         # gettext(key, lang, **kwargs)
│   ├── en.json
│   ├── ru.json
│   └── ua.json
└── utils/
    ├── admin_check.py     # is_chat_admin() + superadmin
    ├── rate_limiter.py    # Per-user cooldowns
    ├── reply_chain.py     # Reply chain collector
    └── tg_safe.py         # Safe send/edit wrappers (RetryAfter, etc.)
```

*Not committed

---

## Translations

- [README на русском](README.ru.md)
- [README українською](README.uk.md)
