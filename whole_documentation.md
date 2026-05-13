# Task Buddy — Complete System Documentation

Task Buddy is a premium, high-performance task management ecosystem featuring a sophisticated React 19 frontend and a robust FastAPI backend. It is designed with a "Dual-Identity" aesthetic: clean and minimal in light mode, and deep navy with warm amber accents in dark mode.

---

## 📑 Table of Contents
1. [🌟 System Overview](#-system-overview)
2. [🛠️ Technology Stack](#-technology-stack)
3. [🚀 Features](#-features)
4. [🏗️ System Architecture & Flow](#-system-architecture--flow)
5. [🗄️ Database Structure](#-database-structure)
6. [🔌 API Endpoints (v1)](#-api-endpoints-v1)
7. [📚 Detailed References](#-detailed-references)

---

## 🌟 System Overview

Task Buddy provides a comprehensive suite for productivity management, including task organization, project tracking, real-time insights, and automated audit logging. The system is built for scalability, security, and exceptional user experience.

### Key Pillars
- **Premium Design**: Carefully crafted visual language with glassmorphism, smooth animations (Framer Motion), and Tailwind CSS v4.
- **Reliability**: Robust backend with comprehensive test coverage, native async support, and background task processing via Celery.
- **Organization**: Hierarchical task management with subtasks, multi-owner projects, and flexible tag associations.
- **Awareness**: Real-time dashboard statistics and a persistent, automated audit trail of all system activities.
- **Connectivity**: Integrated PWA support with Web Push notifications for cross-platform availability.

---

## 🛠️ Technology Stack

### Frontend
- **Framework**: React 19 (using `use`, `useOptimistic`, and concurrent patterns)
- **Language**: TypeScript v5.9+
- **Styling**: Tailwind CSS v4 (Engine-native performance) + Vanilla CSS Design Tokens
- **UI Components**: shadcn/ui (Radix UI primitives)
- **State Management**: TanStack Query v5 (Server state) + Zustand (Client state)
- **Animations**: Framer Motion v12
- **Build Tool**: Vite v7
- **PWA**: Vite PWA Plugin with Service Workers for offline support and push notifications

### Backend
- **Framework**: FastAPI v0.100+ (Python 3.10+)
- **ORM**: SQLAlchemy 2.0 (Full Asynchronous Support)
- **Database**: PostgreSQL (Production), SQLite (Testing/Development)
- **Package Manager**: **uv** (High-performance dependency resolution)
- **Task Queue**: Celery v5.3 + Redis (Message broker and caching)
- **Security**: Argon2 Password Hashing, JWT (OAuth2) stateless authentication
- **Integrations**: Brevo (Email), Sentry (Monitoring), Backblaze B2 (Object Storage)

---

## 🚀 Features

### 🔐 Security & Identity
- **User Registration**: Secure account creation with automated email confirmation.
- **Authentication**: JWT-based login with stateless session management and secure logout.
- **Password Recovery**: Automated forgot/reset password workflows via transactional emails.
- **Account Protection**: Argon2 hashing, rate limiting (SlowAPI), and CSRF/CORS hardening.

### 📝 Task Management
- **Task CRUD**: High-performance task creation and management with priority and status.
- **Subtasks**: Nested task structures for breaking down complex workflows.
- **Prioritization**: Visual priority levels (Low, Medium, High, Critical).
- **Categorization**: Multi-tag support for flexible cross-project organization.
- **Deadlines**: Precision due dates with timezone-aware handling and overdue alerts.

### 📁 Organization & Filtering
- **Projects**: Brandable task groups with custom icons, colors, and descriptions.
- **Tags**: Dynamic tagging system for global organization.
- **Global Search**: Real-time, debounced search across all entities.
- **Advanced Filtering**: Filter by project, tag, priority, status, or date range.

### 📊 Insights & Notifications
- **System Stats**: Real-time dashboard with task completion velocity and project distribution.
- **Audit Logs**: Automatic mutation logging tracking "who changed what and when" across the system.
- **Web Push Notifications**: Browser-level alerts for reminders and system updates using VAPID.
- **In-App Notifications**: Dedicated notification center with read/unread tracking.

---

## 🏗️ System Architecture & Flow

The following diagram illustrates the interconnected workflows of authentication, task management, notifications, and auditing.

```mermaid
---
id: 8a2ad6aa-d9a5-4ba9-bf06-6db6d8c90bbe
---
graph TD
    %% User Entry & Identity
    User((User)) -->|Register| Register[Registration Service]
    Register -->|Delay Task| CeleryEmail[Celery: Send Confirm Email]
    CeleryEmail -->|Brevo| SMTP[User's Inbox]
    SMTP -->|Click Link| Confirm[Email Confirmation]
    Confirm -->|Update| DB_User[(tbl_users)]
    
    User -->|Login| Auth[JWT Authentication]
    Auth -->|Valid| Session[Active Session]
    
    %% Task Management Workflow
    Session -->|CRUD Operations| TaskEngine[Task Management Engine]
    TaskEngine -->|Create/Update| Task[(tbl_tasks)]
    TaskEngine -->|Add Steps| Subtask[(tbl_subtasks)]
    TaskEngine -->|Categorize| TagLink{Tag Association}
    TagLink -->|M2M| Tags[(tbl_tags)]
    
    %% Automatic Audit Logging
    TaskEngine -->|**"@audit_log"**| AuditService[Audit Logging Service]
    AuditService -->|Immutable| AuditDB[(tbl_audit_logs)]
    
    %% Notification Pipeline
    Task -.->|Scheduler| TaskMonitor[Task Due-Date Monitor]
    TaskMonitor -->|Threshold Met| NotifGen[Notification Generator]
    NotifGen -->|Dispatch| RedisBroker[Redis Message Broker]
    RedisBroker -->|Process| Worker[Celery Worker]
    
    Worker -->|Push| PushAPI[Web Push / VAPID]
    Worker -->|In-App| DB_Notif[(tbl_notifications)]
    Worker -->|Alert| BrevoAPI[Brevo Transactional Email]
    
    %% UI Presentation
    DB_Notif -->|Real-time| Bell[Frontend Notification Bell]
    Task -->|Aggregate| Dashboard[Dashboard Statistics]
    AuditDB -->|Query| LogsUI[Audit Trail Page]
```

> For a more detailed breakdown of these flows, see the [System Flowchart Reference](docs/system_flowchart.md).

---

## 🗄️ Database Structure

The schema is optimized for relational integrity and fast asynchronous access.

### Core Tables Summary
| Table | Description |
|-------|-------------|
| `tbl_users` | Identity and credentials. |
| `tbl_tasks` | Task records with priority and status. |
| `tbl_subtasks` | Nested steps linked to parent tasks. |
| `tbl_projects` | Project containers with custom icons/colors. |
| `tbl_tags` | Organizational labels for cross-filtering. |
| `tbl_audit_logs` | Immutable system activity history. |
| `tbl_notifications` | User-targeted alerts and reminders. |

> For a complete column-by-column breakdown and constraints, see the [Database Schema Specification](database_schema.md).

---

## 🔌 API Endpoints (v1)

### Primary Access Points
- **Auth**: `/api/v1/user/` (Register, Login, Confirm, Reset)
- **Tasks**: `/api/v1/task/` (CRUD, Subtasks, Tags)
- **Projects**: `/api/v1/project/` (Management)
- **Notifications**: `/api/v1/notifications/` (History, Push registration)
- **Stats**: `/api/v1/stats/overview` (Dashboard analytics)

> For exact request payloads and method details, see the [API Endpoints Reference](api_endpoints.md).

---

## 📚 Detailed References

To keep this document concise, granular technical details have been moved to dedicated files:

1. **[Database Schema](database_schema.md)**: Full table definitions, data types, and relational constraints.
2. **[API Endpoints](api_endpoints.md)**: Method-by-method breakdown with sample JSON payloads.
3. **[System Flowchart](docs/system_flowchart.md)**: Descriptive Mermaid diagrams and feature-specific logic flows.
4. **[Backend Codebase Documentation](.planning/codebase/STRUCTURE.md)**: Internal file structure and backend architecture.
5. **[Frontend Codebase Documentation](c:/Users/admin/OneDrive/Documents/GitHub/task-buddy-frontend/.planning/codebase/STRUCTURE.md)**: React components and frontend standards.

---

## 🧪 Quality Assurance

- **Unit Testing**: Pytest for backend logic and Vitest for frontend components.
- **E2E Testing**: Playwright for critical user flows (Login, Task Creation).
- **Linting**: Ruff for Python and ESLint for TypeScript.
- **CI/CD**: Dockerized builds ensuring consistency across dev, test, and production.
