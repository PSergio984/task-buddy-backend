"""
Shared dependencies used across multiple routes and modules.

This module contains common dependency functions that are used
by multiple routers and path operations in the application.
"""

from typing import Annotated

from fastapi import Header, HTTPException


async def get_token_header(x_token: Annotated[str, Header()]):
    """
    Validate X-Token header.
    
    This is a simple token validation dependency.
    In production, use proper authentication (JWT, OAuth2, etc.).
    """
    if x_token != "fake-super-secret-token":
        raise HTTPException(status_code=400, detail="X-Token header invalid")


async def get_query_token(token: str = None):
    """
    Validate query token parameter.
    
    Optional query parameter for basic token validation.
    Set as optional in production or remove if not needed.
    """
    if token is None:
        return None
    # Add your token validation logic here
    return token
