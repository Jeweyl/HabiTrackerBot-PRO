# Railway deploy — bot + API + dashboard (Variant B)

Topology for **existing bot already on Railway**, with dashboard as a **separate repo/service**.

| Service | Repo | Image / start |
|---------|------|----------------|
| **bot** | HabiTrackerBot-PRO (`Telegram/`) | Dockerfile default: `alembic upgrade head && python src/main.py` |
| **api** | HabiTrackerBot-PRO (same repo, 2nd service) | Override: `uvicorn src.api.app:app --host 0.0.0.0 --port $PORT` |
| **web** | HabiTrackerBOT-WEB (`Web/`) | Dockerfile (nginx SPA); **build** var `VITE_API_BASE_URL` |
| postgres / redis | Railway plugins or existing | Shared by **bot** and **api** |

**Do not** create a 3rd API repo.  
**Do not** use Marketplace nginx templates — WEB image already has nginx + SPA.  
**Do not** rely on compose hostname `api:8000` across separate Railway services (use public API URL + CORS).

---

## Prerequisites (git)

1. **PRO** (`Telegram/`): remote `https://github.com/Jeweyl/HabiTrackerBot-PRO.git` — commit & push latest (web removed from compose, stats/API, env docs).
2. **WEB** (`Web/`): remote `https://github.com/Jeweyl/HabiTrackerBot-WEB.git` (or `HabiTrackerBOT-WEB`) — `git init` if needed, first push of dashboard sources.

Until both remotes have current code, Railway builds will be stale.

---

## Order of operations

Deploy in this order so domains exist before wiring env:

```text
1. Confirm Postgres + Redis (already used by bot)
2. Add / deploy **api** service → Generate Domain → note API_URL
3. Add / deploy **web** service with VITE_API_BASE_URL=API_URL → Generate Domain → note WEB_URL
4. Set bot DASHBOARD_PUBLIC_URL=WEB_URL
5. Set api API_CORS_ORIGINS=WEB_URL
6. Redeploy bot + api if vars changed after first start
7. Smoke test
```

---

## 1. Shared data plane

On the **same Railway project** as the bot:

- **PostgreSQL** — `DATABASE_URL` must be usable by both bot and api  
  - App expects SQLAlchemy async URL: `postgresql+asyncpg://...`  
  - If Railway gives `postgresql://`, set  
    `DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:<port>/<db>`  
    (same credentials; only driver prefix changes).
- **Redis** — one `REDIS_URL` for bot **and** api (OTT keys live here).

Copy/reference the same variables into the **api** service (Railway “Variable reference” / shared vars).

---

## 2. Service: **api** (from PRO)

1. **New service** → Deploy from GitHub → **HabiTrackerBot-PRO**.
2. Root directory: repo root (where `Dockerfile` and `src/` live).
3. Builder: **Dockerfile** (same as bot).
4. **Custom start command** (important — do **not** use bot CMD):

   ```bash
   uvicorn src.api.app:app --host 0.0.0.0 --port $PORT
   ```

   - Migrations stay on **bot** (`alembic upgrade head` in bot Dockerfile).  
   - Avoid two services racing Alembic on every deploy.

5. **Variables** (mirror bot where shared):

   | Variable | Value |
   |----------|--------|
   | `DATABASE_URL` | same DB as bot (`postgresql+asyncpg://...`) |
   | `REDIS_URL` | same Redis as bot |
   | `API_JWT_SECRET` | **identical** long secret as bot |
   | `API_JWT_EXPIRE_MINUTES` | `60` (or same as bot) |
   | `API_OTT_TTL_SECONDS` | `60` (or same as bot) |
   | `API_CORS_ORIGINS` | set **after** web domain exists: `https://<web-domain>` (no path, no trailing slash) |
   | `API_HOST` | optional; start command binds `0.0.0.0` |
   | `API_PORT` | optional; **use `$PORT` in start command**, not a fixed 8000 |

6. **Networking** → **Generate domain** → e.g. `https://habi-api-production-xxxx.up.railway.app`  
   → call this **`API_URL`** (no trailing slash).

7. Smoke:

   ```text
   GET https://<API_URL>/health
   → {"status":"ok"}  (or equivalent HealthResponse)
   ```

---

## 3. Service: **web** (from WEB repo)

1. **New service** → GitHub → **HabiTrackerBOT-WEB** / `HabiTrackerBot-WEB`.
2. Root: `/`. Dockerfile: `Dockerfile`.
3. **Build argument / build-time variable** (Variables → mark as available at **build** if Railway splits build/runtime):

   ```text
   VITE_API_BASE_URL=https://<API_URL>
   ```

   - No trailing slash.  
   - Vite **bakes** this into the SPA at `npm run build`. Changing it requires **rebuild**, not only restart.

