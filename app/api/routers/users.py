"""
Users router module.

Handles all user-related endpoints including authentication,
profile management, and user CRUD operations.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(
    tags=["users"],
    responses={404: {"description": "User not found"}},
)


# Mock data for demonstration
fake_users_db = {
    "1": {"id": "1", "username": "john_doe", "email": "john@example.com"},
    "2": {"id": "2", "username": "jane_smith", "email": "jane@example.com"},
}


@router.get("/", tags=["users"])
async def get_users():
    """
    Retrieve all users.
    
    Returns a list of all users in the system.
    """
    return {"users": list(fake_users_db.values())}


@router.get("/{user_id}")
async def get_user(user_id: str):
    """
    Retrieve a specific user by ID.
    
    Args:
        user_id: The unique identifier of the user
        
    Returns:
        The user details
    """
    if user_id not in fake_users_db:
        raise HTTPException(status_code=404, detail="User not found")
    return fake_users_db[user_id]


@router.post("/")
async def create_user(username: str, email: str):
    """
    Create a new user.
    
    Args:
        username: The user's username (required)
        email: The user's email address (required)
        
    Returns:
        The created user
    """
    # Check if username already exists
    for user in fake_users_db.values():
        if user["username"] == username:
            raise HTTPException(status_code=400, detail="Username already exists")
    
    new_id = str(len(fake_users_db) + 1)
    new_user = {
        "id": new_id,
        "username": username,
        "email": email,
    }
    fake_users_db[new_id] = new_user
    return new_user


@router.put("/{user_id}")
async def update_user(user_id: str, username: str = None, email: str = None):
    """
    Update an existing user.
    
    Args:
        user_id: The user ID
        username: Updated username (optional)
        email: Updated email (optional)
        
    Returns:
        The updated user
    """
    if user_id not in fake_users_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = fake_users_db[user_id]
    if username is not None:
        user["username"] = username
    if email is not None:
        user["email"] = email
    
    return user


@router.delete("/{user_id}")
async def delete_user(user_id: str):
    """
    Delete a user.
    
    Args:
        user_id: The user ID
        
    Returns:
        Confirmation message
    """
    if user_id not in fake_users_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    deleted_user = fake_users_db.pop(user_id)
    return {"message": "User deleted", "user": deleted_user}
