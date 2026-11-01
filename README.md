# Rasd (رصد) — client finding for service businesses

Discovers businesses from authorized sources, enriches **published business contact channels**, analyses
opportunities with **evidence-grounded AI**, scores leads deterministically, and manages them in a CRM.
A web dashboard (EN/AR, RTL) and a Telegram bot share **one** FastAPI backend, database and job queue.

Brand: **Rasd (رصد)**, a radar that spots your next clients. Ink `#071A17`, Rasd green `#0B8A63`,
Signal lime `#C8F169`, Paper `#F7F7F2` (tokens in `frontend/src/app/globals.css`). Fonts: Readex Pro (headings)
and IBM Plex Sans Arabic (text), both loaded with `next/font`. Marketing copy never names data providers.

---

## 1. Architecture

```text
 Next.js 16 dashboard ──/api (same origin)──┐
                                            ▼
 Telegram bot (aiogram 3) ──service token──► FastAPI /api/v1 ──► PostgreSQL 16
                                            │        ▲
                                            ▼        │ SSE (Redis pub/sub)
                                       Redis 7 ◄─── Celery worker + beat
                                                     │
                       ┌─────────────── Research pipeline ───────────────┐
                       │ DISCOVERY → NORMALIZATION → DEDUPLICATION →      │
                       │ COMPANY/CONTACT ENRICHMENT → AI ANALYSIS →       │
                       │ LEAD SCORING → PERSIST → NOTIFY                  │
                       └──────────────────────────────────────────────────┘
   Free:     OpenStreetMap · File import (CSV/XLSX) · schema.org/sitemap website parsing · DNS MX email check
   Scraping: Google Maps (headless Chromium) · public Instagram/Facebook/Snapchat/TikTok/LinkedIn pages
   Keyed:    Brave Search · Hunter (Discover/Domain/Verify) · X API · Claude · Manual URLs · Demo
```

* **One backend**: the bot has no database. It calls the API with `X-Service-Token` plus the Telegram user id
  of an *approved* linked account, and gets exactly the same permissions as that user.
* **Deterministic pipeline**: each stage writes `job_events`, counters and a checkpoint on `campaign_runs`.
  Per-lead flags (`enriched/analyzed/scored`) make every step idempotent, so pause/resume and worker restarts
  continue where they stopped. Results are committed incrementally.
* **Provider isolation**: a failing or rate-limited provider is retried with backoff. If it still fails, the
  source is marked failed and the campaign becomes *Partially Completed*. Mock data is never substituted.
* **Grounded AI**: website text is passed as fenced, untrusted data. Every observation must cite evidence
  IDs (E1…), and citations to unknown IDs are stripped. The output separates *observed*, *hypothesis* and *unknown*.
  Structured output uses Claude `messages.parse` with Pydantic schemas.
* **Deterministic scoring** (`scoring_version 1.1.0`): six weighted factors, configurable per workspace.
  AI provides evidence-backed inputs but can't set the score. Map-listing and social-profile observations
  count as evidence, so a business with no website is not scored as if nothing were known about it.

## 2. Implementation status

