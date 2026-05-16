import functools
import inspect
import logging
from typing import Any, Callable, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.audit import create_audit_log
from app.schemas.enums import AuditAction

logger = logging.getLogger(__name__)

T = TypeVar("T")

def _extract_db_from_args(bound_args: inspect.BoundArguments) -> AsyncSession | None:
    """Extract database session from function arguments."""
    db = bound_args.arguments.get("db")
    if isinstance(db, AsyncSession):
        return db
    for arg in bound_args.arguments.values():
        if isinstance(arg, AsyncSession):
            return arg
    return None

def _extract_display_name(obj: Any) -> str | None:
    """Extract a human-readable name (title, name, or username) from an object or dict."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get("title") or obj.get("name") or obj.get("username")
    return getattr(obj, "title", getattr(obj, "name", getattr(obj, "username", None)))

def _extract_user_id_from_context(
    bound_args: inspect.BoundArguments,
    result: Any,
    target_type: str,
    target_id: Any
) -> Any:
    """Extract user ID from arguments, result, or target context."""
    user_id = bound_args.arguments.get("user_id")
    if user_id is not None:
        return user_id

    curr_user = bound_args.arguments.get("current_user") or bound_args.arguments.get("user")
    if curr_user:
        user_id = getattr(curr_user, "id", None)
        if user_id is not None:
            return user_id

    for arg in bound_args.arguments.values():
        if hasattr(arg, "user_id"):
            return arg.user_id

    if isinstance(result, dict):
        user_id = result.get("user_id") or (result.get("user", {}).get("id") if isinstance(result.get("user"), dict) else None)
    else:
        user_id = getattr(result, "user_id", None)

    if user_id is None and target_type == "USER":
        return target_id

    return user_id

def _extract_target_id_from_context(bound_args: inspect.BoundArguments, result: Any) -> Any:
    """Extract target object ID from result or arguments."""
    if isinstance(result, dict):
        target_id = result.get("id") or (result.get("user", {}).get("id") if isinstance(result.get("user"), dict) else None)
    else:
        target_id = getattr(result, "id", None)

    if target_id is None:
        target_id = bound_args.arguments.get("id") or bound_args.arguments.get("task_id") or \
                    bound_args.arguments.get("project_id") or bound_args.arguments.get("tag_id")
    return target_id

def _extract_pre_execution_data(
    bound_args: inspect.BoundArguments,
    action_str: str,
    include_diff: bool,
    field_blacklist: list[str]
):
    """Capture initial state and identifiers before the operation executes."""
    db_obj = None
    target_id = None
    pre_name = None
    old_values = {}
    update_data = None

    for arg in bound_args.arguments.values():
        if hasattr(arg, "id") and not isinstance(arg, AsyncSession) and not hasattr(arg, "model_dump"):
            db_obj = arg
            target_id = arg.id
            pre_name = _extract_display_name(arg)
            break

    if include_diff and action_str == AuditAction.UPDATE:
        for arg in bound_args.arguments.values():
            if hasattr(arg, "model_dump"):
                update_data = arg.model_dump(exclude_unset=True)
                break
            elif isinstance(arg, dict) and arg is not bound_args.arguments.get("kwargs"):
                update_data = arg
                break

        if db_obj and update_data:
            for field in update_data.keys():
                if field not in field_blacklist:
                    old_values[field] = getattr(db_obj, field, None)

    return db_obj, target_id, pre_name, old_values, update_data

def _generate_diff_string(old_values: dict, update_data: dict, field_blacklist: list[str]) -> str:
    """Generate a readable diff string for updates."""
    changes = []
    for field, new_value in update_data.items():
        if field in field_blacklist:
            changes.append(f"{field}: [REDACTED]")
            continue

        old_value = old_values.get(field)
        if old_value != new_value:
            v_old = f"'{old_value}'" if isinstance(old_value, str) else old_value
            v_new = f"'{new_value}'" if isinstance(new_value, str) else new_value
            changes.append(f"{field}: {v_old} -> {v_new}")

    return f" | Changes: {', '.join(changes)}" if changes else ""

def audit_log(
    action: AuditAction | str,
    target_type: str,
    include_diff: bool = False,
    blacklist: list[str] | None = None,
    commit: bool = False
):
    """
    Decorator to automatically create an audit log entry after a CRUD operation.
    Extracts 'db' and 'user_id' from the function arguments or the result object.
    Supports granular diff generation for updates.
    """
    target_type = target_type.upper()
    field_blacklist = blacklist or ["password", "hashed_password", "token", "secret"]
    action_str = action.value if hasattr(action, "value") else str(action)

    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # 1. PRE-EXECUTION: Identify target and capture name/title/old_values
            _, target_id, pre_name, old_values, update_data = _extract_pre_execution_data(
                bound_args, action_str, include_diff, field_blacklist
            )

            # 2. EXECUTE the operation
            result = await func(*args, **kwargs)

            # 3. POST-EXECUTION: Extract context
            db = _extract_db_from_args(bound_args)
            if target_id is None:
                target_id = _extract_target_id_from_context(bound_args, result)

            user_id = _extract_user_id_from_context(bound_args, result, target_type, target_id)

            # 4. GENERATE DETAILS
            display_name = _extract_display_name(result) or pre_name
            details = f"{action_str.capitalize()} {target_type.lower()}"
            if display_name:
                details += f": {display_name}"

            if include_diff and action_str == AuditAction.UPDATE and update_data:
                details += _generate_diff_string(old_values, update_data, field_blacklist)

            # 5. PERSIST the log
            if db and user_id:
                try:
                    await create_audit_log(
                        db=db, user_id=user_id, action=action,
                        target_type=target_type, target_id=target_id, details=details
                    )
                    if commit:
                        await db.commit()
                except Exception:
                    logger.exception(f"Failed to create audit log for {func.__name__}")

            return result
        return wrapper
    return decorator
