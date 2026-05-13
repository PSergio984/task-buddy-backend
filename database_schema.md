# Task Buddy — Database Schema Specification

This document provides a comprehensive breakdown of the database schema for the Task Buddy ecosystem. The schema is designed for PostgreSQL and managed via SQLAlchemy 2.0 and Alembic migrations.

## 📊 Schema Overview

The database utilizes a relational model with strict foreign key constraints, many-to-many associations, and comprehensive auditing support. All tables follow a standard naming convention prefixed with `tbl_`.

---

## 🔐 Identity & Access (tbl_users)

**Purpose:** Stores user credentials, profile information, and account status. This is the root table for all user-owned data.

| Column | Type | Purpose | Constraints |
| :--- | :--- | :--- | :--- |
| `id` | Integer | Primary key for the user. | PK, Auto-increment |
| `username` | String | Public-facing display name. | Unique, Not Null |
| `email` | String | Unique login identifier and communication address. | Unique, Not Null |
| `password` | String | Argon2 hashed password string. | Not Null |
| `confirmed` | Boolean | Whether the user has verified their email. | Default: False |
| `confirmation_failed` | Boolean | Flag for tracking failed verification attempts. | Default: False |
| `created_at` | DateTime | Timestamp when the account was created. | Timezone Aware, Default: NOW() |

---

## 📝 Task Management (tbl_tasks)

**Purpose:** The central table for storing tasks. It handles priority, status, deadlines, and project associations.

| Column | Type | Purpose | Constraints |
| :--- | :--- | :--- | :--- |
| `id` | Integer | Primary key for the task. | PK, Auto-increment |
| `user_id` | Integer | ID of the user who owns the task. | FK (tbl_users.id), Not Null |
| `project_id` | Integer | ID of the project this task belongs to. | FK (tbl_projects.id), OnDelete: SET NULL |
| `title` | String | Concise summary of the task. | Not Null |
| `description` | String | Detailed notes or instructions. | Nullable |
| `completed` | Boolean | Binary status (Pending/Completed). | Default: False |
| `priority` | Enum | Importance level: `LOW`, `MEDIUM`, `HIGH`. | Default: MEDIUM |
| `due_date` | DateTime | Deadline for the task. | Timezone Aware, Nullable |
| `created_at` | DateTime | When the task was recorded. | Timezone Aware, Default: NOW() |

---

## 🪜 Nested Tasks (tbl_subtasks)

**Purpose:** Stores smaller, granular steps associated with a parent task.

| Column | Type | Purpose | Constraints |
| :--- | :--- | :--- | :--- |
| `id` | Integer | Primary key for the subtask. | PK, Auto-increment |
| `user_id` | Integer | Owner of the subtask. | FK (tbl_users.id), Not Null |
| `task_id` | Integer | Parent task link. | FK (tbl_tasks.id), Not Null |
| `title` | String | Name of the sub-step. | Not Null |
| `description` | String | Additional details for the sub-step. | Nullable |
| `completed` | Boolean | Completion status of this specific step. | Default: False |
| `due_date` | DateTime | Specific deadline for this sub-step. | Nullable |
| `created_at` | DateTime | Creation timestamp. | Default: NOW() |

---

## 📁 Project Containers (tbl_projects)

**Purpose:** Groups tasks into logical projects with custom visual branding.

| Column | Type | Purpose | Constraints |
| :--- | :--- | :--- | :--- |
| `id` | Integer | Primary key for the project. | PK, Auto-increment |
| `user_id` | Integer | User who created the project. | FK (tbl_users.id), Not Null |
| `name` | String | Project name (unique per user). | Not Null, Unique(user_id, name) |
| `color` | String | Hex code or color name for UI branding. | Nullable |
| `icon` | String | Lucide icon name for UI representation. | Nullable |
| `created_at` | DateTime | When the project was created. | Default: NOW() |

---

## 🏷️ Organization Tags (tbl_tags)

**Purpose:** Stores labels that can be applied across different projects and tasks.

| Column | Type | Purpose | Constraints |
| :--- | :--- | :--- | :--- |
| `id` | Integer | Primary key for the tag. | PK, Auto-increment |
| `user_id` | Integer | User who owns the tag. | FK (tbl_users.id), Not Null |
| `name` | String | Tag label (unique per user). | Not Null, Unique(user_id, name) |
| `color` | String | Visual identifier for the tag. | Nullable |
| `icon` | String | Optional icon for the tag. | Nullable |
| `created_at` | DateTime | Tag creation timestamp. | Default: NOW() |

---

## 🔗 Task-Tag Association (tbl_task_tags)

**Purpose:** Junction table facilitating the Many-to-Many relationship between Tasks and Tags.

| Column | Type | Purpose | Constraints |
| :--- | :--- | :--- | :--- |
| `task_id` | Integer | Link to the task. | FK (tbl_tasks.id), OnDelete: CASCADE |
| `tag_id` | Integer | Link to the tag. | FK (tbl_tags.id), OnDelete: CASCADE |
| `created_at` | DateTime | When the association was created. | Default: NOW() |

---

## 🔔 User Notifications (tbl_notifications)

**Purpose:** Records alerts, reminders, and system messages sent to users.

| Column | Type | Purpose | Constraints |
| :--- | :--- | :--- | :--- |
| `id` | Integer | Primary key. | PK |
| `user_id` | Integer | Target user. | FK (tbl_users.id), Not Null |
| `task_id` | Integer | Optional link to a task related to the alert. | FK (tbl_tasks.id), OnDelete: SET NULL |
| `type` | Enum | Type: `REMINDER_BEFORE`, `REMINDER_DUE`, `SYSTEM`. | Not Null |
| `title` | String | Brief subject of the notification. | Not Null |
| `message` | String | Full content of the alert. | Not Null |
| `is_read` | Boolean | Whether the user has seen the alert. | Default: False |
| `action_url` | String | URL to redirect the user to when clicked. | Nullable |
| `created_at` | DateTime | When the alert was generated. | Default: NOW() |

---

## 📡 Push Subscriptions (tbl_push_subscriptions)

**Purpose:** Stores VAPID push subscription tokens for PWA browser notifications.

| Column | Type | Purpose | Constraints |
| :--- | :--- | :--- | :--- |
| `id` | Integer | Primary key. | PK |
| `user_id` | Integer | Owner of the device/browser. | FK (tbl_users.id), Not Null |
| `endpoint` | String | Service worker push endpoint URL. | Unique, Not Null |
| `p256dh` | String | Public key for push encryption. | Not Null |
| `auth` | String | Authentication secret for push encryption. | Not Null |
| `created_at` | DateTime | When the device was registered. | Default: NOW() |

---

## 🕵️ Audit Trail (tbl_audit_logs)

**Purpose:** An immutable history of system activity, tracking mutations for security and accountability.

| Column | Type | Purpose | Constraints |
| :--- | :--- | :--- | :--- |
| `id` | Integer | Primary key. | PK |
| `user_id` | Integer | User who performed the action. | FK (tbl_users.id), Not Null |
| `action` | String | Description of the action (e.g., `CREATE_TASK`). | Not Null |
| `target_type` | String | The entity affected (e.g., `task`, `project`). | Not Null |
| `target_id` | Integer | ID of the specific entity modified. | Nullable |
| `details` | String | JSON or text string containing specific change diffs. | Nullable |
| `created_at` | DateTime | Exact time of the event. | Default: NOW() |
