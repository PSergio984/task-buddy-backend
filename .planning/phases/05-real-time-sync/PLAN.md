# Plan: Phase 5 - Real-time Sync & Offline Mode

Implementation of distributed synchronization and conflict resolution to support offline usage and multi-device consistency.

## 1. Schema Hardening
- [ ] **Task 5.1**: Add `updated_at` column to `tbl_tasks`, `tbl_subtasks`, and `tbl_projects`.
- [ ] **Task 5.2**: Add `version` (int) or `server_version` to track revisions for conflict detection.
- [ ] **Task 5.3**: Generate and run Alembic migration for schema changes.

## 2. Distributed Transport (SSE + Redis)
- [ ] **Task 5.4**: Refactor `app/libs/broadcaster.py` to use the `broadcaster` library with Redis backend.
- [ ] **Task 5.5**: Update `app/main.py` lifecycle hooks (`startup`, `shutdown`) for Redis connection management.
- [ ] **Task 5.6**: Update `app/api/routers/realtime.py` to use the new distributed broadcaster.

## 3. Real-time Event Emission
- [ ] **Task 5.7**: Add event emission logic to Task CRUD operations (Create, Update, Delete).
- [ ] **Task 5.8**: Add event emission logic to Project CRUD operations.
- [ ] **Task 5.9**: Ensure events include the resource type, ID, and latest version/timestamp.

## 4. Conflict Resolution & Sync API
- [ ] **Task 5.10**: Implement a new `/api/v1/sync` endpoint for batch synchronization.
- [ ] **Task 5.11**: Implement "Last Write Wins" (LWW) comparison logic in the sync handler.
- [ ] **Task 5.12**: Implement error handling for invalid timestamps or clock skew (logical ordering).

## 5. Verification & Testing
- [ ] **Task 5.13**: Write unit tests for the LWW conflict resolution logic.
- [ ] **Task 5.14**: Write integration tests for multi-worker synchronization via Redis.
- [ ] **Task 5.15**: Verify SSE heartbeats and reconnection handling under load.

## Success Criteria
- [ ] Multi-worker SSE: An update on Worker A triggers an event on Worker B's subscribers.
- [ ] Offline Recovery: Client can send a batch of changes after being offline, and server correctly merges them using LWW.
- [ ] No Data Loss: Concurrent updates to different tasks do not interfere.
- [ ] Zero Orphan Records: Deleted resources are handled in the sync state.
