# Freemium & points — internal spec

Status: **design** (not fully implemented in code yet).  
Audience: product / engineering. Not for public demo repos.

## Goals

1. Keep **core habit tracking free forever** so daily retention does not depend on payment.
2. Gate **costly or high-perceived-value** features behind points or Pro.
3. Prefer **Telegram Stars** for first payments (low friction inside Telegram).

## Feature split

### Always free (core)

- Create / edit / delete habits (manual wizard)
- Create / edit / delete one-off tasks
- Calendar & lazy task generation
- Complete / skip, check-in prompts
- Time conflict detection
- Settings: language, timezone, notification time, check interval
- Basic statistics **inside the bot** (counts, simple streak / % text)

### Premium (spend points or Pro)

| Feature | Why gated |
|---------|-----------|
| AI habit wizard (multi-turn SMART) | OpenRouter cost |
| AI one-off task assistant | OpenRouter cost |
| Vue dashboard session (OTT → charts / breakdown / schedule) | High perceived value |
| Future: export, advanced analytics, priority support | Upsell |

## Points economy (v1 targets — calibrate with real cost)

### Wallet

- `points_balance` (int, never negative after successful spend)
- `points_week_anchor` (UTC date of last weekly grant applied)
- `plan`: `free` | `pro`
- `plan_until` (nullable datetime)

### Ledger

Every grant/spend/refund:

- `user_id`, `delta` (+/−), `reason`, `ref_id` (optional), `created_at`

Reasons (examples): `weekly_grant`, `ai_habit`, `ai_task`, `dashboard_open`, `stars_pack`, `admin_adjust`, `referral`, `refund_ai_fail`.

### Weekly grant (free tier)

- Amount: **40 points** / week (starting point)
- Reset: **Monday 00:00 UTC** (v1 — not user timezone)
- On first activity after anchor week changes → add grant once, update anchor
- Pro users: skip spend checks (unlimited premium) while `plan_until` is valid

### Spend table (v1)

| Action | Cost | When to charge |
|--------|------|----------------|
| AI habit session | 12 pts | On successful plan apply (prefer) **or** session start — pick one policy and keep it |
| AI task session | 8 pts | Same policy as habit AI |
| Dashboard open | 4 pts | Once per UTC day per user when issuing OTT / first API use that day |

**Failed AI** (timeout, empty, invalid JSON after retries): **do not** charge; if charged at start, refund via ledger.

### UX rules

1. Core never blocked by zero points.
2. Before spend: show cost and remaining balance.
3. At zero: soft paywall — wait for weekly grant / buy pack / upgrade Pro.
4. Show balance on `/start`, settings, and premium entry points.

## Paid products (M2+)

### Point packs (Telegram Stars)

- Small / medium / large packs with bonus on larger sizes
- Credit ledger `stars_pack` after successful payment

### Pro

- Weekly or monthly
- Unlimited AI + dashboard while active
- Optional: higher limits later (teams, white-label excluded)

## Abuse & cost control

- Cap free weekly grant so worst-case OpenRouter cost per free user is acceptable
- Rate-limit AI starts per user per hour
- Admin: adjust balance, inspect ledger, flag abuse

## Implementation sketch

```
src/services/points_service.py
  ensure_weekly_grant(session, user) -> User
  can_spend(user, amount) -> bool
  spend(session, user, amount, reason, ref_id=None) -> None  # raises if insufficient
  credit(session, user, amount, reason, ref_id=None) -> None

Guards:
  AI handlers — before calling OpenRouter / before apply
  dashboard_link / OTT issue — before minting token
```

### Schema (Alembic later)

- `users.points_balance`, `users.points_week_anchor`, `users.plan`, `users.plan_until`
- table `points_ledger`

## Metrics to watch

- Cost per AI session (provider)
- Free grant cost / MAU / week
- Free → pay conversion
- D1 / D7 retention on core-only users
- % users hitting 0 points (paywall timing)

## Out of scope for first code drop

- Referral bonuses
- Non-Telegram payments (cards, ЮKassa)
- Per-timezone weekly reset
