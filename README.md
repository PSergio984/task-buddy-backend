# Task Buddy Backend

A modern FastAPI backend application for the Task Buddy task management system.

## 📋 Features

- 🚀 Fast, modern Python web framework (FastAPI)
- 📚 Automatic API documentation with Swagger UI
- 🔐 Security with JWT tokens and OAuth2
- 🗄️ SQLAlchemy ORM for database operations
- 🧪 Comprehensive test suite with pytest (347 tests)
- 🤖 AI Knowledge layer (RAG): "what do I need for this task" answers with citations
- 🧠 Memory: RAG over completed-task history for effort hints
- 📅 Planner: "what should I do next" — LLM-judged, time-bucketed plan with soft deadlines
- 🔄 Real-time sync + offline support via `POST /api/v1/sync` and Supabase Realtime
- 📧 In-process background tasks (emails, web pushes, reminders — no Celery)
- 🐋 Dockerized environment with automated migrations
- ✅ Health check endpoints

## 🛠️ Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Server**: [Uvicorn](https://www.uvicorn.org/)
- **ORM**: [SQLAlchemy](https://www.sqlalchemy.org/)
- **LLM**: [Groq](https://groq.com/) (`llama-3.3-70b-versatile`, free tier; OpenAI `gpt-4o-mini` fallback)
- **Embeddings**: [Jina](https://jina.ai/) (`jina-embeddings-v3`, free tier; local sentence-transformers for dev)
- **Retrieval**: BM25 + vector search fused via Reciprocal Rank Fusion (RRF)
- **Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
- **Validation**: [Pydantic](https://docs.pydantic.dev/)
- **Cache**: Redis (bounded pools; in-memory rate-limit storage on Render)
- **Database**: PostgreSQL (Supabase, pgvector for embeddings)

## 🚀 Quick Start

### 🐳 Docker Compose (Recommended)

The easiest way to run the entire stack (App, DB, Redis, Worker) is using Docker Compose:

```bash
docker-compose up --build
```

This will:
1. Start PostgreSQL and Redis.
2. Run database migrations automatically via `start.sh`.
3. Start the FastAPI application (emails, pushes, and reminders run in-process —
   no separate worker process).

### 🐍 Local Development

1. **Prerequisites**: Python 3.10+, PostgreSQL, Redis.

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Migrations**:
   ```bash
   alembic upgrade head
   ```

4. **Run the Application**:
   ```bash
   uvicorn app.main:app --reload
   ```
   Background work (confirmation/reset emails, web pushes, the 60s reminder
   scan, and the boot-time knowledge sweep) runs inside this process.

## 📚 API Documentation

Once the application is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🔍 Key Endpoints

### Authentication & Users
- `POST /api/v1/users/register` - Register a new user
- `POST /api/v1/users/login` - Login and get access token
- `POST /api/v1/users/forgot-password/` - Trigger password reset email
- `POST /api/v1/users/reset-password/` - Reset password with token

### Tasks
- `GET /api/v1/tasks/` - List user tasks
- `POST /api/v1/tasks/` - Create a task
- `PUT /api/v1/tasks/{task_id}` - Update a task

## 🧪 Testing

```bash
pytest
```

## 📚 Codebase Documentation

Evidence-backed docs covering the full capstone (backend + frontend) live in [`docs/codebase/`](docs/codebase/):

| Doc | Covers |
|-----|--------|
| [STACK.md](docs/codebase/STACK.md) | Runtime, frameworks, dependencies, toolchain, env vars, commands for both repos |
| [STRUCTURE.md](docs/codebase/STRUCTURE.md) | Top-level layout, entry points, module boundaries, naming rules |
| [ARCHITECTURE.md](docs/codebase/ARCHITECTURE.md) | System flow, layered design, the RAG pipeline, reused patterns, known risks |
| [CONVENTIONS.md](docs/codebase/CONVENTIONS.md) | Naming, ruff/mypy/eslint/prettier gates, imports, error/logging rules |
| [INTEGRATIONS.md](docs/codebase/INTEGRATIONS.md) | Supabase, Groq, Jina, OpenAI, Render/Vercel, Redis, Brevo, B2, Sentry; secrets & reliability |
| [TESTING.md](docs/codebase/TESTING.md) | pytest/vitest/Playwright layout, golden-set eval (P@k/R@k/F1), CI gates |
| [CONCERNS.md](docs/codebase/CONCERNS.md) | Top risks, tech debt, security, performance, high-churn areas |
| [PRESENTATION.md](docs/codebase/PRESENTATION.md) | Mock-presentation pack: stack, architecture, where RAG is used, BM25 vs TF-IDF vs vector search, evals, full decision log |

For the planning/decision trail see `.planning/` (GSD phases 07–09, DOGFOOD.md) and the wayfinder map
([issue #14](https://github.com/PSergio984/task-buddy-backend/issues/14)) with its decision tickets #15–#23.

---
**Note on Email Sending**: If registration or password reset emails are not being sent, ensure `MAIL_URL`/`MAIL_API_KEY` (Brevo) or `MAIL_SMTP_*` are configured in `.env` — emails are sent in-process after the response.
