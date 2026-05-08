# Task Grouping & Due Time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a relational task grouping system and enhance due time support end-to-end.

**Architecture:** Create a new `Group` model with a many-to-one relationship to `Task`. Update existing `Task` models and schemas to include `group_id`. Refine frontend components to support dynamic groups and precise date-time selection.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, React (TypeScript), Tailwind CSS.

---

### Task 1: Backend - Group Model & Migration

**Files:**
- Create: `app/models/group.py`
- Modify: `app/models/__init__.py`
- Modify: `app/models/user.py`
- Modify: `app/models/task.py`

- [ ] **Step 1: Create Group model**
Create `app/models/group.py`:
```python
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.task import Task

class Group(Base):
    __tablename__ = "tbl_groups"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_group_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("tbl_users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="groups")
    tasks: Mapped[list[Task]] = relationship(back_populates="group")
```

- [ ] **Step 2: Update User model relationship**
Modify `app/models/user.py`:
```python
# Add to imports if needed
from app.models.group import Group
# Inside User class:
groups: Mapped[list[Group]] = relationship(back_populates="user", cascade="all, delete-orphan")
```

- [ ] **Step 3: Update Task model for Grouping**
Modify `app/models/task.py`:
```python
# Inside Task class:
group_id: Mapped[int | None] = mapped_column(ForeignKey("tbl_groups.id", ondelete="SET NULL"), nullable=True)
group: Mapped[Group | None] = relationship(back_populates="tasks")
```

- [ ] **Step 4: Export new model**
Modify `app/models/__init__.py`:
```python
from app.models.group import Group
# Add "Group" to __all__
```

- [ ] **Step 5: Generate and run migration**
Run: `alembic revision --autogenerate -m "add_group_model"`
Run: `alembic upgrade head`

- [ ] **Step 6: Commit**
```bash
git add app/models/ alembic/versions/
git commit -m "feat(backend): add Group model and task grouping relationship"
```

---

### Task 2: Backend - Group Schemas & CRUD

**Files:**
- Create: `app/schemas/group.py`
- Create: `app/crud/group.py`
- Modify: `app/schemas/task.py`

- [ ] **Step 1: Create Group schemas**
Create `app/schemas/group.py`:
```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

class GroupBase(BaseModel):
    name: str
    color: Optional[str] = None

class GroupCreateRequest(GroupBase):
    pass

class GroupUpdateRequest(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

class GroupResponse(GroupBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    created_at: datetime
```

- [ ] **Step 2: Update Task schemas**
Modify `app/schemas/task.py`:
```python
# Add group_id to TaskCreateRequest and TaskUpdateRequest
group_id: Optional[int] = None
# Add group_id to TaskCreateResponse
group_id: Optional[int]
```

- [ ] **Step 3: Implement Group CRUD**
Create `app/crud/group.py`:
```python
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.group import Group
from app.schemas.group import GroupCreateRequest, GroupUpdateRequest

async def create_group(db: AsyncSession, user_id: int, group_in: GroupCreateRequest) -> Group:
    db_group = Group(**group_in.model_dump(), user_id=user_id)
    db.add(db_group)
    await db.flush()
    return db_group

async def get_groups(db: AsyncSession, user_id: int) -> list[Group]:
    result = await db.execute(select(Group).where(Group.user_id == user_id))
    return list(result.scalars().all())

async def get_group(db: AsyncSession, group_id: int, user_id: int) -> Optional[Group]:
    result = await db.execute(select(Group).where(Group.id == group_id, Group.user_id == user_id))
    return result.scalar_one_or_none()

async def update_group(db: AsyncSession, db_group: Group, group_in: GroupUpdateRequest) -> Group:
    for field, value in group_in.model_dump(exclude_unset=True).items():
        setattr(db_group, field, value)
    db.add(db_group)
    await db.flush()
    return db_group

async def delete_group(db: AsyncSession, db_group: Group) -> None:
    await db.delete(db_group)
```

- [ ] **Step 4: Commit**
```bash
git add app/schemas/ app/crud/
git commit -m "feat(backend): implement Group schemas and CRUD operations"
```

---

### Task 3: Backend - Group API Router

**Files:**
- Create: `app/api/routers/group.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create Group router**
Create `app/api/routers/group.py` with endpoints:
- `GET /` (list)
- `POST /` (create)
- `GET /{id}/tasks` (list tasks in group)
- `PUT /{id}` (update)
- `DELETE /{id}` (delete)

- [ ] **Step 2: Register router**
Modify `app/main.py`:
```python
from app.api.routers import group
app.include_router(group.router, prefix="/api/v1/groups")
```

- [ ] **Step 3: Test API**
Write a temporary test or use `curl` to verify group creation and listing.

- [ ] **Step 4: Commit**
```bash
git add app/api/routers/ app/main.py
git commit -m "feat(backend): add Group API router and endpoints"
```

---

### Task 4: Frontend - API Hook Updates

**Files:**
- Modify: `src/hooks/useApi.ts`

- [ ] **Step 1: Add Group interfaces**
```typescript
export interface Group {
  id: number;
  name: string;
  color?: string;
  user_id: number;
  created_at: string;
}
```

- [ ] **Step 2: Update Task interface**
Remove `category`, add `group_id?: number`.

- [ ] **Step 3: Implement useGroups hook**
Implement `useGroups` with `groups`, `loading`, `error`, `createGroup`, `updateGroup`, `deleteGroup`.

- [ ] **Step 4: Update useTasks**
Allow filtering by `group_id` in the API call.

- [ ] **Step 5: Commit**
```bash
git add src/hooks/useApi.ts
git commit -m "feat(frontend): update API hook for task grouping"
```

---

### Task 5: Frontend - UI Enhancements

**Files:**
- Modify: `src/components/new-task-modal.tsx`
- Modify: `src/components/task-card.tsx`
- Modify: `src/components/sidebar.tsx`

- [ ] **Step 1: Update NewTaskModal**
- Use `useGroups` to show dynamic groups.
- Update `due_date` input to `datetime-local`.

- [ ] **Step 2: Update TaskCard**
- Display group badge.
- Format `due_date` to show time.

- [ ] **Step 3: Update Sidebar**
- List groups and allow filtering.

- [ ] **Step 4: Commit**
```bash
git add src/components/
git commit -m "feat(frontend): UI enhancements for grouping and due time"
```
