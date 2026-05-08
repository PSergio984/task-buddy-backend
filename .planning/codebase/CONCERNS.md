# Concerns

**Analysis Date:** 2026-05-08

## Technical Debt

- **CRUD Commit Bloat:** Several CRUD functions in `app/crud/` handle their own commits, which makes composing multiple CRUD operations into a single transaction difficult.
- **Duplicate Literals:** Hardcoded strings in `app/api/routers/tasks.py` for status values and category names. Should be moved to Enums or Constants.

## Security

- **Hardcoded Secret Placeholder:** `.env.example` and potentially some early code versions might have shared "your-secret-key-here" placeholders. Ensure `SECRET_KEY` is always generated and rotated in production.
- **CORS Configuration:** `localhost` is currently allowed. Ensure CORS origins are strictly limited in production to the actual frontend domain.

## Fragile Areas

- **Email Dispatch:** Currently synchronous in some paths or relies on FastAPI `BackgroundTasks` which can lose data if the server restarts. Consider a dedicated task queue (Celery/RabbitMQ) if volume increases.
- **Audit Logging:** Implemented manually in routers. Could be centralized via middleware or decorators to ensure consistency and prevent missing logs.

## Testing Gaps

- **Integration Edge Cases:** Tests focus on happy paths and basic errors. More robust testing needed for race conditions and concurrent access.
- **Database Migrations:** `test_migrations.py` exists but needs to ensure that migrations are actually reversible and don't lose data.

---

*Concerns analysis: 2026-05-08*
*Update as issues are identified or resolved*
