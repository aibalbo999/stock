from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.services.schedule_config import ScheduleConfig, ScheduleConfigStore

settings = get_settings()

celery_app = Celery(
    "stock_ai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.tasks"],
)

def build_beat_schedule(schedule_config: ScheduleConfig, schedule_store: ScheduleConfigStore) -> dict:
    beat_schedule = {}
    if schedule_config.enabled:
        scheduled_task = (
            "app.tasks.tasks.generate_report_task"
            if schedule_config.task == "configured_report"
            else "app.tasks.tasks.after_close_report_update_task"
        )
        beat_schedule["daily-stock-report-update"] = {
            "task": scheduled_task,
            "schedule": crontab(hour=schedule_config.hour, minute=schedule_config.minute),
            "args": (schedule_store.celery_payload(),),
        }
    if schedule_config.maintenance_cleanup_enabled:
        beat_schedule["daily-maintenance-cleanup"] = {
            "task": "app.tasks.tasks.maintenance_cleanup_task",
            "schedule": crontab(
                hour=schedule_config.maintenance_cleanup_hour,
                minute=schedule_config.maintenance_cleanup_minute,
            ),
            "args": (schedule_store.maintenance_cleanup_payload(),),
        }
    return beat_schedule


schedule_store = ScheduleConfigStore()
schedule_config = schedule_store.load()
celery_app.conf.timezone = schedule_config.timezone
celery_app.conf.beat_schedule = build_beat_schedule(schedule_config, schedule_store)
