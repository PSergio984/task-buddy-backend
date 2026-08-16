# Mock Presentation Pack — TaskBuddy: Adaptive Workload & Priority Copilot

A one-file brief for the Amazon Quick capstone presentation. Every claim is traceable to code or the planning/decision records (see `docs/codebase/` for the full evidence-backed docs: STACK, STRUCTURE, ARCHITECTURE, CONVENTIONS, INTEGRATIONS, TESTING, CONCERNS).

---

## 1. One-liner

TaskBuddy is an **AI-powered task manager**: it remembers what you've done (Memory), understands what each task needs (Knowledge), and tells you **"what should I work on next"** — a ranked, time-bucketed plan grounded in your workload, your available time, and your history (Planner). Built as a **mini-Quick mock** on an existing stack — the Amazon Quick feature set (Connectors, Knowledge, Memory, Flows) mapped onto FastAPI + Next.js.

## 2. Tech stack (what it's built on)

| Layer | Choice | Why |
|-------|--------|-----|
| Backend | **FastAPI + SQLAlchemy 2 (async) + Alembic**, Python ≥3.10 | Existing TaskBuddy foundation (Phases 1–6); async fits IO-heavy LLM/RAG work |
| Database | **Supabase Postgres** (pgvector for embeddings) | Managed, free tier, pooler-capped; Realtime doubles as the sync push channel |
| Frontend | **Next.js 16 + React 19 + TypeScript**, TanStack Query, Tailwind 4 + shadcn/ui | Existing foundation; offline-first via IndexedDB sync queue + service worker (Serwist) |
| LLM | **Groq — `llama-3.3-70b-versatile`** (free tier, OpenAI-compatible API) | Zero-cost generation; OpenAI `gpt-4o-mini` remains as fallback/dev default |
| Embeddings | **Jina — `jina-embeddings-v3`** (1024-dim, multilingual, free tier) | Local sentence-transformers (MiniLM-L12-v2, 384-dim) OOMs Render's 512MB tier; Groq has no embedding API → providers split |
| Hosting | **Render** (backend) + **Vercel** (frontend) + Supabase | Cheapest deployed topology; `alembic upgrade head` on Supabase |
| Search/retrieval | **BM25 + dense-vector semantic search fused by Reciprocal Rank Fusion (RRF)** | See §5 — the heart of the RAG answer |
| Background | In-process tasks (reminder loop, memory backfill sweep); **Celery removed** | Simpler, free-tier-friendly |

## 3. Architecture (system flow)

```text
Next.js SPA (offline-first: IndexedDB queue + TanStack persist)
   │ axios                          │ Supabase Realtime (push)
   ▼                                ▼
FastAPI /api/v1/* ── routers: tasks, knowledge, memory, plan, sync,
│                    user, project, notifications, realtime, audit, stats
├─ Auth: JWT cookie + CSRF + idempotency + slowapi rate limits + per-user LLM budget
├─ RAG pipeline (app/knowledge/): Source → chunk → embed → index → retrieve → generate → judge
└─ Planner (app/planner/): connector (synthetic calendar) + LLM-judged scoring + soft deadlines
Supabase Postgres (tbl_*, pgvector embeddings)
```

Key traits:
- **Offline-first sync**: writes queue to IndexedDB, flush via `POST /api/v1/sync`, LWW conflict merge, live updates via Supabase Realtime (SSE was cut — one round-trip sync instead).
- **Layered backend**: routers → CRUD → models; AI lives in its own `app/knowledge/` + `app/planner/` packages with a `Source` registry so new knowledge sources (file/url) plug in without touching the pipeline.

## 4. Where RAG is used (three surfaces, one engine)

All three reuse the **same retrieval engine** (`app/knowledge/retrieval/`: BM25 + semantic + RRF):

1. **Knowledge — "What do I need for this task?"** (`POST /api/v1/tasks/{task_id}/knowledge/ask`)
   Retrieves the top-4 chunks from the user's **notes/knowledge corpus** for that task, grounds the LLM answer with citations, then an **LLM-as-judge** grades relevance (RELEVANT / PARTLY_RELEVANT / NON_RELEVANT). User +1/−1 feedback persists to `tbl_knowledge_feedback`.
2. **Memory — "Similar tasks from my history"** (`POST /api/v1/tasks/{task_id}/memory/similar`)
   RAG over the **completed-tasks corpus** (Phase 8; `history` source type reusing the Phase 7 engine). Returns top-5 similar past tasks with **duration hints** (`estimated_effort_minutes` from history rows) — this is how the planner estimates effort without asking.
3. **Planner — "What should I work on next?"** (`POST /api/v1/plan`)
   Not retrieval-in-the-loop, but **RAG-fed**: the LLM-judged scorer takes open tasks + available minutes + the synthetic calendar connector's free windows + **Memory similar-task hints** and emits a time-bucketed plan (`{tonight, tomorrow, later}` with per-task one-sentence reasons). Stateless — replanning is re-asking.

