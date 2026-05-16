# Research: Phase 5 - Real-time Sync & Offline Mode

## Transport Layer: SSE vs WebSockets

**Current State:** Basic SSE implemented in `app/api/routers/realtime.py` using a custom in-memory Broadcaster.

**Recommendation:**
- **Server-to-Client:** Continue using SSE for notifications and state change alerts. It's more lightweight, supports automatic reconnection, and works over standard HTTP/2.
- **Client-to-Server:** Use standard REST APIs (POST/PUT) for syncing local changes. This is more reliable for offline reconciliation as it allows for clear HTTP status codes and retry logic.
- **Distributed Support:** Replace the custom `Broadcaster` with the `broadcaster` library using the Redis backend. This ensures that a task update on Worker A correctly notifies a client connected to Worker B.

## Distributed Broadcasting (Redis)

To support multiple backend workers, the broadcaster must use Redis Pub/Sub.

```python
from broadcaster import Broadcast
from app.config import REDIS_URL

broadcast = Broadcast(REDIS_URL)

# Usage in FastAPI
@app.on_event("startup")
async def startup():
    await broadcast.connect()

@app.on_event("shutdown")
async def shutdown():
    await broadcast.disconnect()
```

## Offline Reconciliation: Last Write Wins (LWW)

To fulfill **SYNC-02**, we will implement a "Last Write Wins" strategy with server-authoritative timestamps.

### 1. Database Schema Requirements
All syncable entities (Tasks, Projects) must have:
- `updated_at`: DateTime (UTC, server-managed).
- `version`: Integer (incremented on every update).
- `client_updated_at`: DateTime (optional, for debugging client intent).

### 2. Conflict Resolution Logic
When the server receives an update for an entity:
1. Fetch the existing entity.
2. If `incoming.updated_at` (provided by client) is older than `existing.updated_at`, the server's version is newer.
3. **Resolution:**
   - If strict LWW: Reject the update and return the current server state (Conflict 409).
   - If "Silent LWW": Overwrite only if the client's timestamp is newer.
4. **Batch Sync:** Clients should send a list of changes. The server processes them sequentially.

## SYNC Requirements Implementation Plan

| ID | Requirement | Technical Approach |
|----|-------------|-------------------|
| SYNC-01 | Real-time Sync | Redis-backed SSE for server-push. REST for client-push. |
| SYNC-02 | Conflict Resolution | `updated_at` comparison on server. Return 409 Conflict with current state for manual resolution or strict LWW overwrite. |
| SYNC-03 | Exponential Backoff | Client-side responsibility, but server should provide a `Retry-After` hint on 503/429. |
| SYNC-04 | UI Sync Indicators | Provide a `/health/sync` or similar heartbeat endpoint. SSE "ping" events (already present). |

## Next Steps for Planning
1. **Model Audit:** Ensure `Tasks` and `Projects` have proper `updated_at` and `version` fields.
2. **Broadcaster Refactor:** Move to the `broadcaster` library.
3. **Sync Endpoint:** Design a `/sync` endpoint that handles batches of local changes.
