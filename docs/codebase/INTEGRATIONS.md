# External Integrations

## Core Sections (Required)

### 1) Integration Inventory

| System | Type | Purpose | Auth model | Criticality | Evidence |
|--------|------|---------|------------|-------------|----------|
| Supabase (Postgres) | DB | Primary datastore (all `tbl_*` tables; pgvector embedding column served by Supabase) | Connection string `DATABASE_URL`; pool capped ~15 clients | high | `app/config.py`, `app/database.py` |
| Supabase Realtime | Realtime channel | Push channel for live sync to the frontend (replaced SSE — Phase 5 scope cut) | `NEXT_PUBLIC_SUPABASE_URL` + publishable key (frontend) | med | `src/lib/realtime-client.ts`, `app/api/routers/realtime.py`, wayfinder ticket #17 |
| Groq (LLM) | AI API | Production LLM for generation + judge (`llama-3.3-70b-versatile`), OpenAI-SDK-compatible `base_url` | `GROQ_API_KEY` (server env only) | high | `app/config.py:151-156`, `app/knowledge/assistant.py` |
| Jina (embeddings) | AI API | Production embeddings (`jina-embeddings-v3`, 1024-dim, multilingual), OpenAI-compatible | `JINA_API_KEY` (server env only) | high | `app/config.py:136-138`, `app/knowledge/embeddings.py` |
| OpenAI (fallback/legacy) | AI API | LLM `gpt-4o-mini` + embeddings `text-embedding-3-small` (dev default / pre-Groq-Jina prod) | `OPENAI_API_KEY` (server env only) | low (fallback) | `app/config.py:143-150`, git log `c68a8c9`, `020a3ad` |
| Render | Hosting | Backend deployment (free tier, 512MB) | Deploy key / env vars | high | map resolution; `app/config.py` comments |
| Vercel | Hosting | Frontend deployment + serverless function proxy to backend | Vercel project env vars | high | `vercel.json`, git log `ecb1f0d`, `def325c` |
| Redis | Cache/queue | Task cache + optional rate-limit storage (prod uses in-memory limiter; bounded pools) | `REDIS_URL` | low-med | `app/config.py:36,59-64`, `app/libs/cache.py` |
| Brevo (Sendinblue) | Email | Transactional mail (verification, password reset, reminders) | `DEV_MAIL_*` / `TEST_MAIL_*` keys | med | `app/libs/email_templates.py`, `.env.example` |
| Backblaze B2 | Object storage | File storage wrapper (`app/libs/b2/`) | `TEST_B2_*` keys | low | `app/libs/b2/`, `.env.example` |
| Web Push (VAPID) | Push | Browser notifications via pywebpush | VAPID keypair | low | `app/models/notification.py`, `.env.example` |
| Sentry | Observability | Error tracking | `SENTRY_DSN` | low | `app/config.py`, `app/logging_conf.py` |
| SonarCloud | Static analysis | Quality gate (deferred per map resolution) | sonar-secrets workflow | low | `.github/workflows/sonarcloud.yml` |

### 2) Data Stores

| Store | Role | Access layer | Key risk | Evidence |
|-------|------|--------------|----------|----------|
| Supabase Postgres | System of record: users, tasks, subtasks, projects, tags, knowledge (chunks/answers/feedback), plan answers, audit logs, notifications, push subscriptions | `app/crud/*` via SQLAlchemy async | Pool exhaustion under concurrent LLM calls (audit #27 — fixed by releasing session before LLM) | `app/database.py`, `app/api/routers/plan.py` |
| pgvector column (in Supabase) | Embedding vectors (1024-dim prod, 384 dev) | `app/knowledge/ingest.py` writes; retrieval uses in-memory index over chunk rows | Embedding dimension migrations (384→1536→1024) touched prod schema twice | `alembic/versions/1e2f3a4b5c6d_*.py`, `2d4e6f8a0b1c_*.py` |
| Redis | Task cache + optional limiter storage | `app/libs/cache.py` | Redis Cloud free tier ~30 clients (bounded pools fix `2ee499a`) | `app/config.py` |
| IndexedDB (browser) | Offline sync queue + TanStack persist cache | `src/lib/sync-queue.ts`, `src/lib/query-client.ts` | Queue/flush race conditions (frontend audit #2/#3 fixed `ed99518`) | `src/lib/sync-flush.ts` |

### 3) Secrets and Credentials Handling

- Credential sources: server env vars only (`app/config.py` reads `os.environ`; `.env.example` documents every var; no committed secrets — scan found none).
- Hardcoding checks: none found; keys referenced exclusively through config module.
- Rotation: map resolution flags "rotate Groq/Jina keys post-dogfood" — rotation runbook is `[TODO]`.

### 4) Reliability and Failure Behavior

- Retry/backoff: partial — idempotency middleware (`app/middleware/idempotency.py`) with 4xx idempotency semantics (commit `5b17d54`); frontend sync flush retries on 429 from first hit (commit `f6e0cb6`); LLM client no explicit backoff config — `[TODO]`.
- Timeout policy: LLM calls bounded by sync execution + rate limits; no explicit per-provider timeouts documented — `[TODO]`.
- Fallbacks: embeddings provider switch (local/openai/jina) with graceful degradation; missing key → 503 (never 500); budget exceeded → 429; memory backfill sweep survives embed failures (commit `b451c1d`); offline mode works without AI keys (07-VALIDATION).

### 5) Observability for Integrations

- Logging around external calls: yes — `app/knowledge/assistant.py` logs each LLM call; LLMCallRecord persists latency/tokens/cost per answer (`tbl_knowledge_answers`, `tbl_plan_answers`); Sentry for exceptions; JSON logs with correlation IDs.
- Metrics/tracing: latency + token + cost captured per call in DB (queryable at dogfood gate via SQL per DOGFOOD.md); no external metrics system.
- Missing visibility: no structured LLM-error rate dashboard; rate-limit hits only in logs; SonarCloud gate deferred — `[TODO]`.

### 6) Evidence

- `task-buddy-backend/app/config.py`, `.env.example`
- `task-buddy-backend/app/knowledge/embeddings.py`, `assistant.py`
- `task-buddy-backend/.planning/DOGFOOD.md` (capture SQL)
- `task-buddy-frontend/.github/workflows/ci.yml` (env vars)
- `task-buddy-backend/.github/workflows/sonarcloud.yml`
