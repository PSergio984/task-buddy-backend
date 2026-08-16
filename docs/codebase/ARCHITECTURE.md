# Architecture

## Core Sections (Required)

### 1) Architectural Style

- Primary style: **layered API (backend) + client-heavy SPA (frontend)**, with a **pluggable RAG pipeline** at the core of the capstone features.
- Why this classification: the backend is a strict FastAPI router → CRUD → model layering (`app/api/routers/`, `app/crud/`, `app/models/`), while the AI layer (`app/knowledge/`) is a self-contained pipeline with a `Source` registry (extract → chunk → embed → index → retrieve → generate) — see `app/knowledge/sources/base.py`, `app/knowledge/ingest.py`.
- Primary constraints (all from `app/config.py` + deploy reality):
  1. Render free tier = 512MB RAM → no 470MB local embedding model in prod; embeddings moved to an API provider (Jina) — `app/config.py:125-129`.
  2. Supabase pooler caps ~15 clients → DB pool capped, LLM calls must not hold pooled connections (audit #27 fix — snapshot user id, release session before LLM) — `app/api/routers/plan.py`.
  3. Free-tier AI (Groq LLM + Jina embeddings) → per-user daily budget check before every LLM call (`app/knowledge/budget.py`), rate limits per endpoint (`RATE_LIMIT_PLAN=10/minute`, etc.).

### 2) System Flow

```text
Next.js SPA (offline-first: IndexedDB queue + TanStack persist)
   │  axios  │  Supabase Realtime (push channel)
   ▼         ▼
FastAPI /api/v1/*  (routers: task, knowledge, memory, plan, sync, user, project,
                    notifications, realtime, audit, stats)
   │  SQLAlchemy async   │  RAG pipeline
   ▼                     ▼
Supabase Postgres (tbl_*)   KnowledgeAssistant: retrieve (BM25 + semantic,
   (pgvector embeddings)      RRF fusion) → LLM generate (citations) → LLM judge
```

1. **UI → API**: the SPA calls the FastAPI backend via axios (`src/lib/api.ts`); mutations offline-first — writes go to an IndexedDB queue (`src/lib/sync-queue.ts`) and flush via `POST /api/v1/sync` (`src/lib/sync-flush.ts`), conflicts merged LWW (`app/sync/lww.py`); live updates arrive via Supabase Realtime (`src/lib/realtime-client.ts`, `app/api/routers/realtime.py`).
2. **API layer**: `app/main.py:163-173` mounts routers under `/api/v1` — `tasks`, `knowledge`, `memory` under `/api/v1/tasks`; `plan`, `audit`, `stats`, `notifications`, `realtime`, `sync` under `/api/v1`; `users`, `projects`.
3. **Auth/limits**: JWT cookie auth (`app/security.py`), CSRF middleware, idempotency middleware, slowapi rate limits per endpoint, per-user LLM daily budget (`app/knowledge/budget.py`).
4. **RAG (Knowledge)**: notes/history ingested via `Source` → chunked → embedded (`app/knowledge/embeddings.py`, provider switchable: local/openai/jina) → persisted to `tbl_knowledge_chunks` (pgvector) → per-user in-memory retrieval index (`UserKnowledgeIndex`) — `app/knowledge/retrieval/`.
5. **RAG (Ask)**: `POST /api/v1/tasks/{task_id}/knowledge/ask` retrieves top-4 chunks (hybrid RRF over BM25 + semantic), grounds generation with citations, then an LLM judge grades relevance — `app/knowledge/assistant.py`.
6. **Memory**: completed tasks → `history` source → same index; `POST /api/v1/tasks/{task_id}/memory/similar` returns top-5 similar past tasks with duration hints (`app/api/routers/memory.py`).
7. **Planner**: `POST /api/v1/plan` — LLM-judged scoring of open tasks against available time + synthetic calendar connector + memory hints → time-bucketed plan (tonight/tomorrow/later), stateless (re-ask to replan) — `app/planner/service.py`; create-time soft-deadline proposals (`app/planner/deadline.py`).
8. **Background**: in-process tasks (reminder loop, memory backfill sweep) — `app/tasks.py`; celery removed (commit `ee84a2f`).

### 3) Layer/Module Responsibilities

| Layer or module | Owns | Must not own | Evidence |
|-----------------|------|--------------|----------|
| `app/api/routers/*` | HTTP contract, auth deps, rate limits, 503/429 error mapping | Business logic | `app/api/routers/plan.py`, `app/api/routers/knowledge.py` |
| `app/crud/*` | Async DB data access | HTTP/LLM concerns | `app/crud/knowledge.py` |
| `app/knowledge/retrieval/*` | BM25 index, semantic search, RRF fusion, tokenization | Generation | `app/knowledge/retrieval/bm25.py`, `hybrid.py` |
| `app/knowledge/assistant.py` | Grounded generation + LLM-as-judge + LLMCallRecord metrics | Retrieval internals (judge sees only question/answer/citations) | `app/knowledge/assistant.py` |
| `app/planner/*` | Plan scoring, calendar connector, deadline proposal | Retrieval internals | `app/planner/service.py` |
| `src/lib/sync-*` | Offline queue, delta encoding, flush, LWW conflict merge | UI | `src/lib/sync-queue.ts` |
| `src/components/task-drawer/KnowledgeSection.tsx` | Notes editing, "what do I need" answer display, +1/−1 feedback | API calls beyond its hooks | `src/components/task-drawer/KnowledgeSection.tsx` |

### 4) Reused Patterns

| Pattern | Where found | Why it exists |
|---------|-------------|---------------|
| Source registry (protocol + registry) | `app/knowledge/sources/base.py` → `note.py`, `history.py` | One interface per knowledge origin; file/url sources plug in later (07-CONTEXT decision 2) |
| Provider-switchable lazy singletons | `app/knowledge/embeddings.py` (`get_embedder`), `assistant.py` (`_openai_client`/`_groq_client`) | Free-tier cost control; local model loads lazily to avoid OOM at boot |
| Hybrid retrieval with RRF fusion | `app/knowledge/retrieval/hybrid.py` (port of rag-search-engine) | Fuses lexical (BM25) + semantic (vector) rankings; gated by eval to beat both single systems |
| Instrumented LLM wrapper (LLMCallRecord) | `app/knowledge/records.py`, `assistant.py` (pattern ported from llm-zc) | Per-call token/cost/latency telemetry persisted to `tbl_knowledge_answers` / `tbl_plan_answers` |
| LLM-as-judge structured verdict | `app/knowledge/assistant.py` (`RelevanceVerdict`) | Automates answer-quality grading; feeds golden set |
| Offline-first write queue with LWW merge | `src/lib/sync-queue.ts` + `app/sync/lww.py` | Real-time sync + offline (Phase 5) without losing writes |
| Per-user daily LLM budget guard | `app/knowledge/budget.py`, checked in plan/knowledge routers | Free-tier abuse control (audit #29 fix) |

### 5) Known Architectural Risks

- **Retrieval index is in-memory per instance**: `UserKnowledgeIndex` rebuilds from DB chunks (`ensure_index`), so a multi-instance deployment recomputes per instance and embeddings re-fetch; fine on Render single instance, latent scaling cost. (Evidence: `app/knowledge/retrieval/__init__.py`.)
- **LLM latency inside request path**: generate + judge run inline (async offload via `asyncio.to_thread`), so ask/plan latency = 2 LLM calls; bounded by rate limits and budget, but no queue/cache of answers.
- **Frontend hybrid routing**: SPA shell served through Next.js app router + `vercel.json` function proxy — a subtle build surface (the stale-build root cause fixed at `ecb1f0d`; Vercel auto-deploy integration still unconfirmed per map resolution).
- **Provider concentration on free tiers**: Groq + Jina free tiers are rate-limited; a hard spike (or key rotation post-dogfood) can 429/503 the AI features — graceful degradation exists (503 mapping, budget 429s).

### 6) Evidence

- `task-buddy-backend/app/main.py`
- `task-buddy-backend/app/knowledge/retrieval/hybrid.py`, `bm25.py`, `semantic.py`
- `task-buddy-backend/app/knowledge/assistant.py`
- `task-buddy-backend/app/planner/service.py`
- `task-buddy-frontend/src/lib/sync-queue.ts`, `sync-flush.ts`
- `task-buddy-frontend/src/lib/realtime-client.ts`
