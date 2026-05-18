# Concerns

## Operations & Monitoring
- **Celery Worker Health:** Monitoring is required for the Celery worker and Redis broker to ensure notification delivery reliability.
- **Rate Limit Tuning:** Fine-tuning of the FastAPI-Limiter (`app/limiter.py`) is needed as notification frequency increases.
- **Idempotency Expiry:** Ensure Redis TTL for idempotency keys is balanced between storage usage and safety windows.