**RAG boundary (locked decision):** RAG serves *Knowledge* (task context docs) and *Memory* (task history). It does **not** power "what's my task today" — that's a structured query over the live tasks table. Current tasks are state, not a corpus.

## 5. Retrieval method: BM25 or TF-IDF? Vector search? — Yes: all three, fused

**The answer: BM25 + vector search, fused via RRF. TF-IDF is NOT used anywhere.**

| Component | What it is | Details (from code) |
|-----------|-----------|---------------------|
| **BM25** (lexical) | Okapi BM25 keyword index, ported from a prior rag-search-engine | `k1 = 1.5`, `b = 0.75`, Laplace-smoothed IDF; tokens = lowercase → strip punctuation → stopword drop → **Porter stemmer** (nltk) — `app/knowledge/retrieval/bm25.py`, `tokenize.py` |
| **Vector search** (semantic) | Dense embeddings + cosine similarity | L2-normalized vectors from the configured embedder; per-chunk cosine, best-per-doc — `app/knowledge/retrieval/semantic.py` |
| **Hybrid fusion** | **Reciprocal Rank Fusion (RRF)** | `score = Σ 1/(k + rank)`, `k = 60`, deep candidate pools (`limit × 500`) per system — `app/knowledge/retrieval/hybrid.py` |

