# toxic-bot

Telegram-бот для групових чатів з токсичною особистістю у стилі Венесди Аддамс.
Відповідає холодним сарказмом, логічним тиском і психологічною точністю —
на базі Groq LLM через Cloudflare AI Gateway.

**Автор:** [Recluse](https://github.com/Recluse) — [me@recluse.ru](mailto:me@recluse.ru) — [t.me/recluseru](https://t.me/recluseru)
**Ліцензія:** [Unlicense](https://unlicense.org)

---

## Зміст

- [Можливості](#можливості)
- [Архітектура](#архітектура)
- [Вимоги](#вимоги)
- [Встановлення](#встановлення)
- [Конфігурація](#конфігурація)
- [База даних](#база-даних)
- [Запуск](#запуск)
- [Команди](#команди)
- [Функції суперадміна](#функції-суперадміна)
- [Меню налаштувань](#меню-налаштувань)
- [Система особистості](#система-особистості)
- [Структура проекту](#структура-проекту)
- [Переклади](#переклади)

---

## Можливості

- Відповідає в групових чатах з налаштовуваною частотою та рівнем токсичності
- Виявляє логічні помилки та психологічні слабкості в повідомленнях
- Відповідає гострим, дотепним сарказмом — ніколи не просто образами
- Налаштування на чат через інлайн-клавіатуру (тільки для адміністраторів)
- Історія розмов у PostgreSQL
- Фонове підсумовування для економії контекстного вікна
- Багатомовний інтерфейс: англійська, російська, українська
- Автоматична реєстрація чатів при першому повідомленні
- PM-сповіщення та система broadcast для суперадміна
- Інтеграція з Cloudflare AI Gateway для спостережності та rate limiting
- Глобальний обробник помилок — жодних тихих збоїв
- Обробка flood control — автоматичні повтори при rate limits Telegram
- Мультимодальність: `/explain` працює з текстом, фото та голосовими
- Особисте `/settings` у ЛС: токсичність, досьє, глобальна недоторканність, self-reset
- Погодинні ліміти у ЛС: текст (10/год), медіа (5/год), `/explain` (5/год)
- Fallback-модель Groq при over-capacity (503)
- Розширена аналітика суперадміна: аптайм, лічильники активності, розміри БД

---

## Архітектура

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

LLM-запити проходять через:
```
bot  →  Cloudflare AI Gateway  →  Groq API  →  LLM model
```

---

## Вимоги

- Python 3.12
- PostgreSQL 14+
- Акаунт Cloudflare з налаштованим AI Gateway для Groq
- API-ключ Groq
- Токен Telegram-бота від [@BotFather](https://t.me/BotFather)

---

## Встановлення

```bash
git clone https://github.com/Recluse/toxic-bot
cd toxic-bot
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp .env.example .env
# Заповніть .env своїми даними
```

---

## Конфігурація

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

# Telegram user ID суперадмінів (через кому)
SUPERADMIN_IDS=123456789,987654321

# Заповнюється автоматично після setup_commands.py — не редагувати вручну
# COMMANDS_REGISTERED=1
```

### `config.ini`

Усі значення опціональні — показані з дефолтами:

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
model = moonshotai/kimi-k2-instruct-0905  # або llama3-groq-70b-8192-tool-use-preview
fallback_model = llama-3.3-70b-versatile  # автоматичний fallback при 503/over-capacity
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

## База даних

Міграції запускаються автоматично при кожному старті через `db/migrations.py`.
Ручний SQL не потрібен. Створюються таблиці:

| Таблиця          | Призначення                                                   |
|------------------|---------------------------------------------------------------|
| `chat_settings`  | Налаштування на чат (токсичність, частота, мова)              |
| `message_history`| Історія повідомлень на чат                                    |
| `chats`          | Відстеження членства (вступив, активний, кікнутий)            |
| `user_profiles` / `user_summaries` | Психологічні/поведінкові профілі користувачів |
| `untouchable_users` | Список ігнору в межах чату                               |
| `global_untouchables` | Глобальна недоторканність користувачів                 |
| `bot_metrics`    | Персистентні лічильники для статистики суперадміна            |

Чати реєструються автоматично при першому вхідному повідомленні.

---

## Запуск

### Розробка

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

### Реєстрація команд бота (один раз)

```bash
python setup_commands.py

# Перезапустити після додавання суперадмінів або зміни описів:
python setup_commands.py --force
```

---

## Команди

### Публічні (всі чати)

| Команда            | Де          | Опис                                               |
|--------------------|-------------|----------------------------------------------------|
| `/start`           | ЛС + групи  | Привітання від бота                                |
| `/help`            | ЛС + групи  | Інструкція з використання                          |
| `/about`           | ЛС + групи  | Поточні налаштування особистості для цього чату    |
| `/reset`           | ЛС + групи  | Очистити свою історію розмови                      |
| `/dont_touch_me`   | Групи       | Додати себе в недоторканні                         |
| `/settings`        | ЛС          | Відкрити особисте меню налаштувань                 |

### Для адміністраторів (тільки в групах)

| Команда     | Де     | Опис                                                  |
|-------------|--------|-------------------------------------------------------|
| `/toxic`    | Групи  | Відповісти на повідомлення — бот відреагує примусово  |
| `/settings` | Групи  | Відкрити інлайн-меню налаштувань                      |

Команди адміністратора тихо видаляються, якщо той, хто викликає, не є адміністратором.

### Explain (відповідь на повідомлення)

| Команда    | Де          | Опис                                                |
|------------|-------------|-----------------------------------------------------|
| `/explain` | ЛС + групи  | Науковий/фактологічний аналіз тексту/фото/голосу    |

---

## Функції суперадміна

Суперадміни задаються через `SUPERADMIN_IDS` у `.env`. Команди працюють **тільки в особистому чаті** з ботом.

### Команди

| Команда          | Опис                                                      |
|------------------|-----------------------------------------------------------|
| `/sa_chats`      | Список активних чатів з ID та датами вступу               |
| `/sa_stats`      | Дашборд: runtime, чати/користувачі, оброблений контент, розміри БД |
| `/sa_broadcast`  | Надіслати повідомлення до всіх активних груп (діалог)     |
| `/cancel`        | Перервати поточний broadcast                              |

`/sa_chats` намагається підтягнути live-дані з Telegram за `chat_id` (ім'я/назва та `@username`) з fallback на БД.

### Автоматичні PM-сповіщення

- **Додано до чату** — назва, chat ID, тип
- **Кікнуто з чату** — назва, chat ID, тип

---

## Меню налаштувань

Адміністратори групи: `/settings` → інлайн-клавіатура. Зміни застосовуються одразу.

| Налаштування       | Діапазон / варіанти | Опис                                               |
|--------------------|---------------------|----------------------------------------------------|
| Рівень токсичності | 1–5                 | 1=м'яко, 5=ядерно                                  |
| Частота відповідей | min–max (випадково) | Як часто бот вступає в розмову                     |
| Кулдаун користувача| 30/60/120/300 сек   | Мінімальний інтервал між відповідями одному юзеру  |
| Кулдаун `/explain` | 10–600 хв (крок 10) | Інтервал між `/explain` від одного юзера в групах  |
| Глибина ланцюжка   | 3/5/7/10            | Скільки повідомлень назад читає в reply chain      |
| Мінімум слів       | 3/5/7/10            | Ігнорувати повідомлення коротші за це              |
| Керування юзерами  | Перегляд/скидання   | Перегляд і видалення профілів користувачів         |
| Недоторканні       | Список/видалення    | Видалення користувачів зі списку ігнору бота       |

В особистому чаті команда `/settings` відкриває персональне меню:
- рівень токсичності у ЛС
- глобальна недоторканність
- попередній перегляд досьє
- видалення власних даних з БД

---

## Система особистості

Венесда Аддамс × аналітична токсичність:

- **Логічне препарування** — називає помилки, цитує факти
- **Психологічний тиск** — б'є по конкретних слабкостях
- **Дотепність насамперед** — точно, ніколи не банально
- **Контекстуальність** — використовує історію та профілі користувачів

| Рівень | Назва                    | Стиль                                   |
|--------|--------------------------|-----------------------------------------|
| 1      | Холодне розчарування     | Сухе, відсторонене спостереження        |
| 2      | Логічне розтин           | Судовий розбір аргументів               |
| 3      | Психологічний тиск       | Хірургічне зондування (за замовч.)      |
| 4      | Озброєний дотеп          | Комплімент → поворот → укол             |
| 5      | Ядерна Венесда           | Повний вердикт із доказами              |

---

## Структура проекту

```
toxic-bot/
├── .env*                 # Секрети (не комітиться)
├── .env.example          # Шаблон
├── .gitignore
├── README.{md,ru.md,uk.md}
├── config.ini            # Несекретні дефолти
├── config.py             # Завантажувач конфігу (dataclasses)
├── bot.py                # Точка входу, хендлери, міграції
├── setup_commands.py     # Реєстрація команд Telegram
├── requirements.txt
├── ai/
│   ├── client.py             # AsyncOpenAI → CF Gateway → Groq
│   ├── prompts.py            # 5 рівнів × 3 мови + injection guard
│   ├── responder.py          # Основний пайплайн get_reply()
│   ├── summarizer.py         # Фонові профілі користувачів
│   ├── transcriber.py        # Голос → текст (Whisper)
│   └── vision.py             # Фото → base64 мультимодальність
├── db/
│   ├── pool.py               # asyncpg пул з'єднань
│   ├── migrations.py         # Ідемпотентні DDL-міграції
│   ├── chat_settings.py      # CRUD налаштувань чату
│   ├── history.py            # CRUD історії повідомлень
│   ├── chats.py              # CRUD трекінгу чатів
│   ├── metrics.py            # Персистентні лічильники аналітики
│   ├── user_profiles.py      # CRUD психологічних профілів
│   └── untouchables.py       # CRUD недоторканних користувачів
├── handlers/
│   ├── commands_public.py    # /start /help /about /reset /dont_touch_me /toxic
│   ├── commands_explain.py   # /explain (мультимодальний)
│   ├── messages.py           # Основний хендлер + freq/cooldown логіка
│   ├── lifecycle.py          # Вступ/вихід + PM суперадміна
│   ├── pm_settings.py        # Особисте меню /settings
│   ├── superadmin.py         # /sa_* команди
│   ├── language_select.py    # Вибір мови
│   └── admin_menu/
│       ├── callbacks.py          # Константи callback data
│       ├── main_menu.py          # Вхід до меню налаштувань
│       ├── frequency_menu.py     # Меню частоти min/max
│       ├── toxicity_menu.py      # Меню рівнів токсичності
│       ├── simple_choice_menus.py# Cooldown/chain/minwords
│       ├── user_management_menu.py# UI керування профілями
│       ├── untouchables_menu.py  # UI недоторканних
│       └── router.py             # Диспетчер callback
├── i18n/
│   ├── __init__.py         # gettext(key, lang, **kwargs)
│   ├── en.json
│   ├── ru.json
│   └── ua.json
└── utils/
    ├── admin_check.py     # is_chat_admin() + суперадмін bypass
    ├── rate_limiter.py    # Кулдаун на юзера
    ├── reply_chain.py     # Збирач reply chain
    └── tg_safe.py         # Безпечні обгортки send/edit (RetryAfter тощо)
```

*Не комітиться

---

## Переклади

- [README in English](README.md)
- [README на русском](README.ru.md)
