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

---

## Architecture

```
Telegram  ←→  python-telegram-bot  ←→  handlers/
                                         ├── commands_public.py
                                         ├── messages.py
                                         ├── lifecycle.py
                                         ├── superadmin.py
                                         └── admin_menu/
                                               ├── main_menu.py
                                               ├── simple_choice_menus.py
                                               └── router.py
                                    ←→  ai/
                                         ├── client.py
                                         ├── responder.py
                                         ├── prompts.py
                                         └── summarizer.py
                                    ←→  db/
                                         ├── pool.py
                                         ├── migrations.py
                                         ├── chat_settings.py
                                         ├── history.py
                                         └── chats.py
```

LLM requests go through:
```
bot  →  Cloudflare AI Gateway  →  Groq API  →  LLM model
```

---

## Requirements

- Python 3.11+
- PostgreSQL 14+
- A Cloudflare account with AI Gateway configured for Groq
- A Groq API key
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

---

## Installation

```bash
git clone https://github.com/Recluse/toxic-bot
cd toxic-bot
python -m venv .venv
source .venv/bin/activate
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
default_lang         = en

[defaults]
toxicity_level     = 3
freq_min           = 5
freq_max           = 15
reply_cooldown_sec = 60
reply_chain_depth  = 5
min_words          = 5

[groq]
model       = moonshotai/kimi-k2-instruct-0905
temperature = 0.85
max_tokens  = 1024
top_p       = 0.95

[summarizer]
model       = llama-3.3-70b-versatile
max_tokens  = 512
temperature = 0.3
```

---

## Database

Migrations run automatically on every startup via `db/migrations.py`.
No manual SQL required. Tables created:

| Table           | Purpose                                            |
|-----------------|----------------------------------------------------|
| `chat_settings` | Per-chat configuration (toxicity, frequency, lang) |
| `history`       | Conversation message history per chat              |
| `chats`         | Membership tracking (joined, active, kicked)       |

Chats are auto-registered on the first incoming message, so even groups
added before lifecycle tracking was enabled will appear in `/sa_chats`
after the first activity.

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

Reads `BOT_TOKEN` and `SUPERADMIN_IDS` from `.env`, registers all commands
for English, Russian, and Ukrainian across all scopes, then writes
`COMMANDS_REGISTERED=1` to `.env` to prevent accidental re-runs.

```bash
python setup_commands.py

# Re-run after adding superadmin IDs or changing descriptions:
python setup_commands.py --force
```

---

## Command Reference

### Public (all chats)

| Command          | Where       | Description                                |
|------------------|-------------|--------------------------------------------|
| `/start`         | PM + groups | Greeting from the bot                      |
| `/help`          | PM + groups | Usage instructions                         |
| `/about`         | PM + groups | Current personality settings for this chat |
| `/reset`         | PM + groups | Clear your personal conversation history   |
| `/toxicity_demo` | PM + groups | Demo all toxicity levels                   |

### Admin (group admins only)

| Command      | Where  | Description                                    |
|--------------|--------|------------------------------------------------|
| `/toxic`     | Groups | Reply to a message to force the bot to respond |
| `/settings`  | Groups | Open the inline settings menu                  |

Both commands are silently deleted if the caller is not an admin —
no public "admin only" message to avoid noise and trolling.

---

## Superadmin Features

Superadmins are defined by Telegram user ID in `SUPERADMIN_IDS`.
All superadmin commands work only in **private chat** with the bot.
Non-superadmins calling these commands get no response — the commands
are invisible to them in the menu.

### Commands

| Command          | Description                                        |
|------------------|----------------------------------------------------|
| `/sa_chats`      | List all active chats with IDs and join dates      |
| `/sa_stats`      | Total/active/inactive chat counts by type          |
| `/sa_broadcast`  | Send a message to all active groups (conversation) |
| `/cancel`        | Abort an in-progress broadcast                     |

### Automatic PM notifications

The bot sends a message to every superadmin when:

- **Added to a chat** — title, chat ID, type
- **Kicked from a chat** — title, chat ID, type

### `/sa_chats` example output

```
Active chats: 3

[supergroup] Dev Team Chat
    id: -1001234567890  joined: 2026-03-10
[group] Friends
    id: -1009876543210  joined: 2026-03-12
[supergroup] Public Channel Test
    id: -1001111111111  joined: 2026-03-13
```

