# Landings (export only)

Marketing pages for **public** demo repositories. **Not** the product source.

| Folder | Publish to | Language |
|--------|------------|----------|
| `en/` | `https://github.com/Jeweyl/HabiTrackerBot` (public) | English |
| `ru/` | `https://github.com/Jeweyl/HabiTracker-RU` (public) | Russian |

## Do not publish from here

- Anything outside `landing/en` or `landing/ru`
- Bot/API/dashboard source (`src/`, `web/` app, Docker product stack, `.env*`)

## Suggested public repo layout

```
# HabiTrackerBot (EN)
index.html      ← from landing/en/index.html
styles.css
media/
README.md       ← from landing/en/README.md
LICENSE         ← proprietary / assets-only notice

# HabiTracker-RU
(same from landing/ru/)
```

## GitHub Pages

In each public repo: Settings → Pages → Deploy from branch → `/` (root) or `/docs`.

## Media

Drop GIFs/screenshots into `en/media/` and `ru/media/` (or shared exports).  
Filenames expected by the HTML placeholders:

- `demo-habit.gif` — create habit / complete day
- `demo-ai.gif` — AI assistant flow
- `demo-dashboard.png` — Vue dashboard

## Local preview

```powershell
cd landing/en
python -m http.server 5500
# open http://127.0.0.1:5500
```

Cross-language links on the pages point at GitHub Pages:

- EN site: `https://jeweyl.github.io/HabiTrackerBot/`
- RU site: `https://jeweyl.github.io/HabiTracker-RU/`

Enable Pages on each public repo (branch root). Until then, links 404 — that is expected.


## Product remote reminder

Private product: **HabiTrackerBot-PRO** only.  
`git remote -v` in the monorepo must not silently push product code to the public EN demo repo.
