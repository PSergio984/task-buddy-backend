---
phase: 02-security-hardening
reviewed: 2025-02-13T16:45:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - app/security.py
  - app/main.py
  - tests/test_security_hardening.py
  - tests/test_security.py
  - app/api/routers/user.py
  - app/dependencies.py
  - app/config.py
findings:
  critical: 1
  warning: 1
  info: 3
  total: 5
status: issues_found
---

# Phase 02: Code Review Report (Security Hardening)

**Reviewed:** 2025-02-13
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

The security hardening phase successfully implemented Argon2 password hashing with legacy PBKDF2 support and lazy migration logic. It also added comprehensive security headers and CORS protection. However, a critical logic error prevents the password migration from persisting in production, and the overly restrictive CSP header breaks the default developer documentation UI (Swagger).

## Critical Issues

### CR-01: Password Lazy Migration Persistence Failure

**File:** `app/api/routers/user.py:108`
**Issue:** The `login` endpoint calls `authenticate_user`, which correctly triggers a password re-hash if the user is using the legacy PBKDF2 scheme. However, the `login` router never calls `db.commit()`. Since the database session is closed (and thus rolled back) at the end of the request by the `get_db` dependency, the migrated password hash is never saved to the database. Users will be re-hashed on every login indefinitely.
**Fix:**
```python
@router.post(TOKEN_PATH, responses={401: {"description": AUTH_CREDENTIALS_ERROR}})
@limiter.limit("5/minute")
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    auth_user = await authenticate_user(db, form_data.username, form_data.password)
    # Commit any potential lazy migration (password re-hash)
    await db.commit() 
    access_token = create_access_token(auth_user.id)
    return {"access_token": access_token, "token_type": "bearer"}
```

## Warnings

### WR-01: Restrictive CSP Blocks Swagger UI and ReDoc

**File:** `app/main.py:84`
**Issue:** The `Content-Security-Policy` is set to `default-src 'none'`, which blocks all external and inline assets. FastAPI's default `/docs` (Swagger UI) and `/redoc` endpoints rely on CDN-hosted JavaScript and CSS. With this CSP, the documentation pages will fail to load, showing a blank page and console errors.
**Fix:** Update the CSP to allow necessary assets for development/documentation, or specifically exclude documentation routes if they are intended to be public.
```python
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "frame-ancestors 'none';"
    )
```

## Info

### IN-01: Information Leak in Authentication

**File:** `app/security.py:146`
**Issue:** `authenticate_user` returns a specific error message `"Email not confirmed"` when an account exists but is unconfirmed. This allows an attacker to perform email enumeration by distinguishing between unregistered emails (returns `"Invalid credentials"`) and registered but unconfirmed emails.
**Fix:** Consider returning a generic `"Invalid credentials"` or `"Authentication failed"` message for all failed attempts, regardless of whether the email exists or its confirmation status.

### IN-02: Deprecated X-XSS-Protection Header

**File:** `app/main.py:82`
**Issue:** `X-XSS-Protection: 1; mode=block` is deprecated and superseded by modern CSP `script-src` directives. In some rare cases, it can even be exploited to cause vulnerabilities in older browsers.
**Fix:** Rely on a robust `Content-Security-Policy` and consider removing this legacy header.

### IN-03: Redundant Secret Key Validation Logic

**File:** `app/security.py:44`
**Issue:** `_get_secret_key()` provides a runtime check for `SECRET_KEY`, but `ProdConfig` in `app/config.py` already implements a `model_validator` that prevents the application from starting if `SECRET_KEY` is missing in production.
**Fix:** Use `config.SECRET_KEY` directly to simplify the code path.

---

_Reviewed: 2025-02-13_
_Reviewer: gsd-code-reviewer_
_Depth: standard_
