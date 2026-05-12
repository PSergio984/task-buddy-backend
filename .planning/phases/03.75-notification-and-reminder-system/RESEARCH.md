# Phase 3.75: Notification & Reminder System - Research

**Researched:** 2026-05-12
**Domain:** Notifications, Background Workers, WebPush
**Confidence:** HIGH

## Summary

This research establishes the architecture and implementation plan for a multi-channel notification and reminder system. The system will support Email, In-App, and Browser Push notifications. Reminders are triggered by a Celery Beat periodic task that scans for tasks nearing their due date or that are overdue.

**Primary recommendation:** Use `pywebpush` for standard-compliant WebPush encryption and delivery, integrated with the existing Celery worker infrastructure. Use a `Notification` table to persist history and prevent duplicate reminders.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Notification Channels:**
  - **Email:** Primary channel for critical reminders. Reuses Brevo/Celery infrastructure.
  - **In-App:** Real-time (poll-based initially) notifications in the dashboard. Requires `is_read` status.
  - **Push:** WebPush (PWA) support. Requires storing browser subscriptions.

### 2. Data Models
- **Notification Model:**
  - `id`: PK
  - `user_id`: FK to User
  - `type`: Enum (REMINDER_BEFORE, REMINDER_DUE, REMINDER_OVERDUE, SYSTEM)
  - `title`: String
  - `message`: Text
  - `is_read`: Boolean (default False)
  - `action_url`: Optional String (e.g., link to the task)
  - `created_at`: Timestamp
- **PushSubscription Model:**
  - `id`: PK
  - `user_id`: FK to User
  - `endpoint`: String (Unique)
  - `p256dh`: String
  - `auth`: String
  - `created_at`: Timestamp

### 3. Reminder Logic
- **Worker:** Celery Beat task `app.tasks.process_reminders` running every 10 minutes.
- **Scenarios:**
  - **Before Deadline:** 1 hour before `due_date`.
  - **At Deadline:** Exactly when `due_date` passes.
  - **Overdue:** 24 hours after `due_date` if still not completed.
- **Tracking:** Use the `Notification` table to prevent duplicate reminders for the same task/type/time-window.

### 4. API Endpoints
- `GET /notifications/`: List user's notifications (paged, filter by `is_read`).
- `PATCH /notifications/{id}/read`: Mark as read.
- `POST /notifications/push-subscription`: Register/update browser push subscription.

### the agent's Discretion
- Library selection for WebPush (pywebpush recommended).
- VAPID key generation and storage strategy.
- Notification batching/enqueueing logic.

### Deferred Ideas (OUT OF SCOPE)
- Real-time WebSockets (sticky sessions / horizontal scaling complexity).
- SMS notifications.
- Mobile native Push (FCM/APNs) - focus is on PWA/WebPush.
</user_constraints>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reminder Scanning | API / Backend | Celery Beat | Periodic checks must run server-side. |
| Notification Persistence | Database | API / Backend | History and state (is_read) must be durable. |
| Push Encryption | API / Backend | — | VAPID/AES-GCM encryption happens on the server. |
| Email Delivery | External (Brevo) | API / Backend | Reliable transactional email via SMTP/API. |
| Push Delivery | External (Push Service) | Browser | Browsers use OS-level push services (FCM, Mozilla, etc.). |
| In-App Display | Browser / Client | — | Frontend renders the notification list. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pywebpush | 1.14.0 | WebPush encryption | Industry standard for Python WebPush; handles VAPID and AES-GCM. |
| celery | 5.3.6 | Background processing | Already integrated; mandatory for periodic scanning. |
| httpx | 0.27.0 | API communication | Used for Brevo API and potentially push delivery. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| cryptography | 42.0.x | Key generation | Required by pywebpush for VAPID signing. |
| pydantic | 2.6.x | Schema validation | Standard for FastAPI models and data validation. |

**Installation:**
```bash
# cryptography is usually a dependency of pywebpush
pip install pywebpush
```

## Architecture Patterns

### System Architecture Diagram
1. **Celery Beat** triggers `process_reminders` every 10 mins.
2. **Scanner** queries DB for tasks needing reminders based on `due_date`.
3. **Deduplicator** checks `tbl_notifications` to see if a reminder was already sent for that task/type.
4. **Dispatcher** enqueues individual `send_notification` tasks for each channel (Email, Push, In-App).
5. **In-App** creation is just a DB insert into `tbl_notifications`.
6. **Push Task** fetches `tbl_push_subscriptions` and uses `pywebpush` to send.
7. **Email Task** uses `app.tasks.send_brevo_email`.

### Recommended Project Structure
```
app/
├── api/routers/
│   └── notifications.py    # New router for notification management
├── crud/
│   └── notification.py     # CRUD logic for notifications & subscriptions
├── models/
│   └── notification.py     # Notification and PushSubscription ORM models
├── schemas/
│   └── notification.py     # Pydantic schemas for API
└── tasks.py                # Add process_reminders and send_push_notification
```

