"""
Project structure overview and getting started guide.

This file provides a quick reference for the FastAPI project structure
and common operations.
"""

# =============================================================================
# FASTAPI PROJECT STRUCTURE OVERVIEW
# =============================================================================

# PROJECT LAYOUT:
# ===============
# task-buddy-backend/
# ├── app/                                Main application package
# │   ├── __init__.py                    Package initialization
# │   ├── main.py                        FastAPI app (main entry point)
# │   ├── config.py                      Configuration & settings
# │   ├── dependencies.py                Shared dependencies
# │   ├── api/                           API-specific modules
# │   │   ├── __init__.py
# │   │   ├── dependencies.py            API dependencies
# │   │   └── routers/
# │   │       ├── __init__.py
# │   │       ├── health.py              Health check endpoints
# │   │       ├── tasks.py               Task CRUD endpoints
# │   │       └── users.py               User CRUD endpoints
# │   ├── schemas/                       Pydantic validation models
# │   ├── models/                        SQLAlchemy ORM models
# │   ├── crud/                          Database CRUD operations
# │   └── internal/                      Internal modules (admin, etc)
# ├── tests/                             Test suite
# │   ├── test_main.py
# │   ├── test_health.py
# │   └── __init__.py
# ├── pyproject.toml                     Project configuration
# ├── requirements.txt                   Dependencies
# ├── .gitignore                         Git ignore patterns
# ├── .env.example                       Environment template
# ├── Dockerfile                         Container definition
# ├── docker-compose.yml                 Dev environment
# ├── CHANGELOG.md                       Project changelog
# └── README.md                          Main documentation

# =============================================================================
# QUICK START
# =============================================================================

# 1. Install dependencies:
#    pip install -e ".[dev]"
#
# 2. Run development server:
#    fastapi dev
#    # OR: uvicorn app.main:app --reload
#
# 3. Access API documentation:
#    http://localhost:8000/docs
#
# 4. Run tests:
#    pytest

# =============================================================================
# KEY CONCEPTS
# =============================================================================

# MODULAR STRUCTURE:
# - Routers are separated by feature (health, tasks, users)
# - Each router is a module with its own APIRouter instance
# - Routers are included in main.py with app.include_router()
#
# DEPENDENCIES:
# - Shared dependencies in app/dependencies.py
# - API-specific dependencies in app/api/dependencies.py
# - Dependencies are injected using FastAPI's Depends()
#
# CONFIGURATION:
# - Environment variables loaded in config.py
# - .env file for local development
# - .env.example provides template

# =============================================================================
# COMMON COMMANDS
# =============================================================================

# Development:
#   fastapi dev                          Start dev server with auto-reload
#   uvicorn app.main:app --reload       Alternative way to run dev server

# Production:
#   fastapi run                          Start production server
#   uvicorn app.main:app --host 0.0.0.0 --port 8000

# Testing:
#   pytest                               Run all tests
#   pytest -v                            Verbose output
#   pytest --cov=app                     With coverage report
#   pytest tests/test_health.py          Run specific test file

# Code Quality:
#   black app tests                      Format code
#   ruff check app tests                 Lint check
#   mypy app                             Type checking
#   isort app tests                      Sort imports

# Docker:
#   docker build -t task-buddy .        Build image
#   docker run -p 8000:8000 task-buddy  Run container
#   docker-compose up                    Run with PostgreSQL

# =============================================================================
# API ENDPOINTS
# =============================================================================

# Health Checks:
#   GET /health/                         Application health
#   GET /health/ready                    Readiness status
#   GET /health/live                     Liveness status

# Tasks:
#   GET /api/v1/tasks/                   List all tasks
#   GET /api/v1/tasks/{task_id}         Get specific task
#   POST /api/v1/tasks/                  Create new task
#   PUT /api/v1/tasks/{task_id}         Update task
#   DELETE /api/v1/tasks/{task_id}      Delete task

# Users:
#   GET /api/v1/users/                   List all users
#   GET /api/v1/users/{user_id}         Get specific user
#   POST /api/v1/users/                  Create new user
#   PUT /api/v1/users/{user_id}         Update user
#   DELETE /api/v1/users/{user_id}      Delete user

# =============================================================================
# FILE CREATION DATE & STRUCTURE
# =============================================================================
# Created: 2024
# Structure follows FastAPI best practices from official documentation:
# https://fastapi.tiangolo.com/tutorial/bigger-applications/
#
# This structure is:
# ✅ Scalable - Easy to add new features
# ✅ Maintainable - Clear separation of concerns
# ✅ Testable - Each module can be tested independently
# ✅ Professional - Follows FastAPI conventions
# ✅ Production-ready - Includes Docker and configuration management

print("FastAPI Project Structure Guide Created")
