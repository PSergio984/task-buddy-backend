<!-- generated-by: gsd-doc-writer -->
# Conventions

## Coding Style
- **Audit Logging:** All mutating CRUD operations MUST use the `@audit_log` decorator.
- **Idempotency:** POST/PUT requests requiring protection should use the `X-Idempotency-Key` header and the `@idempotent` decorator.

## API Patterns
- **Headers:** Use `X-Idempotency-Key` for ensuring operation uniqueness in high-concurrency or retry scenarios.
