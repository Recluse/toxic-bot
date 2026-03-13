# toxic-bot

Telegram-бот для групповых чатов с токсичной личностью в духе Уэнсдей Аддамс.
Отвечает холодным сарказмом, логическим давлением и психологической точностью —
на базе Groq LLM через шлюз Cloudflare AI Gateway.

**Автор:** [Recluse](https://github.com/Recluse) — [me@recluse.ru](mailto:me@recluse.ru) — [t.me/recluseru](https://t.me/recluseru)
**Лицензия:** [Unlicense](https://unlicense.org)

---

## Содержание

- [Возможности](#возможности)
- [Архитектура](#архитектура)
- [Требования](#требования)
- [Установка](#установка)
- [Конфигурация](#конфигурация)
- [База данных](#база-данных)
- [Запуск](#запуск)
- [Команды](#команды)
- [Функции суперадмина](#функции-суперадмина)
- [Меню настроек](#меню-настроек)
- [Система личности](#система-личности)
- [Структура проекта](#структура-проекта)

---

## Возможности

- Отвечает в групповых чатах с настраиваемой частотой и уровнем токсичности
- Выявляет логические ошибки и психологическую слабость в сообщениях
- Отвечает острым сарказмом — никогда просто оскорблениями
- Настройки на каждый чат через инлайн-клавиатуру (только для админов)
- История разговоров в PostgreSQL
- Фоновая суммаризация для экономии контекстного окна
- Мультиязычный интерфейс: английский, русский, украинский
- Автоматическая регистрация чатов при первом сообщении
- PM-уведомления суперадмину и система рассылки
- Интеграция с Cloudflare AI Gateway для мониторинга и rate limiting
- Глобальный обработчик ошибок — без тихих падений
- Автоматический retry при flood control от Telegram

---

## Архитектура

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

Запросы к LLM идут через:
```
бот  →  Cloudflare AI Gateway  →  Groq API  →  LLM модель
```

---

## Требования

- Python 3.11+
- PostgreSQL 14+
- Аккаунт Cloudflare с настроенным AI Gateway для Groq
- API-ключ Groq
- Токен Telegram-бота от [@BotFather](https://t.me/BotFather)

---

## Установка

```bash
git clone https://github.com/Recluse/toxic-bot
cd toxic-bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Заполни .env своими данными
```

---

## Конфигурация

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

# ID суперадминов в Telegram (через запятую)
SUPERADMIN_IDS=123456789,987654321

# Выставляется автоматически после setup_commands.py — не редактировать вручную
# COMMANDS_REGISTERED=1
```

### `config.ini`

Все значения опциональны — показаны дефолты:

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

## База данных

Миграции запускаются автоматически при каждом старте через `db/migrations.py`.
Ручной SQL не нужен. Создаваемые таблицы:

| Таблица         | Назначение                                              |
|-----------------|---------------------------------------------------------|
| `chat_settings` | Настройки на каждый чат (токсичность, частота, язык)   |
| `history`       | История сообщений разговора на каждый чат               |
| `chats`         | Трекинг членства (добавлен, активен, кикнут)            |

Чаты регистрируются автоматически при первом входящем сообщении — даже группы,
добавленные до появления lifecycle-трекинга, появятся в `/sa_chats` после
первой активности.

---

## Запуск

### Разработка

```bash
source .venv/bin/activate
python bot.py
```

### systemd (продакшен)

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

### Регистрация команд бота (один раз)

Читает `BOT_TOKEN` и `SUPERADMIN_IDS` из `.env`, регистрирует все команды
на английском, русском и украинском для всех scope, затем пишет
`COMMANDS_REGISTERED=1` в `.env` чтобы не запустить повторно случайно.

```bash
python setup_commands.py

# Перезапустить после добавления суперадминов или изменения описаний:
python setup_commands.py --force
```

---

## Команды

### Публичные (все чаты)

| Команда          | Где         | Описание                                        |
|------------------|-------------|-------------------------------------------------|
| `/start`         | ЛС + группы | Приветствие от бота                             |
| `/help`          | ЛС + группы | Инструкция по использованию                     |
| `/about`         | ЛС + группы | Текущие настройки личности для этого чата       |
| `/reset`         | ЛС + группы | Удалить свою личную историю разговора           |
| `/toxicity_demo` | ЛС + группы | Демо всех пяти уровней токсичности              |

### Для админов (только админы группы)

| Команда     | Где    | Описание                                              |
|-------------|--------|-------------------------------------------------------|
| `/toxic`    | Группы | Реплай на сообщение — заставить бота ответить на него |
| `/settings` | Группы | Открыть инлайн-меню настроек                          |

Обе команды молча удаляются если вызывающий не является админом —
никаких публичных сообщений "только для админов".

---

## Функции суперадмина

Суперадмины определяются по Telegram user ID в `SUPERADMIN_IDS`.
Все команды суперадмина работают только в **личной переписке** с ботом.
Обычные пользователи не видят эти команды в меню и не получают ответа.

### Команды

| Команда          | Описание                                               |
|------------------|--------------------------------------------------------|
| `/sa_chats`      | Список активных чатов с ID и датой добавления          |
| `/sa_stats`      | Статистика: всего / активных / неактивных по типам     |
| `/sa_broadcast`  | Рассылка сообщения во все активные группы (диалог)     |
| `/cancel`        | Прервать рассылку в процессе                           |

### Автоматические уведомления в ЛС

Бот пишет каждому суперадмину когда:

- **Добавлен в чат** — название, chat ID, тип
- **Кикнут из чата** — название, chat ID, тип

### Пример вывода `/sa_chats`

```
Active chats: 3

[supergroup] Dev Team Chat
    id: -1001234567890  joined: 2026-03-10
[group] Friends
    id: -1009876543210  joined: 2026-03-12
[supergroup] Public Channel Test
    id: -1001111111111  joined: 2026-03-13
```

### Пример вывода `/sa_stats`

```
Bot statistics

Active chats:   3
Inactive chats: 1
Total ever:     4

Active by type:
  supergroup: 2
  group: 1
```

### Процесс `/sa_broadcast`

```
Ты:  /sa_broadcast
Бот: Send the message to broadcast to all active group chats.
     Plain text only. /cancel to abort.
Ты:  Всем привет, бот только что обновился!
Бот: Broadcast complete.
     Sent: 3  Failed: 0
```

---

## Меню настроек

Админы группы открывают `/settings` для настройки бота через инлайн-клавиатуру.
Все изменения вступают в силу немедленно без перезапуска.

| Настройка          | Значения            | Описание                                          |
|--------------------|---------------------|---------------------------------------------------|
| Уровень токсичности | 1 – 5              | 1 = лёгкий сарказм, 5 = полная психологическая война |
| Частота ответов    | настраивается       | Как часто бот вступает в разговор                 |
| Кулдаун            | 30 / 60 / 120 / 300 сек | Минимальное время между ответами бота         |
| Глубина цепочки    | 3 / 5 / 7 / 10      | Как глубоко в цепочке реплаев следит бот          |
| Минимум слов       | 3 / 5 / 7 / 10      | Игнорировать сообщения короче этого               |
| Язык               | en / ru / uk        | Язык системных сообщений и меню бота              |

---

## Система личности

Бот ведёт себя как Уэнсдей Аддамс, но более аналитически токсично:

- **Логическое давление** — находит слабые аргументы и разбирает их точно
- **Психологическое прицеливание** — выявляет неуверенность, самонадеянность и противоречия
- **Остроумие вместо оскорблений** — каждый ответ имеет смысл, а не просто шум
- **Контекстуальность** — использует историю разговора для развития взаимодействия
- **Реальные знания** — может и будет цитировать реальные факты для усиления точки зрения

Уровни токсичности:

| Уровень | Поведение                                              |
|---------|--------------------------------------------------------|
| 1       | Сухой юмор, лёгкое снисхождение                       |
| 2       | Заметное нетерпение к твоей логике                     |
| 3       | Активный разбор твоих аргументов (по умолчанию)        |
| 4       | Личное, хирургическое, сложно игнорировать             |
| 5       | Полная Уэнсдей — холодно, точно, слегка пугающе        |

---

## Структура проекта

```
toxic-bot/
├── bot.py                    # Точка входа, регистрация хендлеров, обработчик ошибок
├── config.py                 # Загрузчик конфига (dataclasses + .env + config.ini)
├── config.ini                # Несекретные дефолты
├── .env                      # Секреты (не коммитить)
├── .env.example              # Шаблон
├── setup_commands.py         # Однократная регистрация команд Telegram
├── requirements.txt
├── scripts/
│   └── backfill_chats.py     # Однократная регистрация уже существующих чатов
├── ai/
│   ├── client.py             # Async Groq клиент через Cloudflare AI Gateway
│   ├── responder.py          # get_reply() — основной LLM-вызов с историей
│   ├── prompts.py            # Построитель системного промпта по уровню + языку
│   └── summarizer.py         # Фоновая суммаризация разговора
├── db/
│   ├── pool.py               # asyncpg connection pool
│   ├── migrations.py         # Идемпотентные DDL-миграции, запуск при старте
│   ├── chat_settings.py      # CRUD настроек на каждый чат
│   ├── history.py            # CRUD истории разговора
│   └── chats.py              # CRUD трекинга членства + статистика
├── handlers/
│   ├── commands_public.py    # /start /help /about /reset /toxicity_demo /toxic
│   ├── messages.py           # Основной хендлер сообщений с логикой частоты и кулдауна
│   ├── lifecycle.py          # События добавления/удаления + PM-уведомления суперадмину
│   ├── superadmin.py         # /sa_chats /sa_stats /sa_broadcast
│   └── admin_menu/
│       ├── callbacks.py      # Константы callback data
│       ├── main_menu.py      # Точка входа инлайн-меню настроек
│       ├── simple_choice_menus.py  # Меню кулдауна / глубины цепочки / мин. слов
│       └── router.py         # Единый диспетчер CallbackQueryHandler
├── i18n/
│   └── __init__.py           # get_text(key, lang) — все строки интерфейса
└── utils/
    ├── admin_check.py        # is_chat_admin() с обходом для суперадминов
    ├── rate_limiter.py       # Трекер кулдауна на пользователя
    └── reply_chain.py        # Сборщик контекста цепочки реплаев
```
