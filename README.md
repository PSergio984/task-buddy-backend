# Task Buddy Backend

FastAPI backend for **Task Buddy — AI Task Manager (Memory · Knowledge · Planner)** — hybrid retrieval (BM25 `k1=1.5/b=0.75` Porter + `jina-embeddings-v3` 1024-dim + RRF `k=60`), grounded Knowledge answers with citations + LLM-as-judge, Memory over completed-task history, and Planner Tonight/Tomorrow/Later. Supabase Postgres (pgvector), offline-first sync, deployed on **Render**.

> Monorepo front door is [`../README.md`](../README.md) (live demo, architecture mermaid, full run-it, walkthrough, eval, rubric). This file is the deep backend reference. Keep it in sync with `../docs/codebase/` (STACK, STRUCTURE, ARCHITECTURE, TESTING, etc.).

## Features (capstone surfaces)

- 🚀 FastAPI + Uvicorn + SQLAlchemy 2 async + Alembic + Pydantic v2 (Python `>=3.10`, compiled `3.11`, `mypy 3.12` `pyproject.toml`)
- 🤖 **Knowledge** `POST /api/v1/tasks/{id}/knowledge/ask` — hybrid RRF over `tbl_knowledge_chunks`, citations + judge `RELEVANT/PARTLY/NON` `app/knowledge/assistant.py`
- 🧠 **Memory** `POST /api/v1/tasks/{id}/memory/similar` — history RAG top-5 + `estimated_effort_minutes` `app/knowledge/sources/history.py`
- 📅 **Planner** `POST /api/v1/plan` — synthetic connector + LLM-judged scoring `app/planner/service.py` → `{tonight, tomorrow, later}` + soft deadlines `app/planner/deadline.py`
- 🧩 **Breakdown** `POST /api/v1/breakdown` — `BREAKDOWN_MODEL=openai/gpt-oss-120b` `app/config.py:179` (strict `json_schema`), 10/min
- 🎙️ **Voice** `POST /api/v1/voice/plan` — `whisper-large-v3-turbo` → plan
- 🔄 **Sync** `POST /api/v1/sync` — offline delta flush, LWW `app/sync/lww.py` + Supabase Realtime push `app/api/routers/realtime.py` (SSE `task-buddy-backend/app/libs/broadcaster.py` dead code per `docs/codebase/CONCERNS.md`)
- 🧪 347 tests / 49 files `tests/` (`pytest`), golden `tests/fixtures/golden_knowledge.json` + gate `hybrid ≥ bm25 AND ≥ semantic`
- 🔐 JWT cookie + CSRF + idempotency + slowapi rate limits + per-user LLM budget `app/knowledge/budget.py`
- 📧 In-process `app/tasks.py` lifespan (no Celery `ee84a2f`) — emails (Brevo), pushes (VAPID), 60s reminder sweep

## Tech stack

| Layer | Choice | Why | Evidence |
|-------|--------|-----|----------|
| Backend | FastAPI + Uvicorn, SQLAlchemy 2 async, Alembic, Pydantic v2 | Existing foundation (Phases 1-6); async for LLM/RAG | `app/main.py:163-173` |
| DB | Supabase Postgres `Vector(1024)` prod (`384` dev `MiniLM-L12-v2`) | Managed, pooler cap ~15, Realtime doubles as push | `app/config.py:125-129` + `docs/codebase/PRESENTATION.md` |
| LLM | Groq `llama-3.3-70b-versatile` (fallback `gpt-4o-mini`), breakdown `openai/gpt-oss-120b` | Zero-cost, OpenAI-compatible | `app/config.py:151-153,179` |
| Embeddings | Jina `jina-embeddings-v3` 1024-dim multilingual | Local `MiniLM` OOMs Render 512MB; Groq has no embeddings | `app/config.py:136-138` + `app/knowledge/embeddings.py` |
| Search | BM25 `k1=1.5/b=0.75` Porter + dense cosine + RRF `k=60` deep `limit×500` | Hybrid must beat singles on `precision@3`/`F1@5` | `app/knowledge/retrieval/{bm25,semantic,hybrid}.py` |
| Cache | Redis bounded pools, in-memory limiter fallback | Free-tier hygiene | `app/config.py:59-64` + `app/libs/cache.py` |
| Hosting | Render + Supabase + Redis | `start.sh` auto-migrates `alembic upgrade head` | `docker-compose.yml` + `start.sh` |
| Observability | Sentry `app/logging_conf.py` + audit `tbl_audit_logs` + budget | No Prometheus — see `../README.md` Monitoring | `docs/codebase/INTEGRATIONS.md` |

