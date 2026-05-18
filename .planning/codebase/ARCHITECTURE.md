<!-- generated-by: gsd-doc-writer -->
# Architecture

**Analysis Date:** 2026-05-18

## Pattern Overview
**Overall:** Layered Monolith with Distributed Task Processing.

## Background Processing Architecture
- **Task Queue:** Celery handles asynchronous jobs (Emails, Push Notifications, Cleanup).
- **Broker/Backend:** Redis serves as the message broker and result backend.
- **Notification Pipeline:** 
  1. Business logic triggers a notification (e.g., task due soon).
  2. Data is persisted in the `Notification` table.
  3. A Celery task is dispatched to the Redis queue.
  4. Workers pick up tasks and integrate with Brevo (Email) or VAPID (Web Push).

## Key Abstractions
- **Idempotency:** Managed via `IdempotencyMiddleware` and `@idempotent` decorator in `app/middleware/idempotency.py`, using Redis to track request keys.
- **Audit Logging:** `@audit_log` decorator in `app/libs/audit.py` captures state changes.
