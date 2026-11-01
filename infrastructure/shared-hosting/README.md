# Shared hosting deploy (rasd.codexai.systems)

Hostinger shared hosting (CloudLinux, no Docker or root). Everything lives in `~/apps/rasd`, outside any public
folder; the domain's `public_html/.htaccess` only points LiteSpeed at the Node app.

| Path | What |
| --- | --- |
| `rasd.env` | production settings and secrets (chmod 600; symlinked as `.env` into `src/backend` and `src/telegram`) |
| `web/` | Next.js standalone build + `app.cjs` (this folder's entry point) |
| `src/backend`, `src/telegram` | Python code |
| `python/`, `venv/` | standalone Python 3.12 and the virtualenv |
| `pg/`, `data/pg` | PostgreSQL 17 binaries and data (Unix socket only, in `run/`) |
| `redis/`, `data/redis.conf` | Redis (Unix socket only, password) |
| `browsers/`, `libs/` | Playwright Chromium + two libraries the host lacks (libatk-bridge, libatspi) |
| `run/`, `logs/` | sockets, pid files, logs of every service |

`app.cjs` serves the site, proxies `/api` and `/telegram/webhook` to Unix sockets, and starts any stopped service
(now and every minute; also when a proxied request fails). The host caps an account at ~120 threads, so the
worker uses Celery's solo pool, the DB pool is small and Chromium runs single-process (`SCRAPER_BROWSER_ARGS`).

## Redeploy

Backend / bot code (from `ai-lead-hunter/`):

```sh
tar czf - --exclude=__pycache__ backend/app backend/migrations backend/alembic.ini backend/pyproject.toml \
  telegram/bot telegram/main.py | ssh -p 65002 u960306846@178.16.128.8 \
  'cd ~/apps/rasd && tar xzf - -C src && cd src/backend && ../../venv/bin/alembic upgrade head &&
   cd ~/apps/rasd && for s in api worker beat bot; do kill $(cat run/$s.pid); done'
```

The supervisor restarts the killed services within a minute (or on the next request).

Site: build the standalone output on Linux/glibc (e.g. `node:24-bookworm-slim`, with
`SITE_URL=https://rasd.codexai.systems`), copy `public/` and `.next/static` into it, extract it into `web/`
(keep `app.cjs` and `tmp/`), then `touch ~/apps/rasd/web/tmp/restart.txt`.
