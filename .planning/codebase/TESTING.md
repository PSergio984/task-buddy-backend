<!-- generated-by: gsd-doc-writer -->
# Testing

## Testing Strategy
- **Unit & Integration Tests:** Pytest with `pytest-asyncio`. Focus on CRUD logic and API endpoints.
- **API Contract Tests:** `quality/UAT_TEST_CASES.md` verifies the backend API independently.
- **System E2E Tests:** `docs/MASTER_SPEC.md` defines end-to-end scenarios spanning Frontend and Backend.

## Execution
- **Run Tests:** `pytest tests/`
- **Coverage:** `pytest --cov=app tests/`
- **UAT Verification:** Manual or automated scripts against `quality/UAT_TEST_CASES.md`.
