# Task Buddy — API Endpoints Specification

All API endpoints are prefixed with `/api/v1` (unless otherwise specified). This document provides a quick reference for developers and for API testing.

## 🔐 Users & Authentication

**Base Path:** `/api/v1/user` (Based on router configuration)

| METHOD | ENDPOINT | Description | Sample JSON Payload |
| :--- | :--- | :--- | :--- |
| `POST` | `/register` | Register a new user account and trigger confirmation email. | `{"username": "johndoe", "email": "john@example.com", "password": "strongpassword123"}` |
| `POST` | `/token` | Login to receive a JWT access token (OAuth2 Password flow). | Form Data: `username=john@example.com&password=strongpassword123` |
| `POST` | `/logout` | Invalidate the current session and blacklist the token. | `{}` |
| `GET` | `/me` | Get the current authenticated user's profile. | `N/A` |
| `PATCH` | `/me/username` | Update the current user's username. | `{"username": "newusername"}` |
| `PATCH` | `/me/password` | Update the current user's password. | `{"current_password": "old", "new_password": "new"}` |
| `POST` | `/forgot-password/` | Request a password reset link via email. | `{"email": "john@example.com"}` |
| `POST` | `/reset-password/` | Reset password using a valid reset token. | `{"token": "jwt_token", "new_password": "newstrongpassword"}` |
| `POST` | `/resend-confirmation` | Resend the email verification link. | `{"email": "john@example.com"}` |
| `GET` | `/confirm/{token}` | Verify user email via token link. | `N/A` |

---

## 📝 Task Management

**Base Path:** `/api/v1/task`

| METHOD | ENDPOINT | Description | Sample JSON Payload |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | List all tasks with optional filters (`completed`, `project_id`, `tag_id`). | `N/A` |
| `POST` | `/` | Create a new task with optional tags and subtasks. | `{"title": "Buy groceries", "description": "Milk and eggs", "priority": "HIGH", "project_id": 1, "tags": ["shopping"]}` |
| `GET` | `/{task_id}` | Retrieve details of a specific task. | `N/A` |
| `PUT` | `/{task_id}` | Update task details (title, status, priority, etc.). | `{"title": "Updated title", "completed": true, "priority": "LOW"}` |
| `DELETE` | `/{task_id}` | Permanently delete a task. | `N/A` |
| `POST` | `/subtask/` | Create a standalone subtask for a specific task. | `{"task_id": 1, "title": "Check milk expiration"}` |
| `PUT` | `/subtask/{subtask_id}` | Update a specific subtask. | `{"completed": true}` |
| `DELETE` | `/subtask/{subtask_id}` | Delete a specific subtask. | `N/A` |

---

## 📁 Projects

**Base Path:** `/api/v1/project`

| METHOD | ENDPOINT | Description | Sample JSON Payload |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | List all projects for the authenticated user. | `N/A` |
| `POST` | `/` | Create a new project with custom branding. | `{"name": "Work", "color": "#3b82f6", "icon": "briefcase"}` |
| `GET` | `/{project_id}` | Get details of a single project. | `N/A` |
| `GET` | `/{project_id}/tasks` | List all tasks associated with a project. | `N/A` |
| `PUT` | `/{project_id}` | Update project name, color, or icon. | `{"name": "Career", "icon": "trending-up"}` |
| `DELETE` | `/{project_id}` | Delete a project (Tasks are unlinked). | `N/A` |

---

## 🏷️ Tags

**Base Path:** `/api/v1/task/tags` (Tags are currently nested under tasks router)

| METHOD | ENDPOINT | Description | Sample JSON Payload |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | List all available tags. | `N/A` |
| `POST` | `/` | Create a new organizational tag. | `{"name": "Urgent", "color": "#ef4444"}` |
| `DELETE` | `/{tag_id}` | Delete a specific tag. | `N/A` |
| `POST` | `/{task_id}/tags` | Create and associate a new tag with a task. | `{"name": "Personal"}` |
| `POST` | `/{task_id}/tags/{tag_id}` | Associate an existing tag with a task. | `{}` |
| `DELETE` | `/{task_id}/tags/{tag_id}` | Remove a tag association from a task. | `N/A` |

---

## 🔔 Notifications & Push

**Base Path:** `/api/v1/notifications`

| METHOD | ENDPOINT | Description | Sample JSON Payload |
| :--- | :--- | :--- | :--- |
| `GET` | `/vapid-key` | Get the public VAPID key for push registration. | `N/A` |
| `GET` | `/` | List recent notifications (supports `is_read` filter). | `N/A` |
| `PATCH` | `/{notification_id}/read` | Mark a specific notification as read. | `{}` |
| `POST` | `/read-all` | Mark all notifications as read for the user. | `{}` |
| `POST` | `/push-subscription` | Register or update a device for web push notifications. | `{"endpoint": "https://...", "p256dh": "...", "auth": "..."}` |

---

## 📊 Statistics & Audit

**Base Path:** `/api/v1`

| METHOD | ENDPOINT | Description | Sample JSON Payload |
| :--- | :--- | :--- | :--- |
| `GET` | `/stats/overview` | Get dashboard stats (counts, percentages, tag distribution). | `N/A` |
| `GET` | `/audit/logs` | Retrieve audit history (paginated, supports filters). | `N/A` (Query params: `limit`, `offset`, `action`) |

---

## 📦 Request Payload Guidelines

- **Content-Type:** `application/json`
- **Auth:** All endpoints (except registration and login) require a `Bearer <token>` in the `Authorization` header.
- **Dates:** Use ISO 8601 format (e.g., `2026-05-12T15:30:00Z`).
