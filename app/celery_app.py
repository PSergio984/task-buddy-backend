"""
Celery application initialization and configuration.

This module sets up the Celery instance used for background task processing,
configuring it with Redis as the broker and backend, and auto-discovering
tasks in the app package.

Public Exports:
    - celery_app: The configured Celery application instance.
"""

import logging

from celery import Celery

from app.config import REDIS_URL

logger = logging.getLogger(__name__)

celery_app: Celery = Celery(
    "worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

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
    worker_max_tasks_per_child=100,  # Recycle workers to prevent memory leaks
    task_time_limit=300,  # 5 minutes
    task_soft_time_limit=240,  # 4 minutes
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "process-reminders-every-10-mins": {
        "task": "app.tasks.process_reminders",
        "schedule": 600.0,  # 10 minutes
    },
}

# Optional: auto-discover tasks in 'app.tasks'
celery_app.autodiscover_tasks(["app"])
