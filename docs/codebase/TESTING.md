# Testing Patterns

## Core Sections (Required)

### 1) Test Stack and Commands

- Primary test framework: pytest
- Assertion/mocking tools: pytest-mock, httpx.AsyncClient (for API testing)
- Commands:

```bash
pytest
pytest --cov=app tests/
pytest tests/routers/test_task.py
```

### 2) Test Layout

- Test file placement pattern: Separate `tests/` directory mirroring `app/` structure.
- Naming convention: `test_*.py`
- Setup files and where they run: `tests/conftest.py` (fixtures for DB session, app client, etc.)

### 3) Test Scope Matrix

| Scope | Covered? | Typical target | Notes |
|-------|----------|----------------|-------|
| Unit | Yes | Utility functions, security logic | `tests/test_security.py` |
| Integration | Yes | API Routers, Database migrations | `tests/routers/`, `tests/test_migrations.py` |
| E2E | Partial | Complex task flows | `tests/test_tasks.py` |

### 4) Mocking and Isolation Strategy

- Main mocking approach: Uses `pytest-mock` to mock external services (like Sentry) and `dependency_overrides` in FastAPI to inject test database sessions.
- Isolation guarantees: Database is typically reset or a transaction is rolled back after each test fixture (evidenced by `test.db` and fixture patterns).
- Common failure mode in tests: Async synchronization issues or database lock contention if not handled carefully.

### 5) Coverage and Quality Signals

- Coverage tool + threshold: `pytest-cov` (Threshold [TODO])
- Current reported coverage: [TODO]
- Known gaps/flaky areas: Migration tests can sometimes be sensitive to environment state.

### 6) Evidence

- `tests/conftest.py`
- `pyproject.toml`
- `tests/routers/test_task.py`

## Extended Sections (Optional)

- Fixture map: `db_session`, `client`, `test_user`, `auth_headers`.
