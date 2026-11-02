# 0001 — In-process background execution; no external worker

**Status**: accepted (2026-08-26)

Task Buddy's original roadmap planned a Celery/Redis worker for email delivery, but by the time Phase 4 started, every background need was already met in-process: transactional emails send via FastAPI `BackgroundTasks` through the Brevo HTTP API with an SMTP fallback (`app/tasks.py`), and recurring sweeps (reminders, history backfill) run as `asyncio.create_task` loops started on app lifespan. We decided to make in-process execution the platform of record and drop the external-worker premise rather than introduce Celery/Redis.

## Decision

- All background work runs in-process: FastAPI `BackgroundTasks` for email sends, lifespan `asyncio.create_task` loops for recurring sweeps.
- No Celery/Redis worker or Render Background Worker is introduced at pilot scale (~90–100 DAU).
- Transactional email delivery is explicitly best-effort with user-driven recovery (resend/re-request endpoints).
- If deliverability ever demands more, the escape hatch is an outbox table swept by the existing lifespan loops — not a worker reintroduction.
- Any correctness-critical shared state must live in Postgres, not process memory or Redis, because every Render deploy overlaps two live instances for minutes.

## Considered Options

- **Celery/Redis worker (original plan)** — rejected: at ~90–100 DAU pilot scale nothing demands durable queues; it adds a broker, a second service on Render, and an ops surface for zero current payoff.
- **Render Background Workers + queue** — rejected for the same scale reasons.
- **In-process execution (chosen)** — free, already shipped, and adequate given user-driven recovery paths for lost emails and UTC-day self-healing for lost work.

## Consequences

- In-flight background work dies when Render kills the instance (SIGTERM after deploy cutover, SIGKILL after grace; free-tier instances restart without warning). We accept this per-class: emails are explicitly best-effort with user-driven recovery (resend/re-request); sweeps re-run idempotently on next boot.
- The free tier caps web services at one steady-state instance, but every deploy deterministically overlaps two live instances for minutes — so any correctness-critical shared state must live in Postgres, not process memory or Redis (see ADR 0002).
- If deliverability complaints ever arrive, the documented escape hatch is an outbox table swept by the existing lifespan loops — not a worker reintroduction.
