# Technology Stack

The capstone is two deployments in one workspace: a Python/FastAPI backend and a Next.js/React frontend. Each is a separate git repo and separate CI pipeline.

## Core Sections (Required)

### 1) Runtime Summary

| Area | Value | Evidence |
|------|-------|----------|
| Primary language (backend) | Python >= 3.10 (dev machine 3.13; requirements compiled for 3.11; Render runtime 3.14 observed in git history) | `task-buddy-backend/pyproject.toml` (`requires-python = ">=3.10"`), `task-buddy-backend/requirements.txt` (uv-compiled, `--python-version 3.11`) |
| Primary language (frontend) | TypeScript ~5.9 (React 19) | `task-buddy-frontend/package.json` |
| Runtime + version (backend) | FastAPI (ASGI via uvicorn) | `task-buddy-backend/pyproject.toml` `[tool.fastapi] entrypoint = "app.main:app"` |
| Runtime + version (frontend) | Node >= 20.9; Next.js 16 (webpack builds, app router) | `task-buddy-frontend/package.json` (`engines`, `next ^16.3.0`, `build: next build --webpack`) |
| Package manager (backend) | uv (requirements.txt is `uv pip compile` output); pyproject setuptools build | `task-buddy-backend/requirements.txt` header, `task-buddy-backend/pyproject.toml` |
| Package manager (frontend) | npm (package-lock v3) | `task-buddy-frontend/package-lock.json` |
| Module/build system (frontend) | Next.js app router + Vite-era `src/` SPA shell (`app/[slug]/spa.tsx`) | `task-buddy-frontend/app/[slug]/spa.tsx`, `task-buddy-frontend/package.json` |

### 2) Production Frameworks and Dependencies

**Backend** (`task-buddy-backend/pyproject.toml`):

