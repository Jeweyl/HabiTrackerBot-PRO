# HabiTrackerBot-PRO

**Production-oriented Python backend for a Telegram habit management system with an async API, AI-assisted task planning, PostgreSQL, Redis, and a separate Vue dashboard.**

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791.svg)
![Redis](https://img.shields.io/badge/Redis-7-DC382D.svg)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)

> **Live demo:** [@HabiTrakerBot](https://t.me/HabiTrakerBot)

## Overview

HabiTracker is a Telegram-first habit and task management system. The backend combines an asynchronous Telegram bot, a FastAPI statistics/account API, PostgreSQL for persistent state, Redis for short-lived authentication data, and an AI pipeline that converts natural-language requests into validated structured commands.

The project is intentionally split into a backend/API repository and a separate Vue dashboard.

## Engineering highlights

- **Async Python:** aiogram 3, FastAPI, SQLAlchemy 2 async stack
- **API:** FastAPI + Uvicorn with JWT-based dashboard authentication
- **Persistence:** PostgreSQL 15 + Alembic migrations
- **Caching / ephemeral state:** Redis, including one-time authentication tokens
- **AI integration:** natural language → structured Pydantic schema → normalization → business rules → persistence
- **Scheduling:** 15-minute time grid, recurrence rules, lazy task generation, conflict detection
- **Application architecture:** handlers → services → data access
- **Testing:** ~370 pytest tests
- **Quality:** Ruff, Black, automated CI
- **Deployment:** Docker Compose and production-oriented compose configuration
- **Frontend:** separate Vue 3 / TypeScript dashboard

## Architecture

```text
                    Telegram
                       │
                       ▼
                ┌─────────────┐
                │  aiogram 3  │
                │   Bot       │
                └──────┬──────┘
                       │
                       ▼
                ┌─────────────┐
                │  Services   │
                │  + Domain   │
                └───┬─────┬───┘
                    │     │
             ┌──────┘     └──────────┐
             ▼                        ▼
      ┌─────────────┐          ┌─────────────┐
      │ PostgreSQL  │          │    Redis     │
      │   state     │          │ OTT / cache  │
      └─────────────┘          └─────────────┘
                    │
                    ▼
             ┌─────────────┐
             │  FastAPI    │
             │ Stats/Auth  │
             └──────┬──────┘
                    │
                    ▼
             ┌─────────────┐
             │ Vue 3 Web   │
             │ Dashboard   │
             └─────────────┘
```

### AI task pipeline

AI output is not applied directly to the database. The backend validates and normalizes the model response before executing business logic:

```text
Natural language
      ↓
LLM
      ↓
Pydantic schema
      ↓
Normalization
      ↓
Scheduling / conflict rules
      ↓
Service layer
      ↓
PostgreSQL
```

This keeps model output separate from application state and allows business constraints to be enforced independently of the LLM.

## Core backend capabilities

### Tasks and habits

- Daily, weekday, and weekend recurrence
- Lazy task generation from habit templates
- 15-minute scheduling grid
- Task and habit conflict detection
- Untimed tasks
- Per-task automatic rollover
- Completion tracking, streaks, and statistics
- Check-in prompts with configurable anti-spam behaviour

### Natural-language control

Users can interact with the bot using natural language for operations such as:

- creating, deleting, and completing tasks;
- creating habits;
- specifying relative times such as "in 20 minutes";
- opening the habit wizard.

The AI layer produces structured data; the service layer remains responsible for validation and application of domain rules.

### Authentication and web API

The dashboard authentication flow uses a one-time token issued through the Telegram bot:

```text
Telegram bot
    ↓
one-time token
    ↓
Redis
    ↓
FastAPI
    ↓
JWT
    ↓
Vue dashboard
```

The API exposes account and statistics endpoints under `/me` and `/stats/*`.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Telegram | aiogram 3.x |
| API | FastAPI, Uvicorn |
| Validation | Pydantic |
| ORM | SQLAlchemy 2 async |
| Database | PostgreSQL 15 |
| Cache / ephemeral state | Redis 7 |
| Migrations | Alembic |
| Authentication | PyJWT |
| AI | OpenRouter with fallback |
| Frontend | Vue 3, Vite, TypeScript, Chart.js |
| Runtime | Docker Compose |
| CI / quality | GitHub Actions, pytest, Ruff, Black |

## Project structure

```text
src/
├── api/          FastAPI application
├── handlers/     Telegram handlers and FSM flows
├── services/     application and domain logic
└── i18n/         localization

tests/             pytest test suite
alembic/           database migrations
docs/              architecture, deployment and product documentation
landing/           public marketing pages
```

The Vue dashboard is maintained separately in **HabiTrackerBot-WEB**.

## Running locally

### Requirements

- Docker + Docker Compose
- Telegram bot token
- PostgreSQL and Redis are provided by Docker Compose
- OpenRouter API key if AI functionality is enabled

### Start backend

```bash
docker compose up --build
docker compose exec bot alembic upgrade head
```

Run tests:

```bash
docker compose exec bot pytest -v
```

### Environment

Copy `.env.example` to `.env` and configure the required values:

| Variable | Purpose |
|---|---|
| `BOT_TOKEN` | Telegram bot token |
| `DATABASE_URL` | Async PostgreSQL connection |
| `REDIS_URL` | Redis connection |
| `ADMIN_ID` | Administrator Telegram ID |
| `ROUTER_API_KEY` | OpenRouter API key |
| `API_JWT_SECRET` | JWT signing secret |
| `DASHBOARD_PUBLIC_URL` | Dashboard URL |
| `API_CORS_ORIGINS` | Allowed dashboard origins |

## Production

Production configuration is provided through `docker-compose.prod.yml`.

```bash
cp .env.prod.example .env.prod
docker compose -f docker-compose.prod.yml up -d --build
```

The repository also contains deployment documentation for Railway.

## Quality checks

```bash
black --check src/ tests/
ruff check src/ tests/
pytest
```

The test suite contains approximately 370 tests covering application behaviour and backend logic.

## Related repositories

| Repository | Role |
|---|---|
| **HabiTrackerBot-PRO** | Telegram bot + FastAPI backend |
| **HabiTrackerBot-WEB** | Vue 3 dashboard |
| **HabiTrackerBot** | Public EN landing / demo media |
| **HabiTracker-RU** | Public RU landing / demo media |

## License

This repository contains proprietary software.

See [LICENSE](LICENSE) and [COMMERCIAL.md](COMMERCIAL.md) for licensing and usage terms.

---

## Demo

**Telegram:** [@HabiTrakerBot](https://t.me/HabiTrakerBot)
