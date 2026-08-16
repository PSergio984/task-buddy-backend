# Codebase Structure

Two sibling repos compose the capstone. Paths below are relative to the workspace root (`D:\Github\task-buddy`).

## Core Sections (Required)

### 1) Top-Level Map

**Workspace root**

| Path | Purpose | Evidence |
|------|---------|----------|
| `task-buddy-backend/` | FastAPI backend repo (its own git repo + CI) | `task-buddy-backend/pyproject.toml` |
| `task-buddy-frontend/` | Next.js frontend repo (its own git repo + CI) | `task-buddy-frontend/package.json` |
| `docs/codebase/` | This documentation set | — |
| `.scratch/`, `graphify-out/`, `.graphify_python/` | Agent scratch/analysis artifacts (not product code) | — |

**Backend (`task-buddy-backend/`)**

| Path | Purpose | Evidence |
|------|---------|----------|
| `app/` | Application package (see Module Boundaries) | `app/main.py` |
| `alembic/versions/` | 16 migrations (auth, projects, tasks, sync fields, notifications, knowledge tables + pgvector, deadline_type/estimated_effort, plan answers, embedding dim switches, pre-dogfood hardening) | `alembic/versions/` |
| `tests/` | 49 pytest files (`tests/routers/` for API tests) | `tests/` |
| `pyproject.toml`, `requirements.txt`, `uv.lock` | Dependency manifests (note drift: celery/pgvector listed but unused) | `pyproject.toml` |
| `Dockerfile`, `docker-compose.yml` | Container dev env | scan: CONTAINERS & ORCHESTRATION |
| `.github/workflows/` | `python-app.yml` (alembic revision-chain check, ruff lint + format, mypy typecheck, pytest, docker build), `sonarcloud.yml`, `sonar-secrets.yml` | `.github/workflows/` |
| `.planning/` | GSD planning: PROJECT.md, REQUIREMENTS.md, ROADMAP.md, STATE.md, DOGFOOD.md, `phases/07-ai-knowledge-layer/`, `phases/08-memory-rag-over-task-history/`, `phases/09-planner-what-should-i-do-next-soft-deadlines/` | `.planning/` |
| `docs/` | MASTER_SPEC.md, api_endpoints.md, database_schema.md, system_flowchart.md, etc. (historical spec docs) | `docs/` |

**Frontend (`task-buddy-frontend/`)**

| Path | Purpose | Evidence |
|------|---------|----------|
| `app/` | Next.js app router: `/login`, `/register`, `/forgot-password`, `/reset-password/[token]`, `/verify-email`, `/[slug]` (SPA shell + page) | `app/*/page.tsx` |
| `src/` | SPA source: `components/` (incl. `task-drawer/KnowledgeSection.tsx` — notes + "what do I need" + thumbs), `contexts/` (Auth, Filter, Settings, Sync, ProtectedRoute), `hooks/` (useTasks, useKnowledgeNotes, useTaskDrawer*, useNotifications), `lib/` (api, sync-queue/flush/delta/enqueue, realtime-client, query-client), `views/` (TasksPage, TaskDetailPage, DashboardDemo, auth pages, LandingPage, AuditLogsPage, ProfilePage), `test/setup.ts` | `src/` |
| `tests/` | 8 Playwright E2E specs | `tests/*.spec.ts` |
| `.github/workflows/` | `ci.yml` (lint, format:check, typecheck, vitest, build) + `sonar-secrets.yml` | `.github/workflows/ci.yml` |
| `vercel.json` | Vercel functions config (proxy to backend, `app/` prefix pattern) | git log `ecb1f0d` |

### 2) Entry Points

- Backend runtime entry: `app/main.py` → `app:app` FastAPI instance; routers registered at `app/main.py:163-173`; lifespan wires embeddings/index startup.
- Frontend runtime entry: Next.js `app/layout.tsx` → route pages; the app shell is `app/[slug]/spa.tsx` (SPA) + `src/App.tsx`.
- Background work: in-process (celery removed, commit `ee84a2f`) — `app/tasks.py` + FastAPI lifespan tasks (reminder loop, memory backfill sweep).
- CI entry: `.github/workflows/python-app.yml` (backend), `.github/workflows/ci.yml` (frontend).

### 3) Module Boundaries

**Backend** (`app/`)

| Boundary | What belongs here | What must not be here |
|----------|-------------------|------------------------|
| `app/api/routers/` | HTTP endpoints only; dependency injection, rate limits, auth deps, error mapping (503 for AI-not-configured, 429 budget) | Business logic, DB queries |
| `app/crud/` | Async SQLAlchemy data-access functions | HTTP concerns, LLM calls |
| `app/schemas/` | Pydantic request/response/enum models | Logic |
| `app/models/` | SQLAlchemy ORM models (`tbl_*` tables) | Migrations (belong in alembic) |
| `app/knowledge/` | RAG: `assistant.py` (generation+judge), `embeddings.py` (provider switch), `ingest.py`, `retrieval/` (bm25, semantic, hybrid RRF, tokenize), `sources/` (base, note, history), `evaluation.py`, `budget.py`, `cost.py`, `records.py`, `history.py` | API shapes |
| `app/planner/` | `service.py` (LLM-judged plan), `connector.py` (SyntheticCalendarConnector), `deadline.py` (soft-deadline proposal) | Retrieval internals |
| `app/sync/` | Offline-sync protocol (LWW merge: `lww.py`) + `app/api/routers/sync.py` | Frontend queue logic |
| `app/middleware/` | CSRF (`csrf.py`), idempotency (`idempotency.py`) | — |
| `app/libs/` | b2 storage, cache, email templates, supabase signing, audit | — |
| `app/internal/` | Admin/audit automation endpoints | — |

**Frontend** (`src/`)

| Boundary | What belongs here | What must not be here |
|----------|-------------------|------------------------|
| `src/lib/` | Pure logic: api client, sync queue/flush/delta/enqueue, realtime client, query client, utils | JSX |
| `src/hooks/` | Data-fetching and state hooks (useTasks, useTaskDrawer*, useKnowledgeNotes, useNotifications) | Rendering |
| `src/contexts/` | Cross-cutting providers: Auth, Settings, Filter, SyncContext (offline queue orchestration), ProtectedRoute | Data fetching |
| `src/components/` | UI components; `components/ui/` = shadcn primitives; `components/task-drawer/` = drawer + KnowledgeSection | Business logic |
| `src/views/` | Page-level compositions | — |

### 4) Naming and Organization Rules

- Backend: snake_case files/modules; routers named after domain (`task.py`, `knowledge.py`); tables `tbl_<plural>` (`tbl_tasks`, `tbl_knowledge_chunks`); enums in `app/schemas/enums.py`.
- Frontend: PascalCase component files (`TaskDetailPage.tsx`), camelCase hooks (`useTasks.ts`), kebab-case shadcn UI files (`task-card.tsx`). Tests co-located as `*.test.ts(x)` in `src/`, E2E in `tests/`.
- Import style backend: absolute `from app.xxx import yyy`; frontend: relative imports within `src/`.

### 5) Evidence

- `task-buddy-backend/app/main.py` (router registration lines 163-173)
- `task-buddy-backend/app/` tree (scan output)
- `task-buddy-frontend/app/` + `src/` tree (scan output)
- `docs/codebase/.codebase-scan.txt`
