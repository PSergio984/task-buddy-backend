"""
Task Buddy Backend - Main FastAPI Application

This is the main entry point for the Task Buddy Backend API.
It initializes the FastAPI application and includes all routes and configurations.
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies import get_query_token
from app.api.routers import health, tasks, users


# Define lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown events using the modern lifespan approach.
    Code before yield runs on startup, code after yield runs on shutdown.
    """
    # Startup event
    print("✨ Task Buddy Backend is starting up...")
    yield
    # Shutdown event
    print("👋 Task Buddy Backend is shutting down...")


# Initialize FastAPI application
app = FastAPI(
    title="Task Buddy Backend",
    description="API for managing tasks and user accounts",
    version="0.1.0",
    dependencies=[Depends(get_query_token)],
    lifespan=lifespan,
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(
    tasks.router,
    prefix="/api/v1/tasks",
    tags=["tasks"],
)
app.include_router(
    users.router,
    prefix="/api/v1/users",
    tags=["users"],
)


@app.get("/", tags=["root"])
async def root():
    """Root endpoint - returns welcome message."""
    return {
        "message": "Welcome to Task Buddy Backend API",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