| Dependency | Version | Role in system | Evidence |
|------------|---------|----------------|----------|
| fastapi | >=0.100 | HTTP framework; all `/api/v1` routers | pyproject.toml, `app/main.py` |
| uvicorn[standard] | >=0.23 | ASGI server | pyproject.toml |
| sqlalchemy | >=2.0 | Async ORM (asyncpg/aiosqlite drivers) | pyproject.toml, `app/database.py` |
| alembic | >=1.12 | DB migrations (15 versions) | pyproject.toml, `alembic/versions/` |
| pydantic v2 + pydantic-settings | >=2.0 | Schemas (`app/schemas/`) + config (`app/config.py`) | pyproject.toml |
| asyncpg / psycopg2-binary / aiosqlite | — | Postgres async driver / Alembic sync driver / dev SQLite | pyproject.toml |
| PyJWT + passlib[argon2] + argon2-cffi | — | JWT auth (HS256 + ES256 realtime tokens) + Argon2 password hashing | pyproject.toml, `app/security.py` |
| slowapi | >=0.1.9 | Rate limiting (memory default; Redis optional) | pyproject.toml, `app/limiter.py`, `app/config.py` |
| redis | >=5.0 | Cache + optional rate-limit storage (bounded pools after audit #30-era fix) | pyproject.toml, `app/config.py` |
| openai | >=1.30 | SDK used for **all three providers** (OpenAI API, Groq via OpenAI-compatible `base_url`, Jina embeddings via OpenAI-compatible API) | `app/knowledge/assistant.py`, `app/knowledge/embeddings.py` |
| nltk | >=3.10 | Porter stemmer + stopwords for BM25 tokenization | pyproject.toml, `app/knowledge/retrieval/tokenize.py` |
| numpy | >=2.0,<2.5 | Vector math for embeddings/cosine/RRF | pyproject.toml, `app/knowledge/retrieval/` |
| sentence-transformers | >=5.6 | Local embedder (dev only; `EMBEDDING_PROVIDER=local`) | pyproject.toml, `app/knowledge/embeddings.py` |
| pywebpush | >=2.0 | Web Push notifications (VAPID) | pyproject.toml, `app/models/notification.py` |
| b2sdk | >=2.5 | Backblaze B2 (file storage; `app/libs/b2/`) | pyproject.toml |
| httpx | >=0.24 | HTTP client | pyproject.toml |
| sentry-sdk | >=1.30 | Error monitoring | pyproject.toml, `app/config.py` |
| python-json-logger + asgi-correlation-id | — | Structured JSON logging + correlation IDs | pyproject.toml, `app/logging_conf.py` |

> Drift note: `celery` remains mentioned in `app/main.py` comments only — it was dropped (commit `ee84a2f`); embeddings use the `pgvector` package's `Vector` type against Supabase's built-in pgvector extension.

**Frontend** (`task-buddy-frontend/package.json`):

| Dependency | Version | Role in system | Evidence |
|------------|---------|----------------|----------|
| next | ^16.3.0 | App-router host; SPA shell at `app/[slug]/spa.tsx`; API proxy functions | package.json, `app/` |
| react / react-dom | ^19.2 | UI runtime | package.json |
| @tanstack/react-query (+persist, async-storage persister) | ^5.100 | Server-state cache + offline persistence | package.json, `src/lib/query-client.ts` |
| zustand | ^5.0 | Lightweight client state | package.json |
| axios | ^1.16 | HTTP client to backend | package.json, `src/lib/api.ts` |
| @supabase/supabase-js | ^2.112 | Supabase Realtime subscription (sync push channel) | package.json, `src/lib/realtime-client.ts` |
| @serwist/next | ^9.5 | Service worker / PWA | package.json, `public/sw.js`, `src/components/sw-registration.tsx` |
| idb-keyval | ^6.2 | IndexedDB for offline sync queue | package.json, `src/lib/sync-queue.ts` |
| @dnd-kit/* | ^6/^10 | Drag-and-drop sidebar/task reorder | package.json, `src/components/sidebar/` |
| framer-motion | ^12.38 | Animations | package.json |
| radix-ui + shadcn + tailwindcss 4 | — | Component system + styling (CVA, clsx, tailwind-merge, tw-animate-css) | package.json, `src/components/ui/` |
| date-fns + react-datepicker/day-picker/time-picker/clock | — | Date/deadline/time pickers | package.json |

### 3) Development Toolchain

| Tool | Purpose | Evidence |
|------|---------|----------|
| pytest + pytest-asyncio (asyncio_mode=auto) + pytest-cov + pytest-mock | Backend tests (49 test files, 347 tests) | `task-buddy-backend/pyproject.toml` `[tool.pytest.ini_options]` |
| ruff | Backend lint + format gate (CI enforces `ruff check` + `ruff format`) | git log `ee6aa75`/`046ed5e`; CI `python-app.yml` |
| mypy | Backend typecheck gate (CI runs `mypy app`) | `task-buddy-backend/.github/workflows/python-app.yml` (typecheck job) |
| black / isort | Backend dev tooling (declared in pyproject dev extras; ruff is the enforced format/lint gate) | `task-buddy-backend/pyproject.toml` |
| vitest 4 + @testing-library/react + jsdom | Frontend unit tests (13 test files) | `task-buddy-frontend/package.json` |
| @playwright/test | Frontend E2E (8 specs in `tests/`) | `task-buddy-frontend/package.json`, `tests/*.spec.ts` |
| eslint 9 + typescript-eslint + prettier | Frontend lint + format (`format:check` gate in CI) | `task-buddy-frontend/package.json`, `eslint.config.js`, `.prettierrc` |
| uv | Backend dependency lock (requirements.txt) | `task-buddy-backend/requirements.txt` |

### 4) Key Commands

```bash
# backend
uv pip install -r requirements.txt        # install
uvicorn app.main:app --reload             # dev server
pytest                                    # run all tests
ruff check . && ruff format --check .     # lint + format gates

# frontend
npm install                                # install
npm run dev                                # dev server (next dev --webpack)
npm run test:ci                            # vitest run
npm run lint && npm run format:check       # lint + format gates
npm run typecheck                          # tsc --noEmit
npm run build                              # next build --webpack
npm run test:e2e                           # playwright test
```

### 5) Environment and Config

- Config sources: `task-buddy-backend/app/config.py` (pydantic-settings, env-driven; `ProdConfig` switches embedding/LLM providers via `APP_ENV`); `task-buddy-backend/.env.example`; `task-buddy-frontend/.env.example` (`VITE_API_BASE_URL` — Vite-era name; current builds use Next API proxy + `NEXT_PUBLIC_*` vars per CI workflow).
- Required env vars (backend): `DATABASE_URL`, `SECRET_KEY`, `APP_ENV` (dev/production), `JINA_API_KEY` + `EMBEDDING_PROVIDER=jina`, `GROQ_API_KEY` + `LLM_PROVIDER=groq` (prod); optional `OPENAI_API_KEY`, `REDIS_URL`, `SENTRY_DSN`, Brevo `DEV_MAIL_*`, B2 `TEST_B2_*`, VAPID keys. See `.env.example` for the full list.
- Required env vars (frontend): `BACKEND_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (CI workflow references).
- Deployment/runtime constraints: Render free tier is 512MB RAM — the ~470MB local sentence-transformers model OOMs it, which is why prod uses API embeddings (Jina). DB pool capped under Supabase pooler limit (~15 clients). Rate-limit storage defaults to in-process memory because Render runs a single instance.

### 6) Evidence

- `task-buddy-backend/pyproject.toml`
- `task-buddy-backend/requirements.txt`
- `task-buddy-backend/.env.example`
- `task-buddy-backend/app/config.py`
- `task-buddy-frontend/package.json`
- `task-buddy-frontend/.env.example`
- `docs/codebase/.codebase-scan.txt`
