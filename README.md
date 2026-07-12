# HabitTrackerBot — Telegram-бот для отслеживания привычек

![CI](https://github.com/Jeweyl/HabiTrackerBot/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)

> **Демо-бот**: [@HabiTrakerBot](https://t.me/HabiTrakerBot)

---

## О проекте

Формирование привычек — это не про силу воли, а про систему. Большинство трекеров привычек либо слишком простые (чекбокс «сделал / не сделал»), либо перегружены функциями. Я хотел создать инструмент, который:

- **Не заставляет думать о расписании** — бот сам генерирует задачи из шаблонов привычек.
- **Предотвращает конфликты времени** — нельзя случайно назначить две привычки на один слот.
- **Помогает формулировать цели** — встроенный AI-ассистент превращает расплывчатое «хочу больше двигаться» в конкретную SMART-цель.

В результате получился бот, в котором каждая фича решает реальную проблему пользователя, а не добавлена «для галочки».

---

## Возможности

### 📋 Управление привычками
- 🤖 **Создание с AI-ассистентом** — превращает описание в SMART-цель через OpenRouter API
- ✍️ **Ручное создание** — пошаговый мастер с валидацией на каждом шаге
- ✏️ **Редактирование и удаление** — изменение названия, времени, частоты с проверкой конфликтов
- 🔄 **Три типа периодичности** — ежедневно, по будням, по выходным

### 📅 Управление задачами
- 🗓 **Календарь** — навигация по месяцам, выбор любой даты
- ⚡ **Ленивая генерация** — задачи создаются из шаблонов привычек при первом открытии дня
- ✅ **Отметка выполнения** — toggle одним нажатием
- ✏️ **Редактирование** — изменение названия, даты, времени
- ⏰ **Автосдвиг окончания** — при изменении времени начала, время окончания автоматически сдвигается с сохранением длительности (если не задано вручную)

### 📊 Статистика
- 📈 **Процент выполнения** за 7 / 30 дней (в боте и на web-дашборде)
- 🔥 **Streak (серия дней)** — количество дней подряд без пропусков
- 📋 **Счётчики** — выполнено / пропущено / всего привычек
- 🖥 **Vue-дашборд** — графики completion, breakdown по привычкам, read-only schedule
- 🔗 **One-time token login** — кнопка «Открыть дашборд» в статистике бота

### ⚙️ Настройки
- 🌐 **Язык** — RU / EN (i18n-словари, расширяемо)
- 🕐 **Часовой пояс** — UTC от -12 до +14
- ⏰ **Время уведомлений** — 24 слота или отключение
- ⏱ **Интервал проверки** — от 5 до 60 минут (check-in по незавершённым задачам)

### ✅ Check-in уведомления
- 🔔 **Промпт «Выполнили …?»** для незавершённых задач после `start_time`
- ⏱ **Anti-spam** по `check_interval` (поле `last_checkin_at` на задаче)
- ✅/❌ **Ответ в один тап** — complete / skip без повторной спам-рассылки

### 🤖 AI-ассистент (привычки и задачи)
- 🔁 **Multi-turn** — до 3 уточняющих вопросов от модели
- 📐 **Строгий JSON-контракт** (Pydantic) + soft-fail на пустой/битый ответ
- ⏱ **Сетка 15 минут** — час → минуты (00/15/30/45); AI не «мухлюет» с duration
- 📅 **Привычка** → шаблон + генерация задач; **задача** → один пункт расписания (`habit_id=None`)

---


## Стек технологий

| Компонент | Технология |
|-----------|-----------|
| 🐍 Язык | Python 3.11+ |
| 🤖 Бот | aiogram 3.x |
| 🌐 Stats API | FastAPI + Uvicorn + PyJWT |
| � Dashboard | Vue 3 + Vite + TypeScript + Chart.js |
| �🗄 База данных | PostgreSQL 15 |
| ⚡ Кэш / FSM / OTT | Redis 7 |
| 📦 ORM | SQLAlchemy 2.0 (async) |
| 🔄 Миграции | Alembic |
| 🐳 Контейнеризация | Docker + Docker Compose (bot, api, web) |
| 🧠 AI | OpenRouter API (primary + fallback model) |
| 🧪 Тестирование | pytest + pytest-asyncio (~370 tests) |
| ✅ CI | GitHub Actions: Ruff, Black, pytest, vue-tsc, web build |

---

## Быстрый старт для разработчиков

Три команды, чтобы запустить проект:

```bash
# 1. Запуск (PostgreSQL, Redis, bot, API :8000, web :8080)
docker compose up --build

# 2. Применение миграций базы данных
docker compose exec bot alembic upgrade head

# 3. Запуск тестов (~370, SQLite in-memory)
docker compose exec bot pytest -v
# или локально: pytest -v
```

---

## Установка и запуск

### Предварительные требования

- [Docker](https://docs.docker.com/get-docker/) и Docker Compose
- Токен Telegram-бота (получить у [@BotFather](https://t.me/BotFather))
- API-ключ OpenRouter (опционально, для AI-ассистента)

### Полная инструкция

1. **Клонируйте репозиторий:**

   ```bash
   git clone https://github.com/Jeweyl/HabiTrackerBot.git
   cd HabiTrackerBot
   ```

2. **Создайте файл `.env` из примера:**

   ```bash
   cp .env.example .env
   ```

   Отредактируйте `.env`, указав свои значения (см. [Переменные окружения](#переменные-окружения)).

3. **Запустите проект:**

   ```bash
   docker compose up --build
   ```

   Бот запустится после того, как PostgreSQL и Redis станут доступны (healthcheck).

4. **Примените миграции Alembic:**

   ```bash
   docker compose exec bot alembic upgrade head
   ```

5. **Откройте Telegram** и напишите `/start` вашему боту.

### Продакшен-развёртывание

Для продакшен-окружения используйте отдельный Compose-файл:

```bash
cp .env.prod.example .env.prod
# Отредактируйте .env.prod с реальными данными
docker compose -f docker-compose.prod.yml up -d --build
```

### Развёртывание на Railway

1. **Подключите базы данных** в dashboard Railway:
   - `New` → `Database` → **PostgreSQL**
   - `New` → `Database` → **Redis**

2. **Создайте сервис** из репозитория:
   - `New` → `GitHub Repo` → выберите репозиторий
   - Railway автоматически обнаружит `Dockerfile`

3. **Задайте переменные окружения** (Service → Variables):

   | Переменная | Значение |
   |------------|----------|
   | `BOT_TOKEN` | Токен от @BotFather **без кавычек и пробелов** |
   | `DATABASE_URL` | Reference: `${{Postgres.DATABASE_URL}}` |
   | `REDIS_URL` | Reference: `${{Redis.REDIS_URL}}` |
   | `ADMIN_ID` | Ваш Telegram ID |
   | `ROUTER_API_KEY` | API-ключ OpenRouter |
   | `AI_MODEL` | `deepseek/deepseek-v4-flash` |
   | `AI_FALLBACK_MODEL` | `meta-llama/llama-3.1-8b-instruct` |

   > **Важно:** `DATABASE_URL` и `REDIS_URL` должны быть ссылками (Reference)
   > на плагины Railway, а не захардкоженными значениями вроде
   > `redis://redis:6379/0` — это работает только в docker-compose.
   >
   > `postgresql://` автоматически конвертируется в `postgresql+asyncpg://`
   > в коде — вручную менять схему не нужно.

4. **Проверьте переменные** в Railway Shell:
   ```bash
   python -c "import os; print(repr(os.environ.get('BOT_TOKEN','')))"
   ```
   Убедитесь, что нет пробелов, переносов строк или кавычек в значении.

5. **Миграции** — выполняются **автоматически** при старте контейнера
   (через `alembic upgrade head` в `Dockerfile`).
   При необходимости можно запустить вручную в Railway Shell:
   ```bash
   alembic upgrade head
   ```

6. **Redeploy** — после изменения Variables нажмите `Redeploy`.


---

## Переменные окружения

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `BOT_TOKEN` | Токен Telegram-бота от @BotFather | `123456:ABCdef...` |
| `DATABASE_URL` | URL PostgreSQL (asyncpg) | `postgresql+asyncpg://postgres:postgres@postgres:5432/habits_bot` |
| `REDIS_URL` | URL Redis | `redis://redis:6379/0` |
| `ADMIN_ID` | Telegram ID администратора | `123456789` |
| `ROUTER_API_KEY` | API-ключ OpenRouter (опционально) | `sk-or-v1-...` |
| `AI_MODEL` | Primary AI model | `deepseek/deepseek-v4-flash` |
| `AI_FALLBACK_MODEL` | Fallback model | `meta-llama/llama-3.1-8b-instruct` |
| `AI_TIMEOUT` | HTTP timeout OpenRouter (сек) | `30` |
| `BOT_HTTP_TIMEOUT` | Timeout Telegram API (сек) | `10` |
| `DB_POOL_SIZE` | SQLAlchemy pool size | `5` |
| `REMINDER_POLL_SECONDS` | Интервал reminder/check-in loop | `300` |
| `BOT_PUBLIC_URL` | Публичная ссылка на бота (onboarding) | `https://t.me/HabiTrakerBot` |
| `CHANNEL_URL` | Канал (onboarding) | `https://t.me/HabiTraker` |
| `ORIGINAL_BOT_USERNAME` | Username оригинала без `@` | `HabiTrakerBot` |
| `API_JWT_SECRET` | **Обязательно сменить в prod** — HMAC JWT | long random secret |
| `API_JWT_EXPIRE_MINUTES` | TTL access JWT | `60` |
| `API_OTT_TTL_SECONDS` | TTL one-time dashboard token | `60` |
| `API_CORS_ORIGINS` | CORS origins (пусто = `*`) | `https://dash.example.com` |
| `API_HOST` / `API_PORT` | Bind stats API | `0.0.0.0` / `8000` |
| `DASHBOARD_PUBLIC_URL` | Базовый URL Vue-дашборда | `http://localhost:8080` |

---

## Ключевые архитектурные решения

### 1. 🎯 Динамическая фильтрация кнопок времени

**Проблема:** При выборе времени окончания задачи пользователь может выбрать время раньше начала — это невалидно.

**Решение:** Функция `get_time_selection_keyboard(min_time=...)` динамически фильтрует кнопки: если выбрано начало в 14:00, кнопки с 00:00 до 14:00 не отображаются. Сетка автоматически дополняется пустыми кнопками для выравнивания по 3 колонки. Если доступных вариантов нет — показывается заглушка «Нет доступных вариантов».

**Файлы:** `src/keyboards/inline.py`, `src/handlers/tasks.py`, `src/handlers/habits.py`

### 2. 🤖 FSM-мастер с пошаговым созданием

**Проблема:** Создание привычки или задачи — многошаговый процесс (название → время начала → время окончания → частота → подтверждение). Нужно сохранить данные между шагами и позволить вернуться назад.

**Решение:** Использование конечного автомата (FSM) aiogram с отдельными классами состояний: `NewHabitFSM`, `NewTaskFSM`, `EditHabitFSM`, `EditTaskFSM`, `ConflictFSM`, `ConflictHabitFSM`. Данные сохраняются между шагами через `FSMContext`, что позволяет пользователю перемещаться назад без потери введённых значений.

**Файлы:** `src/states/fsm.py`, `src/handlers/habits.py`, `src/handlers/tasks.py`

### 3. 🧠 AI pipeline: schema → normalize → apply

**Проблема:** AI-модели нестабильны и могут «мухлевать» со временем (15 мин в тексте, 60 мин в schedule).

**Решение:**
- `ai_service` — timeout из config, primary + fallback model, empty content → `None`
- `ai_schema` — строгий Pydantic-контракт (`AskQuestions` \| `ProposePlan` \| `ProposeTaskPlan`)
- `ai_normalize` — snap к сетке 15 мин, `end = start + duration`, preview warnings
- `ai_apply` — запись habit/task + conflict check, без hardcoded 08:00–09:00
- Multi-turn clarifying (max 3) + waiting indicator

**Файлы:** `src/services/ai_*.py`, `src/handlers/ai_assistant.py`, `src/handlers/ai_task_assistant.py`

### 4. ⏰ Проверка конфликтов временных слотов

**Проблема:** Две привычки могут пересекаться по времени и дням недели — нужно предотвратить или хотя бы предупредить.

**Решение:** Два уровня проверки:
- **Для задач** (`is_time_slot_free`): проверка пересечения интервалов `[start, end)` на конкретную дату
- **Для привычек** (`check_habit_conflicts`): проверка пересечения по времени **и** по дням недели (например, «ежедневно» и «по будням» пересекаются в будние дни)

При обнаружении конфликта пользователю предлагается: добавить всё равно, изменить время/частоту или отменить.

**Файлы:** `src/utils/conflict.py`

### 5. 🧪 Тестирование и CI

**Проблема:** Бот + AI + API + web нуждаются в быстрых изолированных тестах.

**Решение:**
- **~370 pytest** — handlers, services, API, i18n, time picker, AI schema/normalize/apply
- **In-memory SQLite** + mock Telegram session / MemoryTokenStore
- **CI:** Ruff, Black, pytest, `vue-tsc`, Vite build

**Файлы:** `tests/`, `pytest.ini`, `.github/workflows/ci.yml`, `web/`

---

## Почему этот проект достоин внимания

Этот бот — не учебный туториал, а полноценный продукт с продуманной архитектурой. Вот что я сделал:

- 🏗 **Спроектировал архитектуру** с разделением на слои (handlers → services → db) и реализовал FSM-мастер для пошагового создания привычек и задач
- 🧠 **AI multi-turn** для привычек и задач со строгим JSON, normalize duration и apply в schedule
- ⏰ **Конфликты** временных слотов + check-in уведомления по `check_interval`
- 🎯 **Time picker 15 мин** (час → минуты) и единая сетка для UI и AI
- 🖥 **Vue dashboard + FastAPI** (OTT→JWT, read-only stats/charts/schedule)
- 🧪 **~370 тестов** + CI (lint, pytest, web typecheck/build)

---

## Запуск тестов

```bash
# Все тесты (~370)
pytest -v
# или
docker compose exec bot pytest -v

# Конкретный файл
pytest tests/test_services/test_ai_normalize.py -v
```

Тесты используют **SQLite in-memory** — реальная PostgreSQL не требуется.

---

## Структура проекта

```
.
├── .github/
│   └── workflows/
│       └── ci.yml                # GitHub Actions CI (Ruff, Black, pytest)
├── alembic/
│   ├── env.py                    # Конфигурация Alembic
│   ├── script.py.mako            # Шаблон миграций
│   └── versions/                 # Файлы миграций
├── src/
│   ├── __init__.py
│   ├── bot.py                    # Bot + Redis FSM + HTML parse_mode
│   ├── config.py                 # pydantic-settings
│   ├── main.py                   # Entry: polling + reminder/check-in loop
│   ├── api/                      # FastAPI stats API (OTT → JWT)
│   ├── db/                       # SQLAlchemy models + session
│   ├── handlers/                 # Telegram routers (habits, tasks, AI, settings…)
│   ├── i18n/                     # RU/EN string catalogs + t()
│   ├── keyboards/                # Inline / reply keyboards
│   ├── services/                 # AI, apply, normalize, checkin, stats, dashboard
│   ├── states/                   # FSM states
│   └── utils/                    # conflict, time_picker, timezone
├── web/                          # Vue 3 dashboard (Chart.js)
├── tests/                        # pytest (handlers, services, api, utils)
├── pytest.ini
├── docker-compose.yml            # bot + api + web + postgres + redis
├── docker-compose.prod.yml
├── Dockerfile
├── requirements.txt
└── requirements-dev.txt
```


---

## Как внести свой вклад

Проект открыт для форков и пул-реквестов! Я приветствую вклад и готов к сотрудничеству. Пожалуйста, следуйте этим правилам:

### Стиль кода

- **Форматирование**: [Black](https://github.com/psf/black) (line length 88)
- **Линтер**: [Ruff](https://github.com/astral-sh/ruff)
- **Типизация**: аннотации типов (type hints) для всех публичных функций и методов
- **Docstrings**: Google-стиль для всех публичных функций и классов
- **Язык**: русский для пользовательских сообщений, английский для кода и комментариев

### Перед отправкой PR

```bash
# Проверка форматирования
black --check src/ tests/

# Линтинг
ruff check src/ tests/

# Запуск тестов
pytest
```

Все проверки должны проходить без ошибок. CI в GitHub Actions сделает это автоматически при пуше.

---

## Лицензия

[MIT](LICENSE) — проект полностью открыт. Вы можете свободно использовать, модифицировать и распространять код. Форки и пул-реквесты приветствуются!

---

**Демо-бот**: [@HabiTrakerBot](https://t.me/HabiTrakerBot)