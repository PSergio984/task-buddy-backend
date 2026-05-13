# Concerns

**Analysis Date:** 2026-05-13

## Technical Debt

- **CRUD Commit Bloat:** Several CRUD functions in `app/crud/` handle their own commits, which makes composing multiple CRUD operations into a single transaction difficult.
- **Duplicate Literals:** Hardcoded strings in `app/api/routers/tasks.py` for status values and category names. Should be moved to Enums or Constants.

## Security

- **Hardcoded Secret Placeholder:** `.env.example` and potentially some early code versions might have shared "your-secret-key-here" placeholders. Ensure `SECRET_KEY` is always generated and rotated in production.
- **CORS Configuration:** `localhost` is currently allowed. Ensure CORS origins are strictly limited in production to the actual frontend domain.

## Fragile Areas

- **Email Dispatch:** Integrated with Celery/Redis for reliable background processing.
- **Audit Logging:** Centralized via the `@audit_log` decorator. Ensure all new mutating CRUD operations are decorated.

## Testing Gaps

- **Integration Edge Cases:** Tests focus on happy paths and basic errors. More robust testing needed for race conditions and concurrent access.
- **Database Migrations:** `test_migrations.py` exists but needs to ensure that migrations are actually reversible and don't lose data.

---

*Concerns analysis: 2026-05-13*
*Update as issues are identified or resolved*
