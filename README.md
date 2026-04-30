# Task Buddy Backend

A modern FastAPI backend application for the Task Buddy task management system.

## 📋 Features

- 🚀 Fast, modern Python web framework (FastAPI)
- 📚 Automatic API documentation with Swagger UI
- 🔐 Security with JWT tokens and OAuth2
- 🗄️ SQLAlchemy ORM for database operations
- 🧪 Comprehensive test suite with pytest
- 📝 Type hints and validation with Pydantic
- 🔄 CORS support for cross-origin requests
- ✅ Health check endpoints
- 🏗️ Modular, scalable project structure

## 🛠️ Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Server**: [Uvicorn](https://www.uvicorn.org/)
- **ORM**: [SQLAlchemy](https://www.sqlalchemy.org/)
- **Validation**: [Pydantic](https://docs.pydantic.dev/)
- **Testing**: [pytest](https://pytest.org/)
- **Database**: PostgreSQL (configurable)

## 📁 Project Structure

```
task-buddy-backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Main FastAPI application
│   ├── dependencies.py         # Shared dependencies
│   ├── api/
│   │   ├── __init__.py
│   │   ├── dependencies.py    # API-specific dependencies
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── health.py      # Health check endpoints
│   │       ├── tasks.py       # Task management endpoints
│   │       └── users.py       # User management endpoints
│   ├── crud/                  # Database operations (CRUD)
│   ├── models/                # SQLAlchemy models
│   ├── schemas/               # Pydantic schemas
│   └── internal/              # Internal modules (admin, etc.)
├── tests/
│   ├── __init__.py
│   ├── test_main.py          # Main app tests
│   ├── test_health.py        # Health endpoint tests
│   └── test_*.py             # Other test files
├── pyproject.toml            # Project configuration
├── requirements.txt          # Python dependencies
├── .gitignore               # Git ignore file
└── README.md                # This file
```

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- pip or poetry
- PostgreSQL (optional, for database)

### Installation

1. **Clone the repository**

```bash
git clone https://github.com/yourusername/task-buddy-backend.git
cd task-buddy-backend
```

2. **Create a virtual environment**

```bash
# On Windows
python -m venv venv
venv\Scripts\activate

# On macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

3. **Install dependencies**

```bash
pip install -e ".[dev]"
# or
pip install -r requirements.txt
```

### Running the Application

#### Development Mode

Using FastAPI CLI:

```bash
fastapi dev
```

Or with Uvicorn directly:

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

#### Production Mode

```bash
fastapi run
```

Or with Uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 📚 API Documentation

Once the application is running, visit:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## 🔍 Available Endpoints

### Health Check

- `GET /health/` - Health status
- `GET /health/ready` - Readiness check
- `GET /health/live` - Liveness check

### Tasks

- `GET /api/v1/tasks/` - List all tasks
- `GET /api/v1/tasks/{task_id}` - Get task by ID
- `POST /api/v1/tasks/` - Create new task
- `PUT /api/v1/tasks/{task_id}` - Update task
- `DELETE /api/v1/tasks/{task_id}` - Delete task

### Users

- `GET /api/v1/users/` - List all users
- `GET /api/v1/users/{user_id}` - Get user by ID
- `POST /api/v1/users/` - Create new user
- `PUT /api/v1/users/{user_id}` - Update user
- `DELETE /api/v1/users/{user_id}` - Delete user

## 🧪 Testing

Run the test suite:

```bash
pytest
```

With coverage:

```bash
pytest --cov=app --cov-report=html
```

## 📝 Code Quality

### Format code with Black

```bash
black app tests
```

### Lint with ruff

```bash
ruff check app tests
```

### Type checking with mypy

```bash
mypy app
```

### Sort imports with isort

```bash
isort app tests
```

## 🔑 Environment Variables

Create a `.env` file in the project root:

```env
# Database
DATABASE_URL=postgresql://user:password@localhost/task_buddy

# Security
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Application
DEBUG=True
LOG_LEVEL=INFO
```

## 📦 Docker

### Build Docker image

```bash
docker build -t task-buddy-backend:latest .
```

### Run container

```bash
docker run -p 8000:8000 task-buddy-backend:latest
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 💬 Support

For support, open an issue on GitHub or contact the development team.

## 🔗 Useful Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Uvicorn Documentation](https://www.uvicorn.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [pytest Documentation](https://docs.pytest.org/)

---

**Made with ❤️ for Task Buddy**
