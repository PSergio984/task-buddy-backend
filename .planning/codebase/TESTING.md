# Testing

**Analysis Date:** 2026-05-08

## Framework

- **Primary:** Pytest 7.4+
- **Async Support:** `pytest-asyncio` with `asyncio_mode = "auto"` in `pyproject.toml`.
- **Mocking:** `pytest-mock` for external integrations (Brevo, Sentry).

## Test Structure

```text
tests/
├── routers/              # Integration tests for endpoints
│   ├── test_user.py      # Auth, profile, registration
│   ├── test_task.py      # CRUD tasks, assignments
│   └── test_stats.py     # Analytics endpoints
├── conftest.py           # Global fixtures (client, db, session)
├── test_security.py      # JWT and password hashing tests
└── test_migrations.py    # Database schema validation
```

## Fixtures

**`client`:**
- `TestClient` or `AsyncClient` for making requests to the app.
- Re-creates a clean environment for each test.

**`db` / `session`:**
- Uses a separate SQLite database (`test.db` or in-memory) to avoid data loss in dev/prod.
- Wiped/Reset between tests or test classes.

## Execution

**Run all tests:**
```bash
pytest
```

**Run with coverage:**
```bash
pytest --cov=app
```

**Run specific file:**
```bash
pytest tests/routers/test_task.py
```

## Patterns

- **Arrange, Act, Assert:** Standard structure for all test cases.
- **Mocking External APIs:** Never call Brevo or Sentry in tests. Use `mocker` fixture to intercept calls.
- **Database Isolation:** Each test starts with a fresh database or rolls back changes.

---

*Testing analysis: 2026-05-08*
*Update when testing strategy changes*
