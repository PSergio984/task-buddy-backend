---
phase: 03-task-grouping-and-due-time
reviewed: 2026-05-09T00:15:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - src/components/new-task-modal.tsx
  - src/components/task-card.tsx
  - src/components/sidebar.tsx
  - src/components/layout/main-layout.tsx
findings:
  critical: 2
  warning: 1
  info: 2
  total: 5
status: issues_found
---

# Phase 03: Code Review Report - Task 5 (Frontend UI Enhancements)

**Reviewed:** 2026-05-09
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

The implementation successfully adds support for Task Groups and improved Due Date handling (including time) as requested in Task 5. However, there is a critical bug in how dates are handled in the `NewTaskModal` that results in time shifting by the user's UTC offset every time a task is edited. Additionally, the Sidebar categories ("Work", "Personal", etc.) are currently non-functional as they are not supported by the filtering logic in the frontend or the backend.

## Critical Issues

### CR-01: Timezone Shift Bug in NewTaskModal

**File:** `src/components/new-task-modal.tsx:49`
**Issue:** The `formatDateTimeForInput` function uses `toISOString().slice(0, 16)` to format dates for the `datetime-local` input. `toISOString()` returns UTC time. However, `datetime-local` inputs expect a string in local time format (`YYYY-MM-DDThh:mm`) if they are to be consistent with the user's perception. When the user saves the modal, `new Date(dueDate).toISOString()` is called. Since `dueDate` lacks a timezone, the browser parses it as local time. This results in the time shifting by the user's UTC offset every time the modal is opened and saved.
**Fix:**
```typescript
const formatDateTimeForInput = (dateStr?: string) => {
  if (!dateStr) return ""
  try {
    const date = new Date(dateStr)
    if (isNaN(date.getTime())) return ""
    // Convert to local ISO-like string by manually adjusting for offset
    const offset = date.getTimezoneOffset() * 60000
    return new Date(date.getTime() - offset).toISOString().slice(0, 16)
  } catch (e) {
    return ""
  }
}
```

### CR-02: Non-functional Sidebar Categories

**File:** `src/components/sidebar.tsx:51`
**Issue:** The Sidebar displays "Categories" (Work, Personal, School, Health), but these filters are non-functional. The `useTasks` hook in `useApi.ts` only handles `completed` and `pending` filters, and the backend `get_all_tasks` endpoint in `app/api/routers/task.py` does not support a `category` query parameter. Clicking these sidebar items will result in showing all tasks regardless of category, which is a broken user experience.
**Fix:** Either implement category filtering in the backend and frontend, or remove the non-functional category items from the Sidebar to avoid user confusion.

## Warnings

### WR-01: UI State Mismatch between Sidebar and Dashboard Tabs

**File:** `src/components/dashboard.tsx:162`
**Issue:** The `Dashboard` component contains its own `Tabs` for filtering by "ALL", "PENDING", and "COMPLETED". These tabs share the `activeFilter` state with the `Sidebar`. When a user selects a Group in the Sidebar, `activeFilter` becomes `group:ID`. Since there is no corresponding tab in the Dashboard, no tab will appear selected. Furthermore, clicking a tab in the Dashboard will clear the Group filter from the Sidebar.
**Fix:** Consider separating `statusFilter` (all/pending/completed) and `groupFilter` into two separate state variables in `MainLayout` so they can be combined (e.g., view "Pending" tasks in "Project A" group).

## Info

### IN-01: Redundant Error Logging

**File:** `src/components/new-task-modal.tsx:94`
**Issue:** Both `NewTaskModal` and `MainLayout` (via `handleSaveTask`) log errors to the console. `MainLayout` also shows a toast notification, which is sufficient for the user.
**Fix:** Remove the `console.error` from `NewTaskModal` and let the caller (`MainLayout`) handle error reporting consistently.

### IN-02: Type Assertion in NewTaskModal

**File:** `src/components/new-task-modal.tsx:219`
**Issue:** The category `Select` uses `(v: any) => setCategory(v)`, losing type safety.
**Fix:**
```typescript
onValueChange={(v: "work" | "personal" | "school" | "health" | "other") => setCategory(v)}
```

---

_Reviewed: 2026-05-09T00:15:00Z_
_Reviewer: gsd-code-reviewer_
_Depth: standard_
