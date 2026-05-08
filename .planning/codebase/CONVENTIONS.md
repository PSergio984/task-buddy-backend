# Conventions

**Analysis Date:** 2026-05-08

## Coding Style

**Tooling:**
- **Formatting:** Black (configured in `pyproject.toml`, 100 char line limit).
- **Linting:** Ruff (used for fast linting and import sorting).
- **Typing:** Mypy (strict type checking enabled for `app/`).

**Patterns:**
- **Docstrings:** Required for complex functions and classes.
- **Type Hints:** Mandatory for all function signatures and class attributes.
- **Imports:** Standard library first, then third-party, then local modules.

## API Patterns

**Request/Response:**
- Always use Pydantic schemas in `app/schemas/`.
- Prefer explicit status codes (e.g., `status_code=status.HTTP_201_CREATED`).
- Standard error response format (handled via FastAPI defaults or custom exception handlers).

**Authentication:**
- Protected routes must use `get_current_user` dependency from `app/api/dependencies.py`.
- Tokens are passed via `Authorization: Bearer <token>` header.

## Database Patterns

**Migrations:**
- Never modify database schema directly in models without an Alembic migration.
- Use descriptive migration names: `alembic revision -m "add_category_to_task"`.

**Transactions:**
- Use `db: Session` dependency.
- CRUD functions should not commit/rollback if they are meant to be part of a larger transaction (though current implementation often commits inside CRUD).

## Error Handling

**Global Handler:**
- Exceptions should bubble up to FastAPI's top-level or be caught and converted to `HTTPException`.
- Internal server errors (500) are caught and logged by Sentry.

**Validation Errors:**
- 422 Unprocessable Entity for Pydantic validation failures.
- 400 Bad Request for business logic failures (e.g., "User already exists").

---

*Conventions analysis: 2026-05-08*
*Update when team standards evolve*
