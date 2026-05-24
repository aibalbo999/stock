from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.services.schedule_config import ScheduleConfigStore

settings = get_settings()

celery_app = Celery(
    "stock_ai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.tasks"],
)

schedule_config = ScheduleConfigStore().load()
celery_app.conf.timezone = schedule_config.timezone
celery_app.conf.beat_schedule = {}
if schedule_config.enabled:
    celery_app.conf.beat_schedule["daily-ai-supply-chain-report"] = {
        "task": "app.tasks.tasks.generate_report_task",
        "schedule": crontab(hour=schedule_config.hour, minute=schedule_config.minute),
        "args": (ScheduleConfigStore().celery_payload(),),
    }
