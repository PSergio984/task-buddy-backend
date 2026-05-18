<!-- generated-by: gsd-doc-writer -->
# Integrations

## Background Processing
**Celery & Redis:**
- **Redis:** Primary broker for Celery and storage for Idempotency keys (`app/middleware/idempotency.py`).
- **Celery:** Distributed task execution (`app/tasks.py`).

## External Services
**Brevo (Email):**
- **Purpose:** Transactional emails (Reminders, OTP).
- **Integration:** Triggered via Celery tasks using API-based delivery.

**VAPID (Web Push):**
- **Purpose:** Browser-based notifications.
- **Integration:** Uses `pywebpush` to send alerts to subscribed user endpoints.
