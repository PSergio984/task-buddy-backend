# Phase 5 Context: Real-time Sync & Offline Mode

## Overview
Phase 5 implements a robust synchronization engine and a real-time event system. This enables the frontend to handle offline state gracefully and ensures multi-device consistency through conflict resolution and distributed event broadcasting.

## Decisions

### 1. Schema Hardening (Conflict Resolution Foundation)
- **Problem:** Concurrent updates from offline clients currently cause data loss (last write to the DB wins, but without version tracking).
- **Decision:** 
    - Add `version: Mapped[int]` (default 1) and `updated_at: Mapped[datetime]` (server-managed) to `Task`, `SubTask`, and `Project` models.
    - `updated_at` must use microsecond precision (PostgreSQL `TIMESTAMPTZ(6)` or similar).
    - Incremental versioning: Every update increments the version.

### 2. Distributed Transport (SSE + Redis)
- **Problem:** The current `Broadcaster` is in-memory and fails in multi-worker environments (e.g., Render with Gunicorn/Uvicorn).
- **Decision:**
    - Refactor `Broadcaster` to use **Redis Pub/Sub**.
    - Backend workers publish events to Redis channels (scoped by `user_id`).
    - The SSE `/realtime/stream` endpoint listens to these Redis channels.
    - Choice of SSE over WebSockets: Simpler for one-way server-to-client updates and more resilient over HTTP/2.

### 3. Real-time Event Emission
- **Decision:**
    - Integrate `broadcaster.notify(user_id, event_json)` into all mutating CRUD operations (Task/Project Create, Update, Delete).
    - Event payload format: `{"type": "TASK_UPDATED", "id": 123, "version": 5, "updated_at": "..."}`.

### 4. Sync API (Offline Reconciliation)
- **Decision:**
    - Implement `/api/v1/sync` (POST) for batch synchronization.
    - Conflict Strategy: **Last Write Wins (LWW)** based on the client's `updated_at` timestamp vs the server's.
    - Protocol:
        1. Client sends a list of locally mutated items.
        2. Server compares versions/timestamps.
        3. Server returns "Accepted" or "Conflict" (with the latest server state).

## Success Criteria
- [ ] Schema: Models include `version` and `updated_at`.
- [ ] Transport: SSE works across multiple backend instances using Redis.
- [ ] Performance: SSE connection has a heartbeat (ping) every 30s.
- [ ] Reliability: Batch sync correctly resolves conflicts for a client that has been offline for 24 hours.
- [ ] Efficiency: Sync API supports up to 50 items per request.

## Out of Scope
- Full CRDT (Conflict-free Replicated Data Types) implementation.
- Real-time collaborative editing (Google Docs style).
- Client-side implementation (handled by the frontend agent).