## Quick start

### 🐳 Docker Compose (recommended)

```bash
docker compose up --build  # from task-buddy-backend/
# App http://localhost:8000 (./start.sh --reload auto-migrates), Postgres + Redis
# Verify: curl http://localhost:8000/health && open http://localhost:8000/docs
```

### 🐍 Local dev

Prereqs: Python `3.11` (`>=3.10` declared `pyproject.toml:8` + `requirements.txt:1` `uv pip compile --python-version 3.11`, Docker `python:3.11-slim` `Dockerfile:1`, CI `python: "3.11"` `.github/workflows/python-app.yml`), `uv` (`pyproject.toml`) or `pip`.

```bash
uv sync  # or: pip install -r requirements.txt
cp .env.example .env  # set DATABASE_URL, GROQ_API_KEY, JINA_API_KEY (or OPENAI_API_KEY fallback), REDIS_URL, SENTRY_DSN, VAPID_*, BREVO_*, NEXT_PUBLIC_SUPABASE_URL — see app/config.py
alembic upgrade head  # on Supabase or local Postgres
uv run uvicorn app.main:app --reload  # or: ./start.sh --reload
# Docs: http://localhost:8000/docs  ReDoc: http://localhost:8000/redoc
```

Background work (emails/pushes/reminders/memory backfill) runs inside this process (`app/tasks.py` lifespan).

## Data flow (snippet — full mermaid in `../README.md`)

```text
Next.js SPA (IndexedDB queue) ── POST /api/v1/sync LWW ──┐
                                                        ▼
FastAPI /api/v1/* (13 routers ~58 routes app/main.py:165-177) ── Supabase Postgres tbl_* + pgvector
        │  RAG pipeline Source→chunk→embed→index→retrieve→generate→judge (app/knowledge/)
        └─ Planner synthetic connector + LLM-judged scoring (app/planner/service.py)
```

RAG serves **Knowledge** (notes) + **Memory** (history), *not* live `tbl_tasks` (state vs corpus `docs/codebase/PRESENTATION.md: RAG boundary`). Retrieval is per-user `UserKnowledgeIndex` (in-memory, content-hash, recomputed per instance `docs/codebase/CONCERNS.md`).

## Endpoints (grouped — auth JWT cookie + CSRF, `10/min` where `app/config.py` `RATE_LIMIT_*`)

All under `app/main.py:163-177` (`/api/v1/*`, 13 routers, ~58 routes). See `../README.md` for the grouped table with Method|Path|Auth|Rate limit|Description.

Core: `POST /api/v1/users/register`, `POST /api/v1/users/login`, `GET /api/v1/tasks/`, `POST /api/v1/tasks/`, `PUT /api/v1/tasks/{id}`, `POST /api/v1/tasks/{id}/knowledge/ask` + `feedback`, `POST /api/v1/tasks/{id}/memory/similar`, `POST /api/v1/plan`, `POST /api/v1/breakdown`, `POST /api/v1/voice/plan`, `POST /api/v1/sync` (LWW), plus projects/tags/subtasks/notifications/realtime/audit/stats (`docs/codebase/ARCHITECTURE.md`).

Swagger: `http://localhost:8000/docs`

## Retrieval method (CEIT parity)

