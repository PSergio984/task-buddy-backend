# Task Buddy Backend

A modern FastAPI backend application for the Task Buddy task management system.

## 📋 Features

- 🚀 Fast, modern Python web framework (FastAPI)
- 📚 Automatic API documentation with Swagger UI
- 🔐 Security with JWT tokens and OAuth2
- 🗄️ SQLAlchemy ORM for database operations
- 🧪 Comprehensive test suite with pytest
- 📧 Background tasks with Celery & Redis (Email delivery)
- 🐋 Dockerized environment with automated migrations
- ✅ Health check endpoints

## 🛠️ Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Server**: [Uvicorn](https://www.uvicorn.org/)
- **ORM**: [SQLAlchemy](https://www.sqlalchemy.org/)
- **Task Queue**: [Celery](https://docs.celeryq.dev/) + [Redis](https://redis.io/)
- **Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
- **Validation**: [Pydantic](https://docs.pydantic.dev/)
- **Database**: PostgreSQL

## 🚀 Quick Start

### 🐳 Docker Compose (Recommended)

The easiest way to run the entire stack (App, DB, Redis, Worker) is using Docker Compose:

```bash
docker-compose up --build
```

This will:
1. Start PostgreSQL and Redis.
2. Run database migrations automatically via `start.sh`.
3. Start the FastAPI application.
4. Start a dedicated Celery worker for background tasks.

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

5. **Run Celery Worker**:
   ```bash
   celery -A app.celery_app worker --loglevel=info
   ```

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

---
**Note on Email Sending**: If registration or password reset emails are not being sent, ensure the Celery worker is running and configured with valid SMTP or Brevo API keys in `.env`.
