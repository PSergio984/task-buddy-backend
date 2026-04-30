"""
Test cases for main application.

Tests for the root endpoint and basic application functionality.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root():
    """Test the root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()
    assert "Welcome to Task Buddy Backend API" in response.json()["message"]
