# HabiTrackerBot-PRO

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![License](https://img.shields.io/badge/License-Proprietary-red.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)

**Private product repository.** Source is proprietary — not open source.

> **Live demo:** [@HabiTrakerBot](https://t.me/HabiTrakerBot) · **Channel:** [@HabiTraker](https://t.me/HabiTraker)

Public marketing (no source):

| Repo | Role |
|------|------|
| [HabiTrackerBot](https://github.com/Jeweyl/HabiTrackerBot) | EN landing + demo media |
| [HabiTracker-RU](https://github.com/Jeweyl/HabiTracker-RU) | RU landing + demo media |

Licensing & business: [COMMERCIAL.md](COMMERCIAL.md) · Freemium rules: [docs/FREEMIUM.md](docs/FREEMIUM.md) · Legal: [LICENSE](LICENSE)

---

## Product

HabiTracker is a **Telegram-first habit assistant**: templates generate daily tasks, time conflicts are blocked early, check-ins nudge without spam, and an AI wizard turns vague goals into SMART plans. A Vue dashboard adds charts and schedule views.

### Freemium (direction)

| Tier | Includes |
|------|----------|
| **Core (free)** | Habits, tasks, calendar, check-ins, conflicts, settings, basic in-bot stats |
| **Premium** | AI habit/task assistants, Vue dashboard & charts (points and/or Pro) |

Points economy and gates: [docs/FREEMIUM.md](docs/FREEMIUM.md). Implementation of billing is incremental; core tracking stays free.

---

## Capabilities

### Habits & tasks

- AI multi-turn wizard (SMART) and manual FSM wizards
- Daily / weekdays / weekends recurrence
- Lazy task generation from habit templates
- 15-minute time grid; conflict checks for tasks and habits
- Check-in prompts with `check_interval` anti-spam

### Statistics & web

- Completion % (7 / 30 days), streak, counters in bot
- Vue dashboard: charts, habit breakdown, read-only schedule
- One-time token login from the bot

### Settings

- RU / EN i18n, timezone, notification time, check interval

---

## Stack

| Layer | Tech |
|-------|------|
| Bot | Python 3.11+, aiogram 3.x |
| Stats API | FastAPI, Uvicorn, PyJWT |
| Dashboard | Vue 3, Vite, TypeScript, Chart.js |
| Data | PostgreSQL 15, Redis 7, SQLAlchemy 2, Alembic |
| AI | OpenRouter (primary + fallback) |
| Ops | Docker Compose, GitHub Actions CI, ~370 pytest |

---

## Operator quick start

Authorized operators only. Do not publish this repo or ship images built from it to third parties without a license.

```bash
docker compose up --build
docker compose exec bot alembic upgrade head
docker compose exec bot pytest -v
```

Bot profile texts:

```bash
python scripts/set_bot_profile.py --dry-run
python scripts/set_bot_profile.py
```

### Environment

Copy `.env.example` → `.env` (or `.env.prod.example` → `.env.prod`). Required highlights:

| Variable | Role |
|----------|------|
| `BOT_TOKEN` | Telegram bot token |
| `DATABASE_URL` | Async PostgreSQL URL |
| `REDIS_URL` | Redis URL |
| `ADMIN_ID` | Admin Telegram user id |
| `ROUTER_API_KEY` | OpenRouter (AI) |
| `API_JWT_SECRET` | Dashboard JWT HMAC (change in prod) |
| `DASHBOARD_PUBLIC_URL` | Public URL of HabiTrackerBOT-WEB |
| `API_CORS_ORIGINS` | Web origin(s) for browser stats API |

Dashboard UI is **not** in this repo — see sibling **HabiTrackerBOT-WEB** (`../Web`).


### Production

```bash
cp .env.prod.example .env.prod
docker compose -f docker-compose.prod.yml up -d --build
```

### Railway (bot + API + WEB)

Step-by-step Variant B (public API URL + CORS, separate WEB repo):  
**[docs/RAILWAY.md](docs/RAILWAY.md)**

| Service | Start / notes |
|---------|----------------|
| bot | Dockerfile default |
| api | `uvicorn src.api.app:app --host 0.0.0.0 --port $PORT` |
| web | HabiTrackerBOT-WEB Dockerfile; build `VITE_API_BASE_URL` |

---

## Architecture notes

- **Handlers → services → db** layering; FSM for multi-step wizards
- **AI pipeline:** schema (Pydantic) → normalize (15-min grid) → apply + conflicts
- **Time picker:** hour → minutes (00/15/30/45); shared grid for UI and AI
- **Stats:** OTT in Redis → JWT → read-only FastAPI → Vue

Key paths: `src/handlers/`, `src/services/`, `src/api/`, `tests/`.  
Vue dashboard: separate repo **HabiTrackerBOT-WEB**.


---

## Quality

```bash
black --check src/ tests/
ruff check src/ tests/
pytest
```


---

## Repository layout

```
src/           bot, FastAPI stats API, services, i18n
tests/         pytest
landing/en/    EN marketing page (publish to public HabiTrackerBot only)
landing/ru/    RU marketing page (publish to public HabiTracker-RU only)
docs/          internal product specs
alembic/       migrations
```

**Related repos**

| Repo | Role |
|------|------|
| **HabiTrackerBot-PRO** (this) | Telegram bot + stats API |
| **HabiTrackerBOT-WEB** | Vue dashboard |
| HabiTrackerBot / HabiTracker-RU | public landings only |

**Git remote:** this product tree must track **HabiTrackerBot-PRO** (private).  
Never push `src/` or secrets to public demo repos — only contents of `landing/en` or `landing/ru` (+ media).


```powershell
git remote -v
# expect: github.com/Jeweyl/HabiTrackerBot-PRO.git
# if still HabiTrackerBot.git:
git remote set-url origin https://github.com/Jeweyl/HabiTrackerBot-PRO.git
```

---

## License

**Proprietary.** Copyright (c) 2026 Jeweyl. All rights reserved.  
See [LICENSE](LICENSE) and [COMMERCIAL.md](COMMERCIAL.md).
