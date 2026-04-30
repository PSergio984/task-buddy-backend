"""
Tasks router module.

Handles all task-related endpoints including CRUD operations
for managing tasks.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(
    tags=["tasks"],
    responses={404: {"description": "Task not found"}},
)


# Mock data for demonstration
fake_tasks_db = {
    "1": {"id": "1", "title": "Learn FastAPI", "description": "Study FastAPI framework", "completed": False},
    "2": {"id": "2", "title": "Build API", "description": "Create REST API", "completed": False},
}


@router.get("/", tags=["tasks"])
async def get_tasks():
    """
    Retrieve all tasks.
    
    Returns a list of all tasks in the system.
    """
    return {"tasks": list(fake_tasks_db.values())}


@router.get("/{task_id}")
async def get_task(task_id: str):
    """
    Retrieve a specific task by ID.
    
    Args:
        task_id: The unique identifier of the task
        
    Returns:
        The task details
    """
    if task_id not in fake_tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    return fake_tasks_db[task_id]


@router.post("/")
async def create_task(title: str, description: str = ""):
    """
    Create a new task.
    
    Args:
        title: Task title (required)
        description: Task description (optional)
        
    Returns:
        The created task
    """
    new_id = str(len(fake_tasks_db) + 1)
    new_task = {
        "id": new_id,
        "title": title,
        "description": description,
        "completed": False,
    }
    fake_tasks_db[new_id] = new_task
    return new_task


@router.put("/{task_id}")
async def update_task(task_id: str, title: str = None, description: str = None, completed: bool = None):
    """
    Update an existing task.
    
    Args:
        task_id: The task ID
        title: Updated title (optional)
        description: Updated description (optional)
        completed: Updated completion status (optional)
        
    Returns:
        The updated task
    """
    if task_id not in fake_tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = fake_tasks_db[task_id]
    if title is not None:
        task["title"] = title
    if description is not None:
        task["description"] = description
    if completed is not None:
        task["completed"] = completed
    
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    """
    Delete a task.
    
    Args:
        task_id: The task ID
        
    Returns:
        Confirmation message
    """
    if task_id not in fake_tasks_db:
        raise HTTPException(status_code=404, detail="Task not found")
    
    deleted_task = fake_tasks_db.pop(task_id)
    return {"message": "Task deleted", "task": deleted_task}
