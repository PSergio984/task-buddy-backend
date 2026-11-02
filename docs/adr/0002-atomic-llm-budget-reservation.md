# 0002 — Atomic LLM budget reservation via Postgres conditional UPDATE

**Status**: accepted (2026-08-26)

The per-user daily LLM token budget was enforced by check-before-call: each LLM endpoint summed today's instrumented token usage and compared it to the cap, then called the provider. Two concurrent requests could both pass the check and overshoot (race deferred from the voice-assistant review). We decided to gate every LLM call behind an atomic reservation in Postgres: a per-user-per-day counter row incremented by a single conditional `UPDATE … SET reserved_tokens = reserved_tokens + :est WHERE reserved_tokens + :est <= :cap RETURNING` — zero rows updated maps to the existing 429 path.

## Decision

- The daily LLM budget gate is a Postgres reservation counter keyed `(user_id, UTC day)`, incremented by one atomic conditional UPDATE; zero rows updated → 429.
- Locks held across the provider call and Redis-backed durable counters are rejected.
- Reservation sizes are fixed per-endpoint config constants, set generously (~2× observed mean).
- On success the counter reconciles by `actual − estimate`; on provider error it refunds fully; process death mid-call leaks the estimate until UTC day rollover (bounded, accepted).
- The seam is explicit `reserve_llm_budget` / `reconcile_llm_usage` / `refund_llm_reservation` functions in one budget module, called at all four LLM endpoints (`/plan`, `/breakdown`, `/voice/plan`, `/tasks/{id}/knowledge/ask`); a budget ≤ 0 still disables the cap entirely.
- Future LLM endpoints must follow the same reservation convention, documented for contributors.

## Considered Options

- **`SELECT … FOR UPDATE` / advisory locks held across the provider call** — rejected: the lock would be held across a multi-second external HTTP call, serializing a user's requests while pinning a DB transaction open.
- **Redis-backed counter** — rejected for *durable* budget state: instances die on deploy overlap, stranding reservations; Redis stays in its lane (ephemeral idempotency locks), Postgres is the only coordination point two overlapping deploy instances share.
- **Derived-SUM check (status quo)** — rejected: a live aggregate cannot express compare-and-set; atomicity requires a materialized counter.
- **Postgres reservation counter (chosen)** — atomic, lock-free across the LLM call, no new infrastructure, multi-instance-safe.

## Consequences

- Reservations use fixed per-endpoint estimate constants (~2× observed mean); precision is immaterial at the 200k/day cap.
- On success the counter reconciles by `actual − estimate`; on provider error it refunds fully; if the process dies mid-call the estimate leaks until UTC day rollover — bounded, self-healing, accepted.
- The gate lives as explicit `reserve_llm_budget` / `reconcile_llm_usage` / `refund_llm_reservation` functions in one budget module, called at the four LLM endpoints (`/plan`, `/breakdown`, `/voice/plan`, `/tasks/{id}/knowledge/ask`); future LLM endpoints must follow the same convention (documented in code-reference docs). A budget ≤ 0 still disables the cap entirely.