| Area | Status |
|---|---|
| Auth (argon2, JWT httpOnly cookie, CSRF double-submit, roles owner/admin/analyst/viewer, workspace isolation, audit log, rate limiting) | ✅ working, tested |
| PostgreSQL schema (all 23 tables from the spec + `telegram_link_codes`), Alembic migration `0001` | ✅ |
| Campaign CRUD, start/pause/resume/cancel/retry/duplicate/delete, runs, events, estimate, NL→spec | ✅ tested |
| Celery pipeline with checkpoints, retries/backoff, budget & runtime caps, stalled-run recovery, retention job | ✅ tested |
| Live monitor: SSE (Redis pub/sub) + polling fallback + stall watchdog | ✅ verified in browser |
| Demo provider (fictional `.example` businesses served to the **real** crawler/extractor) | ✅ |
| Brave Search adapter (bilingual query expansion, pagination, 429 handling, normalization) | ✅ unit-tested with mocked API; needs `BRAVE_API_KEY` for live use |
| Hunter (Discover, Domain Search, Email Verifier, Company) | ✅ mocked tests; needs `HUNTER_API_KEY` |
| X API adapter (recent search, tier errors reported honestly) | ✅ mocked tests; needs Basic tier+ |
| Facebook | Pages are enriched by scraping (see below). Keyword *discovery* on Facebook needs login, so it is not offered |
| SSRF-safe crawler (DNS + redirect checks, robots.txt, size/time limits) and contact extraction | ✅ tested |
| Website quality: schema.org JSON-LD (name, phone, email, address, hours, `sameAs` socials) + sitemap.xml page discovery | ✅ tested |
| OpenStreetMap discovery (Nominatim + Overpass, mirror fallback, no key) | ✅ tested + **verified live** |
| File import CSV/XLSX (English or Arabic headers, row validation preview) | ✅ tested |
| Free email domain check (DNS MX; marks dead domains `invalid`, never `verified`) | ✅ tested |
| Google Maps scraping (opt-in `SCRAPING_ENABLED`) | ✅ tested with fake browser + **verified live** |
| Public social profile enrichment (Instagram, Facebook, Snapchat, TikTok, LinkedIn) | ✅ tested; **live**: Instagram & Facebook return data, Snapchat/TikTok/LinkedIn often show a login wall or challenge (recorded as *not accessible*) |
| AI analysis (DeepSeek, Anthropic or OpenAI; `AI_PROVIDER` picks) + rule-based fallback clearly labelled. **DeepSeek verified live** (~$0.01 per lead at the configured price estimate) | ✅ code complete; live Claude calls need `ANTHROPIC_API_KEY` (not exercised in tests) |
| Pitch drafts EN / Gulf Arabic (AI or labelled template), drafts only, opt-out line | ✅ |
| Leads CRM: search, filters, sort, pagination, bulk actions, tags, notes, manual add, edit, suppression | ✅ |
| Exports CSV (UTF-8 BOM) / XLSX + campaign summary sheet / Google Sheets (service account) | ✅ CSV/XLSX tested; Sheets needs credentials |
| Dashboard (live DB metrics, charts), wizard, monitor, lead detail (10 sections), settings, suppression | ✅ |
| EN/AR localisation with RTL, light/dark theme, brand theme | ✅ |
| Telegram bot: menu, FSM wizard, linking with admin approval, progress edits, completion summary, CSV | ✅ tested with recorded Bot API; live use needs `TELEGRAM_BOT_TOKEN` |
| Docker Compose (postgres, redis, migrate, api, worker, beat, frontend, telegram, login-browser) + prod nginx overlay | ✅ |

## 3. File structure

```text
ai-lead-hunter/
├── backend/                 FastAPI + SQLAlchemy 2 + Celery
│   ├── app/api/v1/          auth, campaigns (+SSE), leads/contacts/suppression, dashboard, exports, providers, telegram, settings
│   ├── app/core/            config, db, security, crypto (Fernet), safe_http (SSRF), logging, errors
│   ├── app/models/          ORM models (identity, campaign, business, ops)
│   ├── app/research/        pipeline.py, providers/, enrichment/, analysis/, scoring/, scraping/, catalog.py
│   ├── app/services/        campaigns, leads, exports, providers, suppression, events, notifications
│   ├── app/workers/         celery_app.py, tasks.py
│   ├── migrations/          Alembic
│   └── tests/               100 tests
├── frontend/                Next.js 16 App Router + Tailwind 4 + TanStack Query + RHF/Zod + Recharts
│   ├── src/app/             routes: /login, /, /campaigns, /campaigns/new, /campaigns/[id], /leads, /leads/[id], /settings, /suppression
│   ├── src/features/        dashboard, campaigns (wizard, monitor), leads, settings, suppression, auth
│   ├── src/components/      ui primitives (shadcn-style on Radix), charts, layout
│   ├── src/__tests__/       Vitest component & validation tests
│   └── e2e/                 Playwright journeys
├── telegram/                aiogram 3 bot (bot/handlers, keyboards, states, services) + tests
├── infrastructure/          Dockerfiles, nginx.conf
├── scripts/bootstrap.sh     first-run helper
├── docker-compose.yml       full stack;  docker-compose.prod.yml  nginx overlay
└── .env.example
```

## 4. Environment variables