### `/sa_stats` example output

```
Bot statistics

Active chats:   3
Inactive chats: 1
Total ever:     4

Active by type:
  supergroup: 2
  group: 1
```

### `/sa_broadcast` flow

```
You:  /sa_broadcast
Bot:  Send the message to broadcast to all active group chats.
      Plain text only. /cancel to abort.
You:  Hey everyone, bot was just updated!
Bot:  Broadcast complete.
      Sent: 3  Failed: 0
```

---

## Admin Settings Menu

Group admins open `/settings` to configure the bot per chat via inline keyboard.
All changes take effect immediately without a restart.

| Setting           | Range / Options | Description                                      |
|-------------------|-----------------|--------------------------------------------------|
| Toxicity level    | 1 – 5           | 1 = mild sarcasm, 5 = full psychological warfare |
| Reply frequency   | configurable    | How often the bot joins the conversation         |
| Cooldown          | 30 / 60 / 120 / 300 sec | Minimum time between bot replies         |
| Reply chain depth | 3 / 5 / 7 / 10  | How deep into a reply chain the bot will follow  |
| Min words         | 3 / 5 / 7 / 10  | Ignore messages shorter than this                |
| Language          | en / ru / uk    | Language for bot system messages and menu        |

---

## Personality System

The bot behaves like Wednesday Addams but more analytically toxic:

- **Logical pressure** — identifies weak reasoning and dismantles it precisely
- **Psychological targeting** — detects insecurity, overconfidence, and contradictions
- **Wit over insults** — every response has a point, not just noise
- **Context awareness** — uses conversation history to build on prior interactions
- **Real knowledge** — can and will cite actual facts to reinforce a point

Toxicity levels:

| Level | Behaviour                                           |
|-------|-----------------------------------------------------|
| 1     | Dry wit, mild condescension                         |
| 2     | Visible impatience with your reasoning              |
| 3     | Active deconstruction of your logic (default)       |
| 4     | Personal, surgical, hard to ignore                  |
| 5     | Full Wednesday — cold, precise, slightly terrifying |

---

## Project Structure

```
toxic-bot/
├── bot.py                    # Entry point, handler registration, error handler
├── config.py                 # Config loader (dataclasses + .env + config.ini)
├── config.ini                # Non-secret defaults
├── .env                      # Secrets (not committed)
├── .env.example              # Template
├── setup_commands.py         # One-time Telegram command registration script
├── requirements.txt
├── scripts/
│   └── backfill_chats.py     # One-time script to register pre-existing chats
├── ai/
│   ├── client.py             # Async Groq client via Cloudflare AI Gateway
│   ├── responder.py          # get_reply() — main LLM call with history
│   ├── prompts.py            # System prompt builder per toxicity level + lang
│   └── summarizer.py         # Background conversation summariser
├── db/
│   ├── pool.py               # asyncpg connection pool
│   ├── migrations.py         # Idempotent DDL migrations, run on every startup
│   ├── chat_settings.py      # Per-chat settings CRUD
│   ├── history.py            # Conversation history CRUD
│   └── chats.py              # Chat membership tracking CRUD + stats
├── handlers/
│   ├── commands_public.py    # /start /help /about /reset /toxicity_demo /toxic
│   ├── messages.py           # Main message handler with frequency + cooldown logic
│   ├── lifecycle.py          # Bot add/remove events + superadmin PM notifications
│   ├── superadmin.py         # /sa_chats /sa_stats /sa_broadcast
│   └── admin_menu/
│       ├── callbacks.py      # Callback data constants
│       ├── main_menu.py      # Inline settings menu entry point
│       ├── simple_choice_menus.py  # Cooldown / chain depth / min_words menus
│       └── router.py         # Single CallbackQueryHandler dispatcher
├── i18n/
│   └── __init__.py           # get_text(key, lang) — all UI strings
└── utils/
    ├── admin_check.py        # is_chat_admin() with superadmin bypass
    ├── rate_limiter.py       # Per-user cooldown tracker
    └── reply_chain.py        # Reply chain context collector
```

---

## Translations

- [README на русском](README.ru.md)
- [README українською](README.uk.md)