Why hybrid? It was **gated by the eval harness**: the golden set requires hybrid RRF ≥ BM25 alone AND ≥ semantic alone on precision@3 / F1@5 — the fusion must earn its complexity. Retrieval is **per-user** (user A never sees user B's chunks — tested) and the index is rebuilt with **content-hash cache invalidation**.

## 6. Evals (how we prove the AI works)

| Layer | Method | Details |
|-------|--------|---------|
| Retrieval | **Golden dataset** (`tests/fixtures/golden_knowledge.json`) | 10–20 realistic task/notes cases from the user's real life (Taglish), each with known relevant knowledge ids; scored **P@k / R@k / F1** at k=3,5 (`app/knowledge/evaluation.py`, `test_evaluation.py`) |
| Fusion gate | Hybrid must beat each single system | pytest gate on the golden set |
| Answer quality | **LLM-as-judge** (`RelevanceVerdict`) | Every answer gets a structured verdict (RELEVANT/PARTLY_RELEVANT/NON_RELEVANT + explanation); judge never sees retrieval internals |
| User signal | **+1/−1 feedback loop** | Persisted to `tbl_knowledge_feedback`; thumbs UI shipped (P-1); every −1 / judge NON_RELEVANT is triaged into the golden set + fix |
| Cost/health | **LLMCallRecord instrumentation** | Every LLM call records latency, tokens, cost (USD) into `tbl_knowledge_answers` / `tbl_plan_answers` — dashboard-queryable SQL at the dogfood gate |
| Regression | **347 backend tests** (49 files) + **69 frontend tests** (13 vitest files + 8 Playwright specs), CI gates | backend: alembic chain check + ruff + mypy + pytest + docker build; frontend: lint/format/typecheck/vitest/build; AI calls mocked so the suite passes offline |
| Live | **Dogfood window** (open since 2026-08-14, gate ~Aug 28) | ≥10 real "what do I need" interactions; every bad answer → golden-set case + fix; 5-point gate review |

## 7. Decisions we made (and when) — the decision log

**Wayfinding (wayfinder map #14, all tickets closed 2026-08-13/16):**

| Decision | Gist |
|----------|------|
| Effort & available-time data model (#18) | `estimated_effort_minutes` int, optional, user-entered, tasks only; available time = per-request `available_minutes` + global default (120); schema lands with Phase 9 |
| Memory scope — Phase 8 (#19) | Corpus = completed tasks (title+description), unbounded; retrieval-first personalization (similar past tasks → effort hints); passive collector before dogfood; new `history` SourceType reusing the Phase 7 pipeline |
| Planner scope — Phase 9 (#20) | LLM-judged scoring (KnowledgeAssistant-style), global `POST /api/v1/plan`, time-bucketed output with per-item reasons + metrics, create-time **soft deadlines** (propose-and-confirm, `deadline_type` in schema, **never auto-apply**), stateless recompute |
| Phase 5 scope (#17) | SSE + Redis cut → **Supabase Realtime** is the push channel; single round-trip `POST /api/v1/sync`; frontend offline cache + optimistic UI |
| Phase 4 scope (#16) | Verify vs build — audit + verification before new features |
| Deploy (#15) | Render (backend) / Vercel (frontend) / Supabase DB; `alembic upgrade head` on Supabase |
| Synthetic calendar Connector (#23) | Mock event/availability data, zero OAuth (real Google Calendar = future expansion); fixed demo dataset; `SYNTHETIC_CALENDAR_ENABLED` |
| Capstone packaging & demo (#21) | Demo scenario: 5 active tasks, 3 deadlines, 2.5h available, 1 calendar event → "what should I work on tonight" → situation changes → replan → why-explanation; pre-existing vs new split (doc §19); facilitator approval for existing-project extension |
| Dogfood floor (#22) | 1–2 weeks real use after Planner; bad answers → golden-set cases + fixes; 5-point gate review |

**AI-layer decisions (07-CONTEXT, locked 2026-08-12):**

| Decision | Gist |
|----------|------|
| RAG boundary | RAG serves Knowledge + Memory only; live tasks are state, not a corpus |
| Source strategy | Text-first (task notes), modular `Source` registry; file/url/email later — fog, not yet ticketed |
| Cost profile | Local embeddings (free) at first; OpenAI only for generation + judge; per-query embedding cost = $0 — later amended: **Groq LLM + Jina embeddings in prod** (both free tiers) because the local model OOMs Render |
| Reuse | Retrieval core ported from `rag-search-engine` (BM25 + chunked semantic + RRF + golden harness); instrumentation/judge patterns from `llm-zc` (not the code) |
| No new services | Stack stays FastAPI + SQLAlchemy + Supabase + Next.js |
| Queue order | 7 → 4 → 5, then 8 → 9; deploy first, dogfood after Planner |

**Engineering decisions along the way (git log):**

| When | Decision |
|------|----------|
| `7969d26` | Vite SPA → **Next.js + Supabase Realtime** (phase 5 foundation) |
| `ee84a2f` | **Drop Celery** — background work runs in-process |
| `020a3ad` → `c68a8c9` | Embeddings: local → OpenAI `text-embedding-3-small` → **Jina**; LLM: OpenAI → **Groq** |
| `5b17d54` | Pre-dogfood hardening: XFF spoof fix, sync payload validation, CSRF origin check, 4xx idempotency, PII log redaction, completion-flip history hooks, DB indexes |
| `0934eee` / `ed99518` | Resolved all 14 pre-dogfood audit findings (backend #25–#30, frontend #2–#7) |
| `2ee499a` | Bounded Redis pools + in-memory rate-limit storage (Redis Cloud ~30-client cap) |

## 8. Pre-existing vs new (capstone originality, doc §19)

- **Pre-existing (built before capstone)**: core task/subtask/project/tag CRUD, auth (JWT + Argon2, email verification, password reset), notifications + reminders + web push, audit logging, rate limiting, idempotency, premium UI (Phases 1–3.x, 4 hardening).
- **New for the capstone**: real-time sync + offline mode (Phase 5), AI Knowledge layer (Phase 7), Memory RAG over task history (Phase 8), Planner + soft deadlines + effort model (Phase 9), synthetic calendar Connector, deployment to Render/Vercel/Supabase, dogfood loop, packaging.

## 9. Demo scenario (doc §16, ticket #21)

1. User has 5 active tasks, 3 deadlines, ~2.5h available tonight, 1 calendar event (the 6–7pm Wednesday meeting).
2. User asks **"What should I do tonight?"** → TaskBuddy retrieves memory hints for similar past tasks, reads the calendar connector's free windows, and returns a ranked, time-bucketed plan with per-task reasons.
3. The situation changes (a deadline moves, a task completes) → replan → **updated recommendation with explanation** of what changed and why.

## 10. Numbers to quote

- 347 backend tests / 49 files, CI green on main (2026-08-16); 69 frontend tests, lint/typecheck green
- 15 Alembic migrations (CI sanity-checks a single revision head); 13 `tbl_*` tables; 2 embedding-dim migrations survived
- Retrieval: BM25 (k1=1.5, b=0.75) + 1024-dim vectors + RRF (k=60, 500× pools)
- Cost: $0 LLM/embedding spend at current usage (Groq + Jina free tiers, per-user daily budget enforced)
- Live: `https://task-buddy-backend-wy3w.onrender.com` / `https://task-buddy-frontend.vercel.app`

## Sources

- `task-buddy-backend/.planning/` (PROJECT, REQUIREMENTS, DOGFOOD, `phases/07-*/`, `phases/08-*/`, `phases/09-*/`)
- Wayfinder map #14 + tickets #15–#24 (github.com/PSergio984/task-buddy-backend/issues)
- `C:\Users\admin\Downloads\TaskBuddy_Amazon_Quick_Capstone_Project_Idea.md` (vision doc)
- Code: `app/knowledge/`, `app/planner/`, `app/config.py`, `app/main.py`, `src/lib/sync-*`
- Companion docs: `docs/codebase/STACK.md`, `STRUCTURE.md`, `ARCHITECTURE.md`, `CONVENTIONS.md`, `INTEGRATIONS.md`, `TESTING.md`, `CONCERNS.md`