All variables are documented in [`.env.example`](.env.example). The key ones:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | JWT signing + default secret-encryption key derivation (**required**, long random) |
| `ENCRYPTION_KEY` | optional dedicated Fernet key for DB-stored provider secrets |
| `DEMO_MODE` | `true` enables the fictional demo provider |
| `AI_PROVIDER` | preferred AI provider: `deepseek`, `anthropic` or `openai` (others with a key act as fallbacks) |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` | DeepSeek analysis/pitches (default `deepseek-flash`; `deepseek-v4-pro` also available). JSON output is validated against the schema with one corrective retry |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Claude analysis/pitches (default `claude-opus-5-5`) |
| `BRAVE_API_KEY`, `HUNTER_API_KEY`, `X_BEARER_TOKEN` | discovery/enrichment providers |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_SERVICE_TOKEN` | bot token; shared bot↔API secret |
| `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET` | production webhook mode |
| `GOOGLE_SHEETS_CREDENTIALS_JSON`, `N8N_WEBHOOK_URL`, `CRM_WEBHOOK_URL` | optional integrations |
| `SCRAPING_ENABLED` | `true` turns on Google Maps discovery and social profile enrichment (headless Chromium in the worker image) |
| `SCRAPER_MAX_PLACES_PER_CAMPAIGN`, `SCRAPER_DELAY_MIN/MAX`, `SOCIAL_ENRICHMENT_ENABLED` | scraping limits and pacing |
| `OSM_CONTACT_EMAIL`, `OSM_CITY_RADIUS_KM`, `OSM_OVERPASS_URL` | OpenStreetMap: optional real contact for the User-Agent, search radius, comma-separated Overpass mirrors |
| `EMAIL_MX_CHECK` | free DNS check of email domains (default on) |
| `COOKIE_SECURE`, `FRONTEND_URL` | set `true` / your https URL in production |

Provider keys can also be entered in **Settings → Integrations**. They are stored Fernet-encrypted and are
never returned to the browser; only masked values are shown. Environment values take precedence.

## 5. Local startup

```bash
cp .env.example .env            # set SECRET_KEY and TELEGRAM_SERVICE_TOKEN to random strings
docker compose up -d --build    # postgres, redis, migrate, api, worker, beat, frontend, telegram
docker compose exec api python -m app.cli create-admin --email admin@example.com --workspace "My Agency"
# → http://localhost:3000   (API docs: http://localhost:8000/api/docs)
```

Or run `./scripts/bootstrap.sh admin@example.com "My Agency"`.

Without Docker (development):

```bash
cd backend && uv venv && uv pip install -e ".[dev]"
export DATABASE_URL=postgresql+asyncpg://... REDIS_URL=redis://localhost:6379/0
alembic upgrade head && uvicorn app.main:app --reload
celery -A app.workers.celery_app worker -Q research,default -l info   # add --pool=solo on Windows
cd frontend && npm install && npm run dev                              # proxies /api to :8000
cd telegram && pip install -e . && python main.py
```

## 6. Database migrations

```bash
docker compose run --rm migrate                         # alembic upgrade head (runs automatically on `up`)
docker compose exec api alembic revision --autogenerate -m "describe change"
docker compose exec api alembic downgrade -1
```

## 7. Telegram bot

1. Create a bot with **@BotFather**, then put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_USERNAME` in `.env`.
2. Set `TELEGRAM_SERVICE_TOKEN` (shared with the API), then run `docker compose up -d telegram`. Local mode uses long polling.
3. In the dashboard, go to **Settings → Telegram → Generate linking code**, then send `/link CODE` to the bot within 10 minutes.
   Owners and admins are approved automatically. Other users appear as *pending* until an admin approves them.
4. **Production webhook:** set `TELEGRAM_WEBHOOK_URL=https://your-domain` and `TELEGRAM_WEBHOOK_SECRET`.
   nginx routes `/telegram/webhook` to the bot, which checks the `X-Telegram-Bot-Api-Secret-Token` header.

The bot only works in private chats. Commands are `/start /new /campaigns /top /link /lang /help /cancel`.
Progress is shown by editing one status message, at most once every 10s. The completion summary
(target, discovered, qualified, emails, verified, high-priority) is built from campaign records.

## 8. Your first campaign

1. Sign in and click **New campaign**.
2. Pick the geography (e.g. Saudi Arabia / Riyadh).
3. Pick the targeting (`dental_clinics`, or describe your prospect and click **Convert with AI**).
4. Pick sources. With no keys you can use **Google Maps (direct)**, **OpenStreetMap** or **File import**.
   **Demo fixtures** gives fictional data. Keyed providers show *Requires API key* until configured.
5. Choose settings, then **Start campaign**. The live monitor streams stages, counts, warnings and cost.
6. Open a lead to see contacts with provenance, evidence, analysis, score breakdown and pitch drafts.
7. Export CSV/XLSX from the campaign or the Leads page.

CLI alternative: `docker compose exec api python -m app.cli run-demo --email admin@example.com`.

## 9. Tests (actual results from this build)

| Suite | Command | Result |
|---|---|---|
| Backend (PostgreSQL 16) | `TEST_DATABASE_URL=postgresql+asyncpg://… pytest` | **100 passed** |
| Backend (SQLite fallback) | `pytest` | **100 passed** |
| Telegram bot | `cd telegram && pytest` | **8 passed** |
| Frontend unit/component | `cd frontend && npm test` | **16 passed** |
| Frontend E2E (Playwright, against the running stack) | `cd frontend && npm run test:e2e` | **2 passed** |
| Type-check / lint | `tsc --noEmit`, `eslint`, `ruff check` | clean |

