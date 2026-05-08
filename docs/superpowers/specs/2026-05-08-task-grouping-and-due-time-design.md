# Design Spec: Task Grouping & Due Time Enhancement

**Date**: 2026-05-08
**Status**: Draft
**Topic**: Phase 3 - Task Grouping and Due Time

## 1. Overview
This design outlines the implementation of a relational Task Grouping system and enhanced Due Time support in both the Task Buddy backend and frontend. These changes replace the current hardcoded category system with a flexible, user-defined group structure and ensure high-precision scheduling for tasks.

## 2. Objectives
- Replace hardcoded task categories with a dynamic `Group` relational model.
- Enable users to create, update, and delete custom groups with associated colors.
- Support precise time selection for task deadlines (date + time).
- Ensure consistent display and persistence of due times across all layers.

## 3. Backend Design (`task-buddy-backend`)

### 3.1. Models (`app/models/task.py` and new `app/models/group.py`)

#### `Group` Model
- `id`: Integer, Primary Key.
- `user_id`: Integer, ForeignKey to `tbl_users.id`, non-nullable.
- `name`: String, non-nullable.
- `color`: String (Hex code), nullable.
- `created_at`: DateTime, server default `now()`.
- **Constraint**: `UniqueConstraint("user_id", "name")` to ensure unique group names per user.

#### `Task` Model (Update)
- Add `group_id`: Integer, ForeignKey to `tbl_groups.id`, `ondelete="SET NULL"`, nullable.
- Add `group`: Relationship to `Group` (back_populates="tasks").
- `due_date`: (Existing) `DateTime` - ensure it's handled as UTC and preserves time.

### 3.2. Schemas (`app/schemas/group.py` and update `app/schemas/task.py`)

#### `Group` Schemas
- `GroupCreateRequest`: `name`, `color` (optional).
- `GroupResponse`: `id`, `name`, `color`, `user_id`, `created_at`.

#### `Task` Schemas (Update)
- `TaskCreateRequest` / `TaskUpdateRequest`: Add `group_id: Optional[int]`.
- `TaskCreateResponse`: Include `group_id: Optional[int]`.

### 3.3. API Endpoints
- `GET /api/v1/groups/`: List user's groups.
- `POST /api/v1/groups/`: Create group.
- `PUT /api/v1/groups/{id}`: Update group details.
- `DELETE /api/v1/groups/{id}`: Delete group (FK `SET NULL` on tasks).
- `GET /api/v1/groups/{id}/tasks`: List all tasks in a group.

## 4. Frontend Design (`task-buddy-frontend`)

### 4.1. API Integration (`src/hooks/useApi.ts`)
- Add `Group` and `GroupCreateData` interfaces.
- Update `Task` interface: remove `category`, add `group_id: number | null`.
- Implement `useGroups` hook for CRUD operations.
- Update `useTasks` to allow fetching tasks filtered by `group_id`.

### 4.2. UI Components

#### `NewTaskModal`
- Replace hardcoded Category dropdown with a dynamic Group selector.
- Add an "Add Group" quick-action within the selector.
- Update Due Date input: `type="datetime-local"`.
- Remove string splitting logic that previously truncated time.

#### `TaskCard`
- Display the group badge (name + color dot).
- Format `due_date` using `Intl.DateTimeFormat` or `date-fns` to show both date and time.
- Use distinct styling (e.g., bold or red) for tasks overdue based on their precise time.

#### `Dashboard` / `Sidebar`
- Add a "Groups" section to the sidebar for filtering.
- Group the task list by group name in the "All Tasks" view.

## 5. Success Criteria
1. Users can create custom groups (e.g., "Deep Work", "Urgent", "Chores").
2. Deleting a group does not delete the tasks associated with it.
3. Users can set a task to be due at a specific time (e.g., "2026-05-10 14:30").
4. The frontend displays the precise time for all deadlines.
5. All database operations are covered by tests.