### Pattern 1: Periodic Scanning with Time Windows
**What:** Use fixed time windows to find tasks that fall into specific reminder categories.
**When to use:** Every Celery Beat execution.
**Example:**
```python
# Approximate logic for 10-minute intervals
now = datetime.utcnow()
window_start = now + timedelta(minutes=50)
window_end = now + timedelta(minutes=60)
# Query tasks where due_date BETWEEN window_start AND window_end
```

### Anti-Patterns to Avoid
- **Scanning entire Task table:** Always filter by `completed=False` and indexed `due_date`.
- **Synchronous Push Delivery:** WebPush calls can be slow or timeout; always use Celery.
- **Leaking VAPID Private Key:** Never expose the private key via any API or frontend code.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Push Encryption | AES-GCM + VAPID signing | `pywebpush` | Extremely complex crypto; easy to get wrong and be rejected by browser. |
| Scheduling | Custom loop or sleep | Celery Beat | Reliability, persistence, and decoupling from main process. |
| Email Delivery | Direct SMTP server | Brevo (existing) | Deliverability, reputation management, and analytics. |

## Common Pitfalls

### Pitfall 1: Browser Subscription Expiry (410 Gone)
**What goes wrong:** The push service returns a 410 Gone status code.
**How to avoid:** Catch `WebPushException` in the Celery task; if status is 410, delete the subscription from the DB immediately.

### Pitfall 2: Timezone Confusion
**What goes wrong:** Reminders sent at the wrong time due to UTC vs Local mismatch.
**How to avoid:** Store all `due_date` as `TIMESTAMPTZ` (UTC) and ensure Celery Beat is configured for UTC.

### Pitfall 3: Massive Enqueueing
**What goes wrong:** Scanning finds 10,000 tasks and tries to send them all at once, overwhelming the worker pool.
**How to avoid:** Use Celery rate limiting or task chunking if the user base grows significantly.

## Code Examples

### VAPID Key Generation
```python
# To be run once to generate keys for .env
from pywebpush import vapid_keys
keys = vapid_keys.generate_vapid_keys()
print(f"Public: {keys['public_key']}")
print(f"Private: {keys['private_key']}")
```

### Sending a Push Notification (pywebpush)
```python
# Source: pywebpush docs
from pywebpush import webpush, WebPushException

def send_push(subscription_info, data, private_key):
    try:
        webpush(
            subscription_info=subscription_info,
            data=data,
            vapid_private_key=private_key,
            vapid_claims={"sub": "mailto:admin@taskbuddy.com"}
        )
    except WebPushException as ex:
        if ex.response.status_code == 410:
            # Handle expired subscription
            pass
```

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Redis | Celery Broker/Backend | ✓ | 7.x | — |
| PostgreSQL | Data Persistence | ✓ | 15.x | — |
| Brevo | Email Delivery | ✓ | — | SMTP Fallback |
| pywebpush | Push Notifications | ✗ | — | Install via pip |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | pyproject.toml |
| Quick run command | `pytest tests/test_notifications.py` |
| Full suite command | `pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NOTIF-01 | Create Notification record | Unit | `pytest tests/test_notifications.py::test_create_notification` | ❌ |
| NOTIF-02 | Subscribe to Push | Integration | `pytest tests/test_notifications.py::test_push_subscription` | ❌ |
| NOTIF-03 | Periodic Scan Logic | Integration | `pytest tests/test_notifications.py::test_reminder_scanning` | ❌ |
| NOTIF-04 | Mark as Read | API | `pytest tests/routers/test_notifications.py` | ❌ |

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | Pydantic validation for push subscription JSON. |
| V6 Cryptography | yes | Use `pywebpush` (AES-GCM/VAPID) — no custom crypto. |
| V12 Data Protection | yes | Encrypt or protect PushSubscription secrets in DB. |

### Known Threat Patterns for WebPush

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Subscription Hijacking | Spoofing | Ensure subscription endpoints are only registered by authenticated owners. |
| Notification Spam | Information Disclosure | Rate limit subscription registration and notification sending. |

## Sources

### Primary (HIGH confidence)
- `pywebpush` - [VAPID support and one-call encryption](https://github.com/web-push-libs/pywebpush)
- `celery` - [Periodic Tasks Documentation](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)

### Secondary (MEDIUM confidence)
- MDN Web Docs - [Using the Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Libraries are mature and well-documented.
- Architecture: HIGH - Fits well into existing Celery/FastAPI structure.
- Pitfalls: MEDIUM - Browser specific behaviors can vary.

**Research date:** 2026-05-12
**Valid until:** 2026-06-12
