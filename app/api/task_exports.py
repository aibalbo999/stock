from __future__ import annotations

from app.tasks.celery_app import celery_app
from app.tasks.tasks import (
    data_operation_task,
    discovered_report_task,
    generate_report_task,
    report_follow_up_task,
)


TASK_EXPORT_NAMES = (
    "celery_app",
    "data_operation_task",
    "discovered_report_task",
    "generate_report_task",
    "report_follow_up_task",
)

__all__ = [
    "celery_app",
    "data_operation_task",
    "discovered_report_task",
    "generate_report_task",
    "report_follow_up_task",
    "TASK_EXPORT_NAMES",
    "task_export_namespace",
]


def task_export_namespace() -> dict[str, object]:
    return {name: globals()[name] for name in TASK_EXPORT_NAMES}
