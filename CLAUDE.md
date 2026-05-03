# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

- **Install dependencies (editable)**: `pip install -e ".[dev]"`
- **Install from requirements**: `pip install -r requirements.txt`
- **Run the API in development**:
  - `fastapi dev` (FastAPI CLI) **or**
  - `uvicorn app.main:app --reload`
- **Run the API in production**: `fastapi run` **or** `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- **Run the test suite**: `pytest`
- **Run a single test**: `pytest path/to/test_file.py::test_name`
- **Run tests with coverage**: `pytest --cov=app --cov-report=html`
- **Code formatting**: `black app tests`
- **Linting**: `ruff check app tests`
- **Static type checking**: `mypy app`
- **Import sorting**: `isort app tests`
- **Build Docker image**: `docker build -t task-buddy-backend:latest .`
- **Run Docker container**: `docker run -p 8000:8000 task-buddy-backend:latest`

## High‑Level Architecture

- **Entry point** – `app/main.py` creates the FastAPI instance, adds CORS and correlation‑id middleware, registers routers, and manages the async database lifecycle via a `lifespan` context manager.
- **Configuration** – `app/config.py` holds environment‑driven settings (database URL, JWT secret, etc.) using `pydantic‑settings`.
- **Security** – `app/security.py` provides JWT token creation/verification and the `get_current_user` dependency used by protected routes.
- **Database layer** – `app/database.py` defines the async SQLAlchemy engine and provides table objects (`tbl_task`, `tbl_subtask`, `tbl_tags`). CRUD helpers are in `app/crud/` (if present).
- **Models** – SQLAlchemy ORM models live in `app/models/` (e.g., `task.py`, `user.py`, `tag.py`). They map to database tables and are used by the CRUD layer.
- **Schemas** – Pydantic request/response schemas are defined in `app/schemas/` (e.g., `task.py`, `user.py`). These are the data contracts for FastAPI endpoints.
- **API routers** – `app/api/routers/` groups related endpoints:
  - `tasks.py` – task CRUD, sub‑task handling, tag management.
  - `users.py` – user registration, login, profile operations.
  - `health.py` – health, readiness, and liveness probes.
- **Internal utilities** – `app/internal/` contains auxiliary modules such as admin helpers.
- **Dependencies** – `app/dependencies.py` and `app/api/dependencies.py` expose shared FastAPI dependencies (e.g., DB session, auth).
- **Logging** – `app/logging_conf.py` configures the Python logging system; Sentry integration is initialized in `app/main.py`.
- **Testing** – Tests live under `tests/` mirroring the `app/` package structure. They use `httpx.AsyncClient` to exercise the API and rely on the same configuration utilities.

## Environment Variables

Create a `.env` file at the repository root with at least the following keys (see README for full list):
```
DATABASE_URL=postgresql://user:password@localhost/task_buddy
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
DEBUG=True
LOG_LEVEL=INFO
```
Claude should prefer reading configuration via `app.config` rather than hard‑coding values.

---

*Claude Code should use the above commands for routine tasks and keep the architectural overview in mind when navigating or modifying the codebase.*