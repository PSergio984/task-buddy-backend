# Fix Rate Limiting and Idempotency Interaction Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix rate limiting to be consistent across workers, provide standard headers, and prevent 429 responses from being cached by idempotency middleware.

**Architecture:**
1. Update `app/limiter.py` to use Redis storage via `config.REDIS_URL`.
2. Add `SlowAPIMiddleware` to `app/main.py`.
3. Update `IdempotencyMiddleware` in `app/middleware/idempotency.py` to skip caching for 429 status codes.

**Tech Stack:** FastAPI, SlowAPI, Redis

---

### Task 1: Update Limiter Storage to Redis

**Files:**
- Modify: `app/limiter.py`

- [ ] **Step 1: Update limiter configuration to use storage_uri**

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import config

limiter = Limiter(
    key_func=get_remote_address, 
    enabled=config.RATE_LIMIT_ENABLED,
    storage_uri=config.REDIS_URL
)
```

- [ ] **Step 2: Verify with existing tests**

Run: `pytest tests/test_security_hardening.py`
Expected: PASS (as long as Redis is available or mocked by existing tests)
*Note: Existing tests mock `get_remote_address`, but they don't mock the storage. Slowapi will try to connect to Redis if storage_uri is provided. If Redis is not available during tests, we might need to use a fallback or mock it.*

Wait, in `TestConfig`, `REDIS_URL` might be something like `redis://localhost:6379/0`.
If Redis is not running during local tests, this might fail.
However, `app.config` uses `REDIS_URL` from env.

Let's check if I should use a fallback for tests.
Actually, it's better to keep it consistent.

### Task 2: Add SlowAPIMiddleware

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Import SlowAPIMiddleware**

```python
from slowapi.middleware import SlowAPIMiddleware
```

- [ ] **Step 2: Add middleware to app**

```python
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware) # Add this
```

- [ ] **Step 3: Run repro script to check for headers**

Run: `python repro_rate_limit.py`
Expected: Headers should now contain `x-ratelimit-*` entries.

### Task 3: Fix Idempotency Caching for 429 Responses

**Files:**
- Modify: `app/middleware/idempotency.py`

- [ ] **Step 1: Modify _handle_response to skip 429**

```python
    async def _handle_response(self, redis_client, cache_key, response):
        if response.status_code >= 500 or response.status_code == 429:
            await redis_client.delete(cache_key)
            return response
        ...
```

- [ ] **Step 2: Create a new test to verify this behavior**

Create: `tests/test_idempotency_ratelimit.py`
```python
import pytest
from httpx import AsyncClient
from app.main import app
import uuid

@pytest.mark.asyncio
async def test_ratelimit_not_cached_by_idempotency(authenticated_async_client: AsyncClient, mocker):
    # Enable limiter
    app.state.limiter.enabled = True
    try:
        # Mock remote address
        mocker.patch("app.limiter.get_remote_address", return_value="1.2.3.4")
        
        idempotency_key = str(uuid.uuid4())
        headers = {"X-Idempotency-Key": idempotency_key}
        
        # 1. Hit limit
        for _ in range(10): # Project limit is 10
            await authenticated_async_client.post("/api/v1/projects/", json={"name": str(uuid.uuid4())})
            
        # 2. This one should be 429
        response = await authenticated_async_client.post(
            "/api/v1/projects/", 
            json={"name": "test"}, 
            headers=headers
        )
        assert response.status_code == 429
        
        # 3. Reset limiter manually
        app.state.limiter.reset()
        
        # 4. Try again with same idempotency key - should NOT be 429 anymore
        response = await authenticated_async_client.post(
            "/api/v1/projects/", 
            json={"name": "test"}, 
            headers=headers
        )
        assert response.status_code != 429
    finally:
        app.state.limiter.enabled = False
```

- [ ] **Step 3: Run the new test**

Run: `pytest tests/test_idempotency_ratelimit.py`
Expected: PASS

### Task 4: Verification and Clean-up

- [ ] **Step 1: Run all security tests**

Run: `pytest tests/test_security_hardening.py tests/test_idempotency.py`

- [ ] **Step 2: Remove reproduction scripts**

Run: `rm repro_rate_limit.py repro_idempotency_ratelimit.py`
