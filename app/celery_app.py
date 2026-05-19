"""
Celery application initialization and configuration.

This module sets up the Celery instance used for background task processing,
configuring it with Redis as the broker and backend, and auto-discovering
tasks in the app package.

Public Exports:
    - celery_app: The configured Celery application instance.
"""

import logging
import sys

from celery import Celery

from app.config import REDIS_URL

logger = logging.getLogger(__name__)

celery_app: Celery = Celery(
    "worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

# Windows Compatibility: The 'prefork' pool (default) is unstable on Windows and
# frequently causes 'OSError: [WinError 6] The handle is invalid'.
# We use 'threads' on Windows because it is more responsive to shutdown signals
# (Ctrl+C) than 'solo', while still avoiding the multi-process handle issues of 'prefork'.
if sys.platform == "win32":
    celery_app.conf.worker_pool = "threads"
    celery_app.conf.worker_concurrency = 4  # Allow some concurrency on Windows

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Reliability and Scale settings
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100 if sys.platform != "win32" else None,  # Recycle workers only on Linux
    task_time_limit=300,  # 5 minutes
    task_soft_time_limit=240,  # 4 minutes
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "process-reminders-every-1-min": {
        "task": "app.tasks.process_reminders",
        "schedule": 60.0,  # 1 minute
    },
}

# Optional: auto-discover tasks in 'app.tasks'
celery_app.autodiscover_tasks(["app"])
