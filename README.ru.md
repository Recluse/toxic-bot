# toxic-bot

Telegram-бот для групповых чатов с токсичной личностью в духе Уэнсдей Аддамс.
Отвечает холодным сарказмом, логическим давлением и психологической точностью —
на базе Groq LLM через Cloudflare AI Gateway.

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
- [Переводы](#переводы)

---

## Возможности

- Отвечает в групповых чатах с настраиваемой частотой и уровнем токсичности
- Выявляет логические ошибки и психологические слабости в сообщениях
- Отвечает острым, остроумным сарказмом — никогда не просто оскорблениями
- Настройки на чат через инлайн-клавиатуру (только для администраторов)
- История разговоров в PostgreSQL
- Фоновое суммирование для экономии контекстного окна
- Мультиязычный интерфейс: английский, русский, украинский
- Адаптивный язык ответа: если сообщение явно целиком на другом одном языке, бот отвечает на этом языке
- Префильтр prompt injection до любого вызова LLM (`<system>`, `</system>`, `<\\system>` и проверки `ai-injection-guard`)
- Санитизация контекста перед вызовом LLM: история и reply-chain фильтруются на инъекции, опасные фрагменты вырезаются
- Защита по тегам также покрывает варианты с `admin` (`<admin>`, `</admin>`, `<\\admin>`) включая regex и escaped-формы
- Отдельный лог инъекций: `logs/prompt_injection_events.log` с полным payload чата/пользователя/сообщения
- PM-уведомления суперадмину при каждом срабатывании инъекционного фильтра с источником и подробной причиной
- Инъекционные сообщения в случайном групповом потоке тихо игнорируются; явная реакция остаётся в ЛС, командах и прямых реплаях боту
- Автоматическая регистрация чатов при первом сообщении
- PM-уведомления и система broadcast для суперадмина
- Интеграция с Cloudflare AI Gateway для наблюдаемости и rate limiting
- Глобальный обработчик ошибок — никаких тихих сбоев
- Обработка flood control — автоматические повторы при rate limits Telegram
- Мультимодальность: `/explain` работает с текстом, фото и голосовыми
- Личное `/settings` в ЛС: токсичность, досье, глобальная неприкасаемость, self-reset
- Почасовые лимиты в ЛС: текст (10/ч), медиа (5/ч), `/explain` (5/ч)
- Fallback-модель Groq при over-capacity (503)
- Расширенная аналитика суперадмина: аптайм, счётчики активности, размеры БД

---

## Архитектура

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

LLM-запросы проходят через:
```
bot  →  Cloudflare AI Gateway  →  Groq API  →  LLM model
```

---

## Требования

- Python 3.12
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
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp .env.example .env
# Заполните .env своими данными
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

# Telegram user ID суперадминов (через запятую)
SUPERADMIN_IDS=123456789,987654321

# Заполняется автоматически после setup_commands.py — не редактировать вручную
# COMMANDS_REGISTERED=1
```

### `config.ini`

Все значения опциональны — показаны с дефолтами:

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
model = moonshotai/kimi-k2-instruct-0905  # или llama3-groq-70b-8192-tool-use-preview
fallback_model = llama-3.3-70b-versatile  # автоматический fallback при 503/over-capacity
vision_model  = meta-llama/llama-4-scout-17b-16e-instruct
whisper_model = whisper-large-v3-turbo
temperature = 0.85
max_tokens = 1024
top_p = 0.95

[summarizer]
model = llama-3.3-70b-versatile
max_tokens = 512
temperature = 0.3
```

---

## База данных

Миграции запускаются автоматически при каждом старте через `db/migrations.py`.
Ручной SQL не нужен. Создаются таблицы:

| Таблица          | Назначение                                                  |
|------------------|-------------------------------------------------------------|
| `chat_settings`  | Настройки на чат (токсичность, частота, язык)               |
| `message_history`| История сообщений на чат                                    |
| `chats`          | Отслеживание членства (вступил, активен, кикнут)            |
| `user_profiles` / `user_summaries` | Психологические/поведенческие профили пользователей |
| `untouchable_users` | Перечень игнора по чату                                  |
| `global_untouchables` | Глобальная неприкасаемость пользователей               |
| `bot_metrics`    | Персистентные счётчики для статистики суперадмина           |

Чаты регистрируются автоматически при первом входящем сообщении.

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

```bash
python setup_commands.py

# Перезапустить после добавления суперадминов или изменения описаний:
python setup_commands.py --force
```

---

## Команды

### Публичные (все чаты)

| Команда            | Где         | Описание                                           |
|--------------------|-------------|----------------------------------------------------|
| `/start`           | ЛС + группы | Приветствие от бота                                |
| `/help`            | ЛС + группы | Инструкция по использованию                        |
| `/about`           | ЛС + группы | Текущие настройки личности для этого чата          |
| `/reset`           | ЛС + группы | Очистить свою историю разговора                    |
| `/dont_touch_me`   | Группы      | Добавить себя в неприкасаемые                      |
| `/settings`        | ЛС          | Открыть личное меню настроек                        |

### Для администраторов (только в группах)

| Команда     | Где    | Описание                                              |
|-------------|--------|-------------------------------------------------------|
| `/toxic`    | Группы | Ответить на сообщение — бот отреагирует принудительно |
| `/settings` | Группы | Открыть инлайн-меню настроек                          |

Команды администратора тихо удаляются, если вызывающий не является администратором.

### Explain (ответ на сообщение)

| Команда    | Где         | Описание                                            |
|------------|-------------|-----------------------------------------------------|
| `/explain` | ЛС + группы | Научный/фактологический анализ текста/фото/голоса   |

---

## Функции суперадмина

Суперадмины задаются через `SUPERADMIN_IDS` в `.env`. Команды работают **только в личке** с ботом.

### Команды

| Команда          | Описание                                                  |
|------------------|-----------------------------------------------------------|
| `/sa_chats`      | Список активных чатов с ID и датами вступления            |
| `/sa_stats`      | Дашборд: runtime, чаты/пользователи, обработанный контент, размеры БД |
| `/sa_broadcast`  | Отправить сообщение во все активные группы (диалог)       |
| `/cancel`        | Прервать текущий broadcast                                |

`/sa_chats` пытается подтянуть live-данные из Telegram по `chat_id` (имя/название и `@username`) с fallback на БД.

### Автоматические PM-уведомления

- **Добавлен в чат** — название, chat ID, тип
- **Кикнут из чата** — название, chat ID, тип

---

## Меню настроек

Администраторы группы: `/settings` → инлайн-клавиатура. Изменения применяются сразу.

| Настройка          | Диапазон / варианты | Описание                                          |
|--------------------|---------------------|---------------------------------------------------|
| Уровень токсичности| 1–5                 | 1=мягко, 5=ядерно                                 |
| Частота ответов    | min–max (случайно)  | Как часто бот вступает в разговор                 |
| Кулдаун пользователя | 30/60/120/300 сек | Минимальный интервал между ответами одному юзеру  |
| Кулдаун `/explain` | 10–600 мин (шаг 10) | Интервал между `/explain` от одного юзера в чате  |
| Глубина цепочки    | 3/5/7/10            | Сколько сообщений назад читает в reply chain      |
| Минимум слов       | 3/5/7/10            | Игнорировать сообщения короче этого               |
| Управление юзерами | Просмотр/сброс      | Просмотр и удаление профилей пользователей        |
| Неприкасаемые      | Список/удаление     | Удаление пользователей из списка игнора бота      |

В личке команда `/settings` открывает персональное меню:
- уровень токсичности в ЛС
- глобальная неприкасаемость
- предпросмотр досье
- удаление своих данных из БД

---

## Система личности

Уэнсдей Аддамс × аналитическая токсичность:

- **Логическое препарирование** — называет ошибки, цитирует факты
- **Психологическое давление** — бьёт по конкретным слабостям
- **Остроумие прежде всего** — точно, никогда не банально
- **Контекстуальность** — использует историю и профили пользователей

| Уровень | Название                | Стиль                                  |
|---------|-------------------------|----------------------------------------|
| 1       | Холодное разочарование  | Сухое, отстранённое наблюдение         |
| 2       | Логическое вскрытие     | Судебный разбор аргументов             |
| 3       | Психологическое давление| Хирургическое зондирование (по умолч.) |
| 4       | Вооружённое остроумие   | Комплимент → поворот → укол            |
| 5       | Ядерная Уэнсдей         | Полный вердикт с доказательствами      |

---

## Структура проекта

```
toxic-bot/
├── .env*                 # Секреты (не коммитится)
├── .env.example          # Шаблон
├── .gitignore
├── README.{md,ru.md,uk.md}
├── config.ini            # Несекретные дефолты
├── config.py             # Загрузчик конфига (dataclasses)
├── bot.py                # Точка входа, хендлеры, миграции
├── setup_commands.py     # Регистрация команд Telegram
├── requirements.txt
├── ai/
│   ├── client.py             # AsyncOpenAI → CF Gateway → Groq
│   ├── prompts.py            # 5 уровней × 3 языка + injection guard
│   ├── responder.py          # Основной пайплайн get_reply()
│   ├── summarizer.py         # Фоновые профили пользователей
│   ├── transcriber.py        # Голос → текст (Whisper)
│   └── vision.py             # Фото → base64 мультимодальность
├── db/
│   ├── pool.py               # asyncpg пул соединений
│   ├── migrations.py         # Идемпотентные DDL-миграции
│   ├── chat_settings.py      # CRUD настроек чата
│   ├── history.py            # CRUD истории сообщений
│   ├── chats.py              # CRUD трекинга чатов
│   ├── metrics.py            # Персистентные счётчики аналитики
│   ├── user_profiles.py      # CRUD психологических профилей
│   └── untouchables.py       # CRUD неприкасаемых пользователей
├── handlers/
│   ├── commands_public.py    # /start /help /about /reset /dont_touch_me /toxic
│   ├── commands_explain.py   # /explain (мультимодальный)
│   ├── messages.py           # Основной хендлер + freq/cooldown логика
│   ├── lifecycle.py          # Вступление/выход + PM суперадмина
│   ├── pm_settings.py        # Личное меню /settings
│   ├── superadmin.py         # /sa_* команды
│   ├── language_select.py    # Выбор языка
│   └── admin_menu/
│       ├── callbacks.py          # Константы callback data
│       ├── main_menu.py          # Вход в меню настроек
│       ├── frequency_menu.py     # Меню частоты min/max
│       ├── toxicity_menu.py      # Меню уровней токсичности
│       ├── simple_choice_menus.py# Cooldown/chain/minwords
│       ├── user_management_menu.py# UI управления профилями
│       ├── untouchables_menu.py  # UI неприкасаемых
│       └── router.py             # Диспетчер callback
├── i18n/
│   ├── __init__.py         # gettext(key, lang, **kwargs)
│   ├── en.json
│   ├── ru.json
│   └── ua.json
└── utils/
    ├── admin_check.py     # is_chat_admin() + суперадмин bypass
    ├── rate_limiter.py    # Кулдаун на юзера
    ├── reply_chain.py     # Сборщик reply chain
    └── tg_safe.py         # Безопасные send/edit обёртки (RetryAfter и др.)
```

*Не коммитится

---

## Переводы

- [README in English](README.md)
- [README українською](README.uk.md)
