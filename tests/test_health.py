"""
Test cases for health check endpoints.

Tests for application health, readiness, and liveness checks.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    """Test the health check endpoint."""
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_readiness_check():
    """Test the readiness check endpoint."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_liveness_check():
    """Test the liveness check endpoint."""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["alive"] is True
