# Roadmap: Task Buddy Backend

## Overview

The journey starts with refining the architectural core (transaction management and constants) to ensure a stable foundation. We then move into security hardening and automated auditing to protect user data and ensure accountability. Finally, we scale the reliability by implementing background task queues and advanced integration tests.

## Phases

- [x] **Phase 1: Architecture Refinement** - Standardize CRUD transactions and API literals.
- [x] **Phase 2: Security Hardening** - Upgrade hashing and enforce strict security headers/CORS.
- [/] **Phase 3: Centralized Auditing** - Automate mutation logging for all core entities.
- [ ] **Phase 4: Reliability & Scale** - Implement background task workers and stress-test transactions.

## Phase Details

### Phase 1: Architecture Refinement
**Goal**: Decouple CRUD from transaction commits and standardize API constants.
**Depends on**: Nothing
**Requirements**: REFI-01, REFI-02, REFI-03
**Success Criteria**:
  1. CRUD functions can be composed into a single transaction.
  2. No hardcoded status strings in routers.
  3. All SQLAlchemy models use 2.0 type hints.
**Plans**: 2 plans

Plans:
- [ ] 01-01: Refactor CRUD methods to remove `db.commit()` and `db.refresh()`.
- [ ] 01-02: Standardize Enums and Constants across all routers.

### Phase 2: Security Hardening
**Goal**: Implement industry-standard security practices for data and networking.
**Depends on**: Phase 1
**Requirements**: SECU-01, SECU-02, SECU-03
**Success Criteria**:
  1. Argon2 hashing used for all new passwords.
  2. CORS limited to configured trusted origins.
  3. API responses include standard security headers.
**Plans**: 1 plan

Plans:
- [ ] 02-01: Security middleware and password hashing upgrade.

### Phase 3: Centralized Auditing
**Goal**: Ensure every state change is automatically recorded with high fidelity.
**Depends on**: Phase 2
**Requirements**: AUDI-01, AUDI-02
**Success Criteria**:
  1. Mutation logging happens automatically on CRUD calls.
  2. Audit logs capture field-level diffs.
**Plans**: 1 plan

Plans:
- [ ] 03-01: Implement automated audit logging decorator/middleware.

### Phase 4: Reliability & Scale
**Goal**: Modernize integration handling and verify system resilience.
**Depends on**: Phase 3
**Requirements**: RELI-01, RELI-02, RELI-03
**Success Criteria**:
  1. Emails are sent via background worker without blocking request.
  2. Database migrations are verified reversible.
  3. No deadlocks or race conditions found under concurrent load.
**Plans**: 2 plans

Plans:
- [ ] 04-01: Set up background worker (e.g., Celery/Redis) for emails.
- [ ] 04-02: Stress and concurrency integration test suite.

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Architecture Refinement | 2/2 | Completed | 2026-05-08 |
| 2. Security Hardening | 1/1 | Completed | 2026-05-08 |
| 3. Centralized Auditing | 0/1 | In-progress | - |
| 4. Reliability & Scale | 0/2 | Not started | - |

---
*Roadmap defined: 2026-05-08*
*Last updated: 2026-05-08 after initial definition*
