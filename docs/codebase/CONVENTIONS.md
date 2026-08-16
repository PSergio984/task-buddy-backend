# Coding Conventions

## Core Sections (Required)

### 1) Naming Rules

**Backend**

| Item | Rule | Example | Evidence |
|------|------|---------|----------|
| Files | snake_case | `app/knowledge/retrieval/bm25.py` | `app/` tree |
| Functions/methods | snake_case | `tokenize_text`, `rrf_search`, `check_llm_budget` | `app/knowledge/retrieval/*.py`, `app/knowledge/budget.py` |
| Classes | PascalCase | `InvertedIndex`, `KnowledgeAssistant`, `SyntheticCalendarConnector` | `app/knowledge/retrieval/bm25.py`, `app/knowledge/assistant.py` |
| Tables | `tbl_<plural>` | `tbl_tasks`, `tbl_knowledge_chunks`, `tbl_plan_answers` | `app/models/*.py` |
| Config/env vars | UPPER_SNAKE | `GROQ_API_KEY`, `EMBEDDING_PROVIDER`, `RATE_LIMIT_PLAN` | `app/config.py` |
| Routers/tags | domain noun | `ROUTER_TAG = "plan"` | `app/api/routers/plan.py` |

**Frontend**

| Item | Rule | Example | Evidence |
|------|------|---------|----------|
| Component files | PascalCase | `TaskDetailPage.tsx`, `KnowledgeSection.tsx` | `src/views/`, `src/components/task-drawer/` |
| Hooks | camelCase `useX` | `useTasks.ts`, `useKnowledgeNotes.ts` | `src/hooks/` |
| shadcn/ui primitives | kebab-case | `task-card.tsx`, `sync-status-pill.tsx` | `src/components/ui/`, `src/components/` |
| Tests | co-located `*.test.ts(x)` | `sync-queue.test.ts` | `src/lib/` |

### 2) Formatting and Linting

- Backend formatter/linter: **ruff** (CI gate: `ruff check .` + `ruff format --check .`; see commits `ee6aa75`, `046ed5e`); **mypy** enforced via the CI typecheck job (`mypy app`); black/isort declared in dev extras but ruff is the enforced format gate.
- Frontend formatter/linter: **eslint 9 + typescript-eslint** (`eslint .`) and **prettier** (`format:check` gate in CI); `next typegen && tsc --noEmit` typecheck.
- Run commands:
  - Backend: `ruff check .`, `ruff format .`, `pytest`
  - Frontend: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run test:ci`

### 3) Import and Module Conventions

- Backend: absolute imports from package root (`from app.knowledge.retrieval import UserKnowledgeIndex`, `from app.config import ...`); lint-enforced (ruff `I` rules in CI commit `ee6aa75` sorted migration imports).
- Frontend: relative imports within `src/`; barrel-free (direct file imports).
- Migrations: one file per change, semantic names (`2d4e6f8a0b1c_switch_embeddings_to_jina_1024.py`), imported in order.

### 4) Error and Logging Conventions

- Error strategy: routers map AI failures to **503** (missing key → `AssistantNotConfiguredError`; provider errors → `AI_UNAVAILABLE`) and budget overflow to **429** ("Daily AI usage limit reached") — `app/api/routers/plan.py`, `app/api/routers/knowledge.py`, `app/api/routers/memory.py`. DB/domain errors map to 404/400 per resource.
- Logging: `logging.getLogger(__name__)` per module; JSON logs via python-json-logger with correlation IDs (`app/logging_conf.py`).
- Sensitive-data redaction: PII log redaction added in pre-dogfood hardening (commit `5b17d54`); reset tokens never echoed back in responses (audit #25 fix); keys live in env/config only (`app/config.py` comments: "The key comes from env only — never hardcoded").

### 5) Testing Conventions

- Backend: pytest; files `test_*.py` under `tests/` (`tests/routers/` for API tests); `asyncio_mode = "auto"`; strict markers; LLM/embedding calls mocked or stubbed (`get_embedder` stubbed directly per `app/knowledge/embeddings.py` docstring); offline mode must pass without API keys (07-VALIDATION).
- Frontend: vitest unit tests co-located `*.test.ts(x)` in `src/`; Playwright E2E in `tests/*.spec.ts`; jsdom setup at `src/test/setup.ts`.

### 6) Evidence

- `task-buddy-backend/pyproject.toml` (`[tool.pytest.ini_options]`, dev extras)
- `task-buddy-backend/.github/workflows/python-app.yml`
- `task-buddy-frontend/package.json`, `eslint.config.js`, `.prettierrc`
- `task-buddy-frontend/.github/workflows/ci.yml`
- Representative source: `app/api/routers/plan.py`, `src/lib/sync-flush.ts`
