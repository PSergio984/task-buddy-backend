"""FastAPI application entrypoint: app factory, middleware, and exception handlers."""

import asyncio
import logging
from contextlib import asynccontextmanager

import sentry_sdk
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routers import (
    audit,
    knowledge,
    memory,
    notifications,
    plan,
    project,
    realtime,
    stats,
    sync,
    task,
    user,
)
from app.config import DevConfig, config
from app.libs.supabase_signing import SigningKeyCache
from app.limiter import limiter
from app.logging_conf import configure_logging
from app.middleware.csrf import origin_check_middleware
from app.middleware.idempotency import IdempotencyMiddleware

logger = logging.getLogger(__name__)

# Keep a reference to the detached sweep task so it is never garbage-collected
# mid-execution (asyncio.create_task discards are a documented GC hazard).
_background_tasks: set[asyncio.Task[None]] = set()

if config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        send_default_pii=isinstance(config, DevConfig),
        enable_logs=isinstance(config, DevConfig),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown logic for the application.

    Pre-warms the embedding model only when config allows (EMBEDDER_PREWARM).
    Dev/test warm it for a fast first query; prod overrides to False so the
    ~470MB model never loads into Render's 512MB free tier at boot —
    get_embedder() stays lazy there (slow first call, cheap boot). Graceful
    degradation is unchanged: if the model cannot load, the ask endpoint
    degrades instead of crashing.
    """
    configure_logging()
    if config.EMBEDDER_PREWARM:
        try:
            from app.knowledge.embeddings import get_embedder

            get_embedder()
            logger.info("Embedder pre-warmed")
        except Exception as exc:
            logger.warning("embedder pre-warm failed: %s", exc)
    if config.EMBEDDER_PREWARM or config.EMBEDDING_PROVIDER in ("openai", "jina"):
        # The sweep embeds every completed task lacking a history row. With the
        # local provider this loads the ~470MB model, so it is gated on
        # EMBEDDER_PREWARM (prod keeps the model off boot). The openai/jina
        # providers have no local model — the sweep is cheap and keeps the
        # corpus warm.
        try:
            from app.knowledge.history import history_backfill_sweep

            sweep_task = asyncio.create_task(history_backfill_sweep())
            _background_tasks.add(sweep_task)
            sweep_task.add_done_callback(_background_tasks.discard)
        except Exception:
            logger.exception("history backfill sweep failed to start")
    yield


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.state.signing_key_cache = SigningKeyCache()


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Return a 429 response when the client exceeds a rate limit."""
    response: Response = JSONResponse(
        status_code=429,
        content={"detail": "Too many attempts. Please try again in a few minutes."},
    )
    # Inject rate limit headers into the error response
    if hasattr(request.state, "view_rate_limit"):
        response = limiter._inject_headers(response, request.state.view_rate_limit)
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Flatten request validation errors into a single response detail string."""
    errors = []
    for error in exc.errors():
        loc = " -> ".join(str(item) for item in error.get("loc", []))
        msg = error.get("msg", "Validation error")
        errors.append(f"{loc}: {msg}")
    detail = "; ".join(errors)
    logger.warning("%s %s - Validation Error: %s", request.method, request.url.path, detail)
    status_code = 400 if request.url.path.startswith("/api/v1/users") else 422
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
    )


app.add_middleware(IdempotencyMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(SlowAPIMiddleware)

# Order matters: this runs inside the security-headers middleware below, so it
# sees the request before CORS header processing — Origin checks must not rely
# on preflight (browser already rejected cross-origin JSON; this covers the
# form/bodyless POSTs preflight never sees).
app.middleware("http")(origin_check_middleware)

app.include_router(task.router, prefix="/api/v1/tasks")
app.include_router(knowledge.router, prefix="/api/v1/tasks")
app.include_router(memory.router, prefix="/api/v1/tasks")
app.include_router(plan.router, prefix="/api/v1")
app.include_router(user.router, prefix="/api/v1/users")
app.include_router(project.router, prefix="/api/v1/projects")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(realtime.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """Return a simple liveness response."""
    return {"status": "ok"}


@app.get("/test-limit")
@limiter.limit("100/minute")
async def test_limit(request: Request, response: Response):
    """Return a response for exercising the rate limiter."""
    return {"message": "limit test"}


@app.exception_handler(HTTPException)
async def log_http_exception(request: Request, exc: HTTPException):
    """Log and re-emit an HTTPException as a JSON response."""
    logger.warning(
        "%s %s - HTTP %s: %s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, exc: Exception):
    """Log unhandled exceptions and return a generic 500 response."""
    logger.exception("%s %s - unhandled error", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security-related response headers to every response."""
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"
    return response
