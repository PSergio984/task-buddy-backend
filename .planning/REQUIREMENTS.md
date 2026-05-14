# Requirements: Task Buddy Backend

**Defined:** 2026-05-08
**Core Value:** Reliable and auditable task management state for the Task Buddy ecosystem.

## v1 Requirements

Requirements focused on quality hardening, security, and scalability of the existing system.

### Refinement & Standards (REFI)

- [ ] **REFI-01**: CRUD functions in `app/crud/` do not perform `db.commit()` or `db.refresh()`.
- [ ] **REFI-02**: All API status codes, tags, and common literals are defined as Enums or Constants.
- [ ] **REFI-03**: Database models use SQLAlchemy 2.0 style type annotations consistently.

### Security (SECU)

- [ ] **SECU-01**: Password hashing upgraded to Argon2.
- [ ] **SECU-02**: CORS policies strictly limited to trusted domains.
- [ ] **SECU-03**: HTTP Security Headers (HSTS, CSP, etc.) enforced on all responses.

### Auditing (AUDI)

- [ ] **AUDI-01**: Mutation logging is centralized (e.g., via a base model, decorator, or middleware).
- [ ] **AUDI-02**: Audit trail includes old/new values for critical fields.

### Reliability & Stability (RELI/IDEO)

- [ ] **RELI-01**: Email dispatch is asynchronous and resilient to server restarts (e.g., via background workers).
- [ ] **RELI-02**: Automated tests cover database migration rollbacks.
- [ ] **RELI-03**: Automated tests simulate concurrent mutation requests to verify transaction isolation.
- [ ] **IDEO-01**: Requests with `X-Idempotency-Key` return cached responses for the same key within 1 hour.
- [ ] **IDEO-02**: Concurrent requests with the same idempotency key are handled atomically to prevent race conditions.

## v2 Requirements (Deferred)

- [ ] **NOTI-01**: Real-time push notifications via WebSockets.
- [ ] **INTE-01**: Integration with third-party task providers (e.g., Jira, Trello).

### Real-time Sync & Offline Mode (SYNC)

- [ ] **SYNC-01**: Support for real-time synchronization using WebSockets or SSE with connection heartbeats.
- [ ] **SYNC-02**: Conflict resolution strategy using "Last Write Wins" or server-authoritative merge rules for offline reconciliation.
- [ ] **SYNC-03**: Exponential backoff and jitter for reconnection and data re-sync procedures on network restore.
- [ ] **SYNC-04**: UI-level status indicators for syncing, offline, and pending conflict states.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Frontend UI | Separate repository |
| Social Networking | Not core to the "Buddy" (which refers to the AI/helper aspect) |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| REFI-01 | Phase 1 | Pending |
| REFI-02 | Phase 1 | Pending |
| REFI-03 | Phase 1 | Pending |
| SECU-01 | Phase 2 | Pending |
| SECU-02 | Phase 2 | Pending |
| SECU-03 | Phase 2 | Pending |
| AUDI-01 | Phase 3 | Pending |
| AUDI-02 | Phase 3 | Pending |
| RELI-01 | Phase 4 | Pending |
| RELI-02 | Phase 4 | Pending |
| RELI-03 | Phase 4 | Pending |
| IDEO-01 | Phase 3.9 | In Progress |
| IDEO-02 | Phase 3.9 | In Progress |
| SYNC-01 | Phase 5 | Not Started |
| SYNC-02 | Phase 5 | Not Started |
| SYNC-03 | Phase 5 | Not Started |
| SYNC-04 | Phase 5 | Not Started |

**Coverage:**
- v1 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-08*
*Last updated: 2026-05-08 after initial definition*
