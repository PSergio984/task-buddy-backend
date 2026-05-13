<!-- generated-by: gsd-doc-writer -->
# Conventions

**Analysis Date:** 2026-05-13

## Coding Style

**Tooling:**
- **Formatting:** Black (100 char line limit).
- **Linting & Imports:** Ruff.
- **Typing:** Mypy (mandatory for all new code).

**Patterns:**
- **Dependency Injection:** Use `Annotated` for all FastAPI dependencies (e.g., `db: Annotated[AsyncSession, Depends(get_db)]`).
- **Docstrings:** Use Google-style docstrings for complex logic.
- **Async First:** All database and I/O operations must be `async`. Avoid `blocking` calls in the main thread.
- **Audit Logging:** CRUD operations that mutate state (CREATE, UPDATE, DELETE) must use the `@audit_log` decorator from `app.libs.audit`.

## API Patterns

**Request/Response:**
- Use Pydantic schemas for all data entry and exit points.
- Define `responses` in the APIRouter for 404, 400, and 401 cases to ensure Swagger accuracy.
- Use explicit status codes (e.g., `status.HTTP_201_CREATED`, `status.HTTP_204_NO_CONTENT`).

- Protect routes using the `get_current_user` dependency.
- **Authentication:** JWTs are primarily extracted from HttpOnly cookies; fallback to `HTTPBearer` (Authorization header) is supported for specialized API integrations.

## Database Patterns

**Migrations:**
- Every schema change must have a corresponding Alembic migration.
- Use descriptive names: `add_notifications_table`.

**Transactions:**
- Leverage `AsyncSession` context managers or the `db` dependency.
- Ensure `db.commit()` is called after successful mutations, typically in the router or service layer.

**Models:**
- Use `Mapped` and `mapped_column` for SQLAlchemy 2.0 type-safe models.
- Prefer `selectinload` for relationship loading to avoid N+1 problems in async contexts.

## Error Handling

**Standardized Exceptions:**
- Raise `fastapi.HTTPException` for client-side errors (400-499).
- Let unexpected errors bubble up to the global 500 handler, which logs to Sentry.

**Validation:**
- Allow Pydantic to handle 422 Unprocessable Entity automatically.
- Manually check for business logic conflicts (e.g., duplicate names) and raise 400 Bad Request.

---

*Conventions analysis: 2026-05-13*
*Update when team standards evolve or new patterns are adopted*