**Hybrid:** BM25 (`k1=1.5/b=0.75`, Laplace IDF, `lowercase→strip punct→stopword drop→Porter` `nltk` `app/knowledge/retrieval/tokenize.py`) + dense cosine (L2-normalized `jina-embeddings-v3` 1024 / `MiniLM-L12-v2` 384, best-per-doc `app/knowledge/retrieval/semantic.py`) → RRF `Σ 1/(60+rank)` `k=60` `limit×500` `app/knowledge/retrieval/hybrid.py`. Gate: hybrid must beat both singles on `precision@3`/`F1@5` (`docs/codebase/PRESENTATION.md §5`, `tests/test_evaluation.py`).

No query rewriting, no rerank, no catalog-code pin (CEIT extras) — hybrid + judge is the extra; token handling is daily budget `app/knowledge/budget.py` (`CONTEXT.md: Reservation/Reconciliation/Refund`).

## Testing & evaluation

```bash
pytest                      # 347/49 (per 2026-08-16 scan, docs/codebase/TESTING.md)
pytest tests/test_evaluation.py -v  # retrieval gate — 3-row P@k TODO until re-run (do not copy CEIT 0.4545)
pytest tests/test_knowledge_assistant.py -v  # judge RELEVANT/PARTLY/NON + LLMCallRecord
pytest --cov=app            # coverage [TODO]
```

CI: `alembic` single-head, `ruff lint+format`, `mypy` `3.12`, `pytest`, `docker build` (`.github/workflows/python-app.yml`), frontend `ci.yml` separate. Mocking via `get_embedder()` stub (`app/knowledge/embeddings.py` docstring) — suite offline.

Golden: `tests/fixtures/golden_knowledge.json` (`jq length` for N) — CEIT has 27 cases; Task Buddy's N is different.

## Monitoring (actual — no Prometheus)

Sentry `SENTRY_DSN` + `app/logging_conf.py`, audit `tbl_audit_logs` `GET /api/v1/audit/`, per-user daily budget `app/knowledge/budget.py` + slowapi, Realtime `GET /api/v1/realtime/*`, Web Push VAPID, Brevo email `app/tasks.py`. No `GET /metrics` Grafana (scan found none — `docs/codebase/CONCERNS.md`).

## Project structure (backend slice — full monorepo in `../README.md` + `docs/codebase/STRUCTURE.md`)

```text
app/main.py                 # lifespan + routers 163-173
app/config.py               # env (30+ vars)
app/api/routers/            # tasks, knowledge, memory, plan, breakdown, voice, sync, users, projects, notifications, realtime, audit, stats
app/crud/                   # async SQLAlchemy
app/models/                 # Task → SubTask flat app/models/task.py:101
app/knowledge/{sources,retrieval,embeddings,assistant,budget,ingest}.py
app/planner/{service,deadline}.py
app/sync/lww.py
app/tasks.py                # lifespan loops
alembic/versions/           # 19 migrations
tests/                      # 49 files + fixtures/golden_knowledge.json
```

## Docs

- Monorepo front door: [`../README.md`](../README.md) (TOC, live demo, dataset, mermaid, run-it, walkthrough, endpoints, eval, monitoring, rubric, structure, security)
- Deep docs: [`../docs/codebase/`](docs/codebase/) `STACK.md` / `STRUCTURE.md` / `ARCHITECTURE.md` / `CONVENTIONS.md` / `INTEGRATIONS.md` / `TESTING.md` / `CONCERNS.md` / `PRESENTATION.md`
- Planning trail: `.planning/` GSD `07` Knowledge → `08` Memory → `09` Planner + wayfinder `.wayfinder/issues/0024-wayfinder-map-readme-refresh.md`

> Stale claims removed per `../.wayfinder/research/existing-readmes-and-codebase-facts.md`: `VITE_*` → `NEXT_PUBLIC_*`/`BACKEND_URL`, `338KB` unverified → `TODO`, `7` endpoints → `~58` routes, `celery` dead code flagged, `pgvector` drift footnote.

