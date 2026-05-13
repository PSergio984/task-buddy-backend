<!-- generated-by: gsd-doc-writer -->
# Integrations

**Analysis Date:** 2026-05-12

## Databases & Caching

**PostgreSQL:**
- **Purpose:** Primary relational data store.
- **Library:** `asyncpg` (async driver), `sqlalchemy`.
- **Migrations:** Managed via Alembic.
- **Config:** `DATABASE_URL` in `.env`.

**Redis:**
- **Purpose:** Message broker for Celery and high-speed data caching.
- **Config:** `REDIS_URL`.
- **Library:** `redis`.

**SQLite:**
- **Purpose:** Local development and CI testing.
- **Library:** `aiosqlite`.

## Background Processing

**Celery:**
- **Purpose:** Handling long-running or distributed tasks (Emails, Push Notifications, Cleanup).
- **Architecture:** Worker process separate from the API server.
- **Broker:** Redis.
- **Configuration:** `app/celery_app.py`.

## External Services

**Backblaze B2:**
- **Purpose:** Cloud object storage for file uploads and assets.
- **Library:** `b2sdk`.
- **Integration:** `app/libs/b2/`.
- **Required Config:** `B2_KEY_ID`, `B2_APPLICATION_KEY`, `B2_BUCKET_NAME`.

**Web Push:**
- **Purpose:** Real-time browser/mobile push notifications.
- **Protocol:** VAPID.
- **Library:** `pywebpush`.
- **Integration:** `app/api/routers/notifications.py`.

**Brevo (Transactional Email):**
- **Purpose:** OTP, password resets, and user notifications.
- **Type:** REST API / SMTP.
- **Integration:** `app/tasks.py`.

**Sentry:**
- **Purpose:** Error tracking and performance monitoring.
- **Library:** `sentry-sdk`.
- **Config:** `SENTRY_DSN`.
- **Scope:** API and Worker errors are captured.

## Security & Protocols

**JWT (JSON Web Tokens):**
- **Purpose:** Stateless authentication.
- **Library:** `python-jose`.
- **Flow:** Bearer token authentication in `app/dependencies.py`.

**Argon2:**
- **Purpose:** State-of-the-art password hashing.
- **Library:** `argon2-cffi`.

**OpenAPI (Swagger):**
- **Purpose:** API documentation and client generation.
- **Endpoints:** `/docs` and `/redoc`.

---

*Integrations analysis: 2026-05-12*
*Update when adding or removing external service dependencies*
