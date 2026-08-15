"""Origin-check CSRF guard for cookie-authenticated mutations.

Cookie auth with SameSite=None (prod) is CSRF-able via cross-site form POSTs:
JSON endpoints are protected by CORS preflight, but form-encoded and bodyless
POSTs (e.g. /logout, /users/token) are not. Browsers always send an Origin
header on cross-site POSTs and on same-origin POSTs; non-browser clients
(curl, health checks) omit it and are allowed through.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import config

logger = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


async def origin_check_middleware(request: Request, call_next):
    """Reject non-safe requests whose Origin is neither the frontend nor the API."""
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("Origin")
        if origin:
            allowed = {str(o).rstrip("/") for o in config.ALLOWED_ORIGINS}
            allowed.add(str(request.base_url).rstrip("/"))
            if origin.rstrip("/") not in allowed:
                logger.warning(
                    "CSRF rejection: method=%s path=%s origin=%s",
                    request.method,
                    request.url.path,
                    origin,
                )
                return JSONResponse(status_code=403, content={"detail": "Forbidden origin"})
    return await call_next(request)
