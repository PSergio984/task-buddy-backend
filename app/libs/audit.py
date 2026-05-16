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

def _find_db_obj(bound_args: inspect.BoundArguments) -> Any:
    """Find the database object in the arguments."""
    for arg in bound_args.arguments.values():
        if hasattr(arg, "id") and not isinstance(arg, AsyncSession) and not hasattr(arg, "model_dump"):
            return arg
    return None

def _find_update_data(bound_args: inspect.BoundArguments) -> Any:
    """Find the update data (dict or model) in the arguments."""
    for arg in bound_args.arguments.values():
        if hasattr(arg, "model_dump"):
            return arg.model_dump(exclude_unset=True)
        if isinstance(arg, dict) and arg is not bound_args.arguments.get("kwargs"):
            return arg
    return None

def _extract_pre_execution_data(
    bound_args: inspect.BoundArguments,
    action_str: str,
    include_diff: bool,
    field_blacklist: list[str]
):
    """Capture initial state and identifiers before the operation executes."""
    db_obj = _find_db_obj(bound_args)
    target_id = getattr(db_obj, "id", None)
    pre_name = _extract_display_name(db_obj)
    old_values = {}
    update_data = None

    if include_diff and action_str == AuditAction.UPDATE:
        update_data = _find_update_data(bound_args)
        if db_obj and update_data:
            old_values = {
                field: getattr(db_obj, field, None)
                for field in update_data.keys()
                if field not in field_blacklist
            }

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

def _format_audit_details(
    action_str: str,
    target_type: str,
    display_name: str | None,
    include_diff: bool,
    old_values: dict,
    update_data: dict | None,
    field_blacklist: list[str]
) -> str:
    """Generate the details string for the audit log."""
    details = f"{action_str.capitalize()} {target_type.lower()}"
    if display_name:
        details += f": {display_name}"

    if include_diff and action_str == AuditAction.UPDATE and update_data:
        details += _generate_diff_string(old_values, update_data, field_blacklist)
    return details

async def _persist_audit_log(
    db: AsyncSession,
    user_id: Any,
    action: AuditAction | str,
    target_type: str,
    target_id: Any,
    details: str,
    commit: bool,
    func_name: str
):
    """Persist the audit log entry to the database."""
    try:
        await create_audit_log(
            db=db, user_id=user_id, action=action,
            target_type=target_type, target_id=target_id, details=details
        )
        if commit:
            await db.commit()
    except Exception:
        logger.exception(f"Failed to create audit log for {func_name}")

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

            # 1. PRE-EXECUTION: Capture context before the call
            _, target_id, pre_name, old_values, update_data = _extract_pre_execution_data(
                bound_args, action_str, include_diff, field_blacklist
            )

            # 2. EXECUTE the operation
            result = await func(*args, **kwargs)

            # 3. POST-EXECUTION: Extract remaining context
            db = _extract_db_from_args(bound_args)
            if target_id is None:
                target_id = _extract_target_id_from_context(bound_args, result)

            user_id = _extract_user_id_from_context(bound_args, result, target_type, target_id)

            # 4. GENERATE DETAILS & PERSIST
            if db and user_id:
                display_name = _extract_display_name(result) or pre_name
                details = _format_audit_details(
                    action_str, target_type, display_name,
                    include_diff, old_values, update_data, field_blacklist
                )
                await _persist_audit_log(
                    db, user_id, action, target_type, target_id, details, commit, func.__name__
                )

            return result
        return wrapper
    return decorator