Coverage includes: dashboard campaign creation, demo discovery, persistence, enrichment, analysis grounding,
scoring, dashboard results, CSV/XLSX export, Telegram campaign creation and completion notification,
missing credentials, rate limits (simulated 429 → retries → failed → retry run), duplicates (in-batch,
cross-campaign, exclude option), failed and partial runs, pause/resume (including mid-run checkpoint resume),
cancellation, unauthorized and CSRF-less requests, workspace isolation, viewer restrictions, businesses with
no contacts, suppression across campaigns, SSRF and robots.txt, OSM/import/JSON-LD/sitemap/MX, Google Maps and
social-profile parsers, scraper block handling, and an end-to-end real campaign (OSM + import + social enrichment).

Tests need Redis reachable (`TEST_REDIS_URL`), otherwise every event publish waits for a connection timeout.

### Direct scraping: what to expect

* **Limits built in**: no account login, no captcha solving, no proxy rotation, one browser page at a time
  with a 2-5 s pause, and a page budget per run. If Google or a platform serves a challenge, that source
  stops with a clear message, places already collected are kept, and the campaign ends *Partially Completed*.
* **Google Maps** (live-verified): name, category, rating, phone, website, address, hours, coordinates.
  Review *counts* are hidden from logged-out visitors, so they stay empty.
* **Social profiles** (live-verified): Instagram and Facebook page data (followers, posts, bio and any
  phone/email in it) is read. Snapchat, TikTok and LinkedIn often serve a login wall or bot challenge; that is
  recorded as *not accessible*, never guessed.
* **Linked accounts (optional)**: for platforms that hide data from logged-out visitors (LinkedIn, TikTok...),
  link a *secondary* account from **Settings → Integrations → Linked accounts → Connect**. A real browser
  (the `login-browser` container: Chromium on a TigerVNC display streamed through noVNC, bound to
  `127.0.0.1:6080`, one-time VNC password per login) opens inside the dashboard. You log in by hand (2FA works)
  and click **I'm logged in, save**. Only cookies are stored, Fernet-encrypted, and the password is never seen.
  A save is refused until the platform's login cookie exists (e.g. LinkedIn `li_at`). The CLI alternative is
  `backend/.venv/Scripts/python scripts/connect_session.py linkedin`.
  Daily page caps per platform (LinkedIn 30, TikTok/Snapchat 60, Instagram/Facebook 80) are counted in Redis, and
  visits past the cap continue logged out. A visit that lands on a login or checkpoint page marks the session
  *expired* and stops using it. Live-verified on LinkedIn: company followers and employee range.
  The platforms can still restrict the linked account, which is why it should not be your personal one.
  In production, put noVNC behind authenticated HTTPS instead of exposing port 6080.
* **Maintenance**: platform markup changes break selectors. Every selector lives in
  `backend/app/research/scraping/selectors.py`, and the parsers are pure functions with tests.
* **Risk**: scraping goes against these platforms' terms of service and can get the server IP blocked for a while.
  It is off unless `SCRAPING_ENABLED=true`.

## 10. Known limitations & next priorities

* **Not exercised against live third-party APIs** in this environment (no keys were provided). Brave,
  Hunter, X, Claude, Google Sheets and Telegram are implemented per their official docs and tested with
  mocked HTTP. Validate each one with **Test connection** after adding keys.
* **OpenStreetMap coverage varies**: live, Riyadh dentists returned 15 places (2 with a website). It is free
  but thinner than Google Maps for Gulf cities. Use it alongside Maps.
* **Neue Montreal** is licensed and not bundled. Inter is used until the font files are added.
* Phone-only deduplication (no domain) scans the workspace's domain-less businesses. Add a JSONB index if that set grows large.
* The Telegram language switch (`/lang`) is held in memory per bot process.
* Google Sheets export creates a new spreadsheet each time (no incremental sync yet).
* Next priorities: live provider validation, CRM/n8n bidirectional sync, scheduled recurring campaigns,
  per-provider monthly budget enforcement (usage is tracked; budgets are currently per campaign), OpenTelemetry tracing.

**Compliance**: public availability does not by itself authorize collection or marketing use of personal
data. The platform prefers role-based company channels, flags personal mailboxes, labels provenance and
verification honestly, enforces a cross-campaign suppression list, and only generates drafts.
It does not send messages. Before any outreach, confirm a lawful basis under the applicable rules
(e.g. Saudi PDPL, UAE PDPL, Egypt PDPL) and each platform's terms.
