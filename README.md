# maria-agent

Monorepo for **Maria**, Altria's AI voice agent. First module: **Maria Outbound**, which makes
appointment-setting calls and includes a mini CRM. The design docs are in [`docs/outbound/`](docs/outbound/).
Start with `00-MASTER-PLAN.md` and `02-ARCHITECTURE.md`.

```
apps/
  api/            FastAPI + SQLAlchemy 2 (async) + Alembic — CRM API, dialer, learning, notify, internal
  web/            Vite + React + TS + Tailwind + TanStack Query + React Router — CRM UI at /crm
  voice-worker/   (Phase 2) LiveKit Agents worker
packages/
  playbook-schema/  Python package `playbook_schema` — campaign playbook models
  shared/           Python package `maria_shared` — phone/timezone/cost helpers
scripts/          PowerShell equivalents of every make target (+ future ops scripts)
```

Python is managed as a **uv workspace** (root `pyproject.toml` + `uv.lock`). `apps/api` imports
`maria_shared` and `playbook_schema`, and the future `apps/voice-worker` joins the workspace the same way.

## Prerequisites (Windows)

Run in PowerShell:

```powershell
winget install --id=astral-sh.uv -e          # Python package manager (installs Python 3.11 on demand)
winget install OpenJS.NodeJS.LTS             # Node 22+
winget install Docker.DockerDesktop          # optional — for local Postgres
# optional: winget install GnuWin32.Make  (otherwise use scripts\*.ps1)
```

If script execution is blocked, allow it once for your user:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Setup

```powershell
cd E:\maria-agent
Copy-Item .env.example .env
Copy-Item apps\web\.env.example apps\web\.env
.\scripts\install.ps1        # = make install  (uv sync --all-packages; npm install)
```

### Database

Pick one:

- **Docker:** `docker compose up -d` (or `.\scripts\db-up.ps1`). This runs Postgres 16 + pgvector
  on `localhost:5432` with user, password and db all set to `maria`, which matches the default
  `DATABASE_URL` in `.env.example`.
- **Local Postgres 16:** install pgvector, create a `maria` role and database, and set `DATABASE_URL` in `.env`.
- **Railway Postgres:** paste its connection URL into `DATABASE_URL` in `.env`. Plain `postgresql://`
  URLs are converted to `postgresql+asyncpg://` automatically.

Then apply migrations and seed the first admin:

```powershell
.\scripts\migrate.ps1        # = make migrate
# set SEED_ADMIN_PASSWORD (and JWT_SECRET) in .env first
.\scripts\seed.ps1           # = make seed — admin user, client "YP", placeholder SIP trunk,
                              #   "YP SEO US (test)" campaign (test mode), 2 sample DNC numbers
```

The seed can be run again safely. It never changes an existing admin's password.

## Trying the CRM (Phase 1)

1. `.\scripts\dev.ps1`, open http://localhost:5173/crm, and sign in with `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`.
2. **Campaigns → New campaign** has tabs General, Telephony, Schedule & Pacing, Appointments,
   Compliance and Playbook. A new campaign starts in test mode.
3. **Leads → Import CSV** and pick `scripts\sample_leads.csv`. The wizard walks through upload →
   column mapping → preview → import. The report shows 50 rows: 45 imported, 3 duplicates and
   2 on the DNC list.
4. The leads table shows each lead's timezone and current local time. Click a row to open the lead
   drawer (details, custom fields, timeline). Select rows for bulk requeue, move, mark DNC or export CSV.
5. **Settings** covers users (admin), teams, the DNC list and SIP trunks.

Roles: **admin** can do everything. **manager** can edit campaigns, leads, teams and DNC.
**rep** and **qa** are read-only, except that they can add numbers to the DNC list. Only admins
manage users and SIP trunks, remove DNC entries, or override the playbook eval gate.
The API docs are at http://localhost:8000/docs; all routes are under `/api/v1`.

## Everyday commands

| make | PowerShell | What |
|---|---|---|
| `make dev` | `.\scripts\dev.ps1` | API on http://localhost:8000 (`/health`, `/docs`) + web on http://localhost:5173/crm |
| `make test` | `.\scripts\test.ps1` | pytest (api + packages) and vitest (web) |
| `make lint` | `.\scripts\lint.ps1` | ruff check/format and eslint + tsc |
| `make format` | `.\scripts\format.ps1` | auto-fix Python lint/format |
| `make migrate` | `.\scripts\migrate.ps1` | `alembic upgrade head` |
| `make seed` | `.\scripts\seed.ps1` | idempotent seed (admin, YP client, test campaign) |
| `make install` | `.\scripts\install.ps1` | install all deps |

Tests need a reachable Postgres. They connect to the server's `postgres` database to create and
drop a `<db>_test` database next to `DATABASE_URL`'s. If `TEST_DATABASE_URL` is set, it names the test database instead. That database is dropped and
recreated on every run, so the fixture refuses any name that lacks "test" or matches
`DATABASE_URL`'s database. With a Railway `DATABASE_URL` (database `railway`), tests use
`railway_test` on the same server. The database user needs `CREATEDB`, or use
`TEST_DATABASE_URL`. The pgvector extension must be available on that server.

New migration (one revision per phase, descriptive name):

```powershell
cd apps\api; uv run alembic revision -m "phase1 crm tables"; cd ..\..
```

## Deploying to Railway (not deployed yet)

Each app is its own Railway service, configured as code:

| Service | Root directory | Config file | Notes |
|---|---|---|---|
| `api` | `/` (repo root, needs `packages/`) | `/apps/api/railway.json` | Dockerfile `apps/api/Dockerfile`. `alembic upgrade head` runs as pre-deploy. Set the env vars from `.env.example`. |
| `web` | `/apps/web` | `/apps/web/railway.json` | Set `VITE_API_BASE_URL` (build-time) to the api's public URL. Served by nginx with SPA fallback. |
| `worker-jobs` | (Phase 3) | | Same image as api with a different start command. |

Set `ENV=production` and a random `JWT_SECRET` (32+ characters) on the api service. Outside
development the API refuses to start without one. Secrets live only in Railway variables. SIP trunks and caller IDs are rows in `sip_trunks`, not env vars.

## CI

`.github/workflows/ci.yml` runs on every push and PR. It runs ruff and pytest (against a pgvector
service container) plus an Alembic round-trip, then eslint/tsc, vitest and the Vite build.
