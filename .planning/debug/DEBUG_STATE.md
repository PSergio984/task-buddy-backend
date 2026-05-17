# Debug Session: Rate Limiting and Idempotency Issues

## Issues Reported
1. Rate limiting "isn't appearing" (headers missing? limits not enforcing?).
2. Idempotency interaction with login/signup questioned.
3. Middleware order might be causing bypass.

## Investigation Notes
- `SlowAPIMiddleware` is added before `IdempotencyMiddleware`. In FastAPI, this means `IdempotencyMiddleware` runs FIRST.
- If `IdempotencyMiddleware` returns a cached response, it bypasses `SlowAPIMiddleware`.
- `IdempotencyMiddleware` scopes "anonymous" users to a single "anonymous" bucket, which is a security risk (response leakage).
- `limiter` in `app/limiter.py` does not have `headers_enabled=True`.
- Deployment on Render might need `X-Forwarded-For` handling for IP-based rate limiting.

## Hypotheses
1. `SlowAPIMiddleware` missing headers because `headers_enabled` is False.
2. `SlowAPIMiddleware` is bypassed by `IdempotencyMiddleware`.
3. `IdempotencyMiddleware` allows anonymous response leakage.

## Plan
1. [ ] Enable headers in `app/limiter.py`.
2. [ ] Reorder middleware in `app/main.py`.
3. [ ] Harden `IdempotencyMiddleware` for anonymous users.
4. [ ] Verify IP detection for proxy environments.