4. Runtime: image listens on **`$PORT`** (nginx template). Do not force port 80 only.
5. **Generate domain** → e.g. `https://habi-dash-production-xxxx.up.railway.app`  
   → call this **`WEB_URL`** (no trailing slash).
6. Open `WEB_URL` in browser → login shell / “open link from bot” (no token yet is OK).

**Do not** attach Marketplace nginx or a second reverse-proxy template.

---

## 4. Wire **bot** env

On the existing **bot** service:

| Variable | Value |
|----------|--------|
| `DASHBOARD_PUBLIC_URL` | `https://<WEB_URL>` |
| `API_JWT_SECRET` | **same** as api |
| `REDIS_URL` | **same** as api |
| `DATABASE_URL` | existing |

Redeploy bot after setting `DASHBOARD_PUBLIC_URL`.

In Telegram stats UI you should get **Open dashboard** when OTT succeeds. If missing: check bot logs for empty `DASHBOARD_PUBLIC_URL` or Redis errors; use **refresh link**.

---

## 5. Wire **api** CORS

On **api** service:

```text
API_CORS_ORIGINS=https://<WEB_URL>
```

- Exact browser origin (scheme + host, no trailing `/`).  
- Multiple origins: comma-separated.  
- Empty `API_CORS_ORIGINS` may allow all in code — **do not** leave empty in production.

Redeploy **api** after setting CORS.

---

## 6. End-to-end smoke checklist

| # | Check | Expected |
|---|--------|----------|
| 1 | `GET {API_URL}/health` | 200 ok |
| 2 | Browser → `{WEB_URL}` | SPA loads (no blank nginx error) |
| 3 | Bot → Statistics → Open dashboard | Button present; URL host = WEB_URL |
| 4 | Open link quickly (OTT TTL ~60s) | Login exchange → dashboard charts |
| 5 | Browser DevTools → Network | `POST {API_URL}/api/v1/auth/exchange` 200; `GET .../stats/...` 200 |
| 6 | CORS failure? | Console blocked by CORS → fix `API_CORS_ORIGINS` to exact WEB origin |
| 7 | 401 on stats | Expired JWT or bad `API_JWT_SECRET` mismatch bot/api |
| 8 | Exchange 400/401 | OTT expired, Redis not shared, or bot/api different Redis |

---

## Env contract (summary)

```text
# bot
DASHBOARD_PUBLIC_URL=https://<web>
API_JWT_SECRET=<shared>
REDIS_URL=<shared>
DATABASE_URL=postgresql+asyncpg://...

# api
DATABASE_URL=<same>
REDIS_URL=<same>
API_JWT_SECRET=<same as bot>
API_CORS_ORIGINS=https://<web>
# start: uvicorn src.api.app:app --host 0.0.0.0 --port $PORT

# web (build-time)
VITE_API_BASE_URL=https://<api>
```

---

## Common failures

| Symptom | Cause | Fix |
|---------|--------|-----|
| Web service crash / no HTTP | nginx only on 80, Railway `$PORT` ignored | Use current WEB Dockerfile + `nginx.conf.template` (`listen ${PORT}`) |
| Dashboard button missing | `DASHBOARD_PUBLIC_URL` empty | Set on bot; redeploy |
| Exchange fails | Redis not shared / OTT TTL | Same `REDIS_URL`; open link within ~60s |
| CORS errors in browser | Wrong origin | `API_CORS_ORIGINS` = exact `https://web-host` |
| API calls go to web host `/api` | Empty `VITE_API_BASE_URL` at build | Rebuild web with public API URL |
| 502 on API | Start still runs bot CMD | Override start to uvicorn + `$PORT` |
| JWT invalid | Different secrets | Align `API_JWT_SECRET` on bot and api |
| DB errors on api | Sync URL without asyncpg | Use `postgresql+asyncpg://` |

---

## Optional later

- Railway **private networking**: web nginx `proxy_pass` to private api host + empty `VITE_API_BASE_URL` (same-origin `/api`) — not required for Variant B.
- Custom domains on web + api; then update `DASHBOARD_PUBLIC_URL`, `API_CORS_ORIGINS`, rebuild web `VITE_API_BASE_URL`.

---

## Local parity

```bash
# PRO
uvicorn src.api.app:app --host 0.0.0.0 --port 8000

# WEB
# .env: VITE_API_BASE_URL=   (empty → Vite proxy to :8000)
npm run dev
```

Docker web with public API shape:

```bash
docker build -t habitracker-web \
  --build-arg VITE_API_BASE_URL=https://your-api.example.com \
  .
docker run --rm -e PORT=8080 -p 8080:8080 habitracker-web
```
