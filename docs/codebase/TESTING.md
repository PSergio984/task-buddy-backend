# Testing Patterns

## Core Sections (Required)

### 1) Test Stack and Commands

- Primary test framework (backend): **pytest >=7.4** with pytest-asyncio (`asyncio_mode = "auto"`), pytest-cov, pytest-mock — 49 test files, 347 tests (map resolution, 2026-08-16).
- Primary test framework (frontend): **vitest 4** + @testing-library/react + jsdom (unit), **Playwright** (E2E) — 13 unit test files + 8 E2E specs.
- Commands:

```bash
# backend
pytest                                  # all tests
pytest tests/routers/                   # API tests
pytest --cov=app                         # coverage

# frontend
npm run test:ci                          # vitest run
npm run test:e2e                         # playwright test
npm run test:coverage                    # vitest coverage
```

### 2) Test Layout

- Backend: `tests/` folder, `test_*.py` naming, `tests/routers/` for API tests; shared fixtures in `tests/conftest.py`; golden eval fixture at `tests/fixtures/golden_knowledge.json`.
- Frontend: unit tests co-located next to source (`src/lib/sync-queue.test.ts`, `src/components/sidebar.test.tsx`), setup at `src/test/setup.ts`; E2E in `tests/*.spec.ts`.

### 3) Test Scope Matrix

| Scope | Covered? | Typical target | Notes |
|-------|----------|----------------|-------|
| Unit | yes | retrieval (BM25/semantic/RRF), embeddings providers, budget, sync LWW, planner schema, idempotency, cache, security, migrations | `test_retrieval.py`, `test_embeddings_jina.py`, `test_sync_lww.py`, `test_llm_budget.py` |
| Integration | yes | API routers against test DB (SQLite/Postgres), sync API, realtime, notifications, plan/memory/knowledge endpoints, deadline proposal; CI also runs an alembic revision-chain sanity check (single head) | `tests/routers/*`, `test_plan_endpoint.py`, `test_memory_endpoint.py`, `.github/workflows/python-app.yml` (migrations job) |
| E2E | yes (frontend) | auth, landing, layout/nav, notifications, sidebar dnd, timepicker, advanced tasks | `tests/*.spec.ts` (Playwright, 8 specs) |
| Evaluation harness | yes | golden-set P@k/R@k/F1, hybrid vs single-system gates, judge/LLM record assertions | `test_evaluation.py`, `test_knowledge_assistant.py`, `tests/fixtures/golden_knowledge.json` |

### 4) Mocking and Isolation Strategy

- Main mocking approach: LLM/embedding calls are stubbed — `get_embedder()` stubbed directly in tests (per `app/knowledge/embeddings.py` docstring), generation/judge mocked so the suite passes offline without API keys (07-VALIDATION); `httpx`/client calls mocked at boundaries.
- Isolation guarantees: per-test DB via conftest fixtures; `DB_FORCE_ROLL_BACK` config exists for transactional isolation; tests are strictly marker-validated (`--strict-markers`).
- Common failure mode: provider-dependent tests failing when keys are missing or rate-limited — mitigated by offline-mock requirement.

### 5) Coverage and Quality Signals

- Coverage tool: pytest-cov / vitest coverage configured; current % `[TODO]` (347 tests green per 2026-08-16 map resolution; no explicit threshold found).
- Known gaps: LLM answer *quality* is judge-verified, not unit-assertable (manual-only verification per 07-VALIDATION); golden dataset is synthetic-but-representative until dogfood appends real pairs (per DOGFOOD.md).

### 6) Evidence

- `task-buddy-backend/pyproject.toml` (`[tool.pytest.ini_options]`)
- `task-buddy-backend/.github/workflows/python-app.yml` (CI runs ruff + pytest)
- `task-buddy-frontend/package.json` (vitest, playwright scripts)
- `task-buddy-frontend/.github/workflows/ci.yml`
- `task-buddy-backend/tests/fixtures/golden_knowledge.json`
- `task-buddy-backend/.planning/phases/07-ai-knowledge-layer/07-VALIDATION.md`
