"""
Health check router.

Provides endpoints for monitoring application health and status.
Useful for load balancers and monitoring systems.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException

router = APIRouter(
    prefix="/health",
    tags=["health"],
    responses={404: {"description": "Not found"}},
)


@router.get("/")
async def health_check():
    """
    Health check endpoint.
    
    Returns the current status and timestamp of the application.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "task-buddy-backend",
    }


@router.get("/ready")
async def readiness_check():
    """
    Readiness check endpoint.
    
    Returns whether the application is ready to handle requests.
    Can be extended to check database connectivity, etc.
    """
    return {
        "ready": True,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/live")
async def liveness_check():
    """
    Liveness check endpoint.
    
    Returns whether the application is still running.
    Used by Kubernetes and container orchestration platforms.
    """
    return {
        "alive": True,
        "timestamp": datetime.utcnow().isoformat(),
    }
