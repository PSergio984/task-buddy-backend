---
phase: 03-task-grouping-and-due-time
reviewed: 2026-05-09T01:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - app/models/group.py
  - app/models/user.py
  - app/models/task.py
  - app/models/__init__.py
  - alembic/versions/27b3aa32daf2_add_group_model.py
findings:
  critical: 1
  warning: 2
  info: 1
  total: 4
status: issues_found
---

# Phase 03: Code Review Report - Task 1

**Reviewed:** 2026-05-09T01:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

The implementation of the Group model and migration is mostly sound but contains a critical inconsistency regarding foreign key constraints and a significant mismatch in the association table definition. While the SQLAlchemy 2.0 patterns are correctly applied, DB-level integrity and consistency with established project patterns (as seen in `Tag` and `Task`) need to be addressed.

## Critical Issues

### CR-01: Missing DB-level `ondelete="CASCADE"` for Group `user_id`

**File:** `app/models/group.py:22` and `alembic/versions/27b3aa32daf2_add_group_model.py:28`
**Issue:** All other user-owned models in the project (`Task`, `Tag`, `AuditLog`) define `ondelete="CASCADE"` at the database level for their `user_id` foreign key. The `Group` model is missing this, which risks orphaned group records if a user is deleted directly in the database, and creates an inconsistency in the schema.
**Fix:**
In `app/models/group.py`:
```python
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id", ondelete="CASCADE"), nullable=False)
```
In `alembic/versions/27b3aa32daf2_add_group_model.py`:
```python
    sa.ForeignKeyConstraint(['user_id'], ['tbl_users.id'], ondelete='CASCADE'),
```

## Warnings

### WR-01: Primary Key Mismatch in `tbl_task_tags` association table

**File:** `app/models/task.py:16`
**Issue:** The model defines `tbl_task_tags` with a composite primary key (`task_id`, `tag_id`). However, the initial migration (`a6e267909ed1`) created this table with a separate `id` column as the primary key. This mismatch can cause SQLAlchemy to fail when updating or deleting associations as it expects a different PK structure than what exists in the DB.
**Fix:** Update the model to match the actual database schema:
```python
task_tags = Table(
    "tbl_task_tags",
    Base.metadata,
    Column("id", sa.Integer, primary_key=True),
    Column("task_id", ForeignKey("tbl_tasks.id", ondelete="CASCADE")),
    Column("tag_id", ForeignKey("tbl_tags.id", ondelete="CASCADE")),
    Column("created_at", DateTime, server_default=func.now()),
)
```

### WR-02: Missing `__repr__` method in `Group` model

**File:** `app/models/group.py:16`
**Issue:** The `Group` model lacks a `__repr__` method. This is inconsistent with all other models in the project (`User`, `Task`, `SubTask`, `Tag`), which include it for easier debugging and logging.
**Fix:**
```python
    def __repr__(self) -> str:
        return f"<Group(id={self.id}, name={self.name}, user_id={self.user_id})>"
```

## Info

### IN-01: Cross-Entity Ownership Risk

**File:** `app/models/task.py:40`
**Issue:** `Task.group_id` allows associating a task with a group. There is currently no database-level constraint (e.g., via composite FK) to ensure that the `task.user_id` matches the `group.user_id`. While typically handled in application logic, this allows for potential data integrity issues if not carefully validated in CRUD operations.
**Fix:** Ensure ownership validation is strictly enforced in `app/crud/task.py` and `app/api/routers/task.py` when assigning or updating groups.

---

_Reviewed: 2026-05-09T01:00:00Z_
_Reviewer: gsd-code-reviewer_
_Depth: standard_
