from celery import Celery

from app.config import REDIS_URL

celery_app = Celery(
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
)

# Optional: auto-discover tasks in 'app.tasks'
celery_app.autodiscover_tasks(["app"])
