# Phase 3: Task Grouping & Due Time Enhancement

## Context & Objectives
Phase 3 focuses on two key feature enhancements to improve task organization and scheduling precision.

1.  **Task Grouping (Relational)**: Replace the current hardcoded `category` field with a dynamic, relational `Group` model. This allows users to create, manage, and assign tasks to custom groups.
2.  **Due Time Enhancement**: Refine the existing `due_date` field handling to ensure full support for time selection and display in both backend and frontend.

## Current State Analysis

### Backend (`task-buddy-backend`)
*   **Model (`app/models/task.py`)**:
    *   `Task` and `SubTask` both have a `due_date` field of type `DateTime`.
    *   No dedicated `Group` or `Category` model exists.
    *   There is a `Tag` model and a many-to-many relationship with `Task`.
*   **Schemas (`app/schemas/task.py`)**:
    *   `TaskCreateRequest` and `TaskUpdateRequest` include `due_date: Optional[datetime]`.

### Frontend (`task-buddy-frontend`)
*   **API Hook (`src/hooks/useApi.ts`)**:
    *   `Task` interface includes a hardcoded `category` enum: `"work" | "personal" | "school" | "health" | "other"`.
    *   `due_date` is typed as `string`.
*   **UI (`src/components/new-task-modal.tsx`)**:
    *   Uses a `Select` component for the hardcoded `category`.
    *   Uses an `<input type="date" />` for `dueDate`, which truncates time information (`split("T")[0]`).
    *   Does not currently support time selection.

## Proposed Changes

### 1. Task Grouping (Relational Model)
*   **Backend**:
    *   Create `Group` model with `id`, `name`, `color`, and `user_id`.
    *   Add `group_id` foreign key to `Task` model.
    *   Implement CRUD for `Group`.
    *   Update `Task` CRUD to handle `group_id`.
*   **Frontend**:
    *   Update `Task` interface to include `group_id` and optional `group` object.
    *   Add `useGroups` hook to `useApi.ts`.
    *   Update `NewTaskModal` to fetch and display dynamic groups instead of hardcoded categories.
    *   Add a UI for managing groups (e.g., in Settings or a dedicated modal).

### 2. Due Time Enhancement
*   **Backend**:
    *   Ensure `DateTime` handling is timezone-aware and preserves time information across all layers (Model -> Schema -> Router).
*   **Frontend**:
    *   Update `NewTaskModal` to use a date-time picker (e.g., `<input type="datetime-local" />` or a specialized UI component).
    *   Ensure the `TaskCard` and other views display the time if present.
    *   Refine `useApi.ts` to correctly parse and format ISO date-time strings.

## Success Criteria
1.  Users can create, rename, and delete custom groups.
2.  Tasks can be assigned to a group during creation or editing.
3.  Tasks can be filtered or grouped by their assigned group in the dashboard.
4.  Users can specify both a date and a time for task deadlines.
5.  The UI clearly displays the due time for tasks that have one.
