from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery(
    "lead_hunter", broker=settings.broker_url, backend=settings.result_backend, include=["app.workers.tasks"]
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_acks_late=True,  # redeliver if a worker dies mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_always_eager=settings.celery_task_always_eager,
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.run_campaign": {"queue": "research"},
        # A worker of their own: the research worker can be busy with one long run for an hour.
        "app.workers.tasks.deliver_notifications": {"queue": "notify"},
        "app.workers.tasks.notification_daily_checks": {"queue": "notify"},
    },
    broker_transport_options={"visibility_timeout": 60 * 60 * 2},
    beat_schedule={
        "recover-stalled-runs": {"task": "app.workers.tasks.recover_stalled_runs", "schedule": 300.0},
        "apply-retention": {"task": "app.workers.tasks.apply_retention", "schedule": 60.0 * 60 * 24},
        "deliver-notifications": {
            "task": "app.workers.tasks.deliver_notifications",
            "schedule": 20.0,
            "options": {"expires": 19},  # a backlog of ticks is pointless: the next one picks up everything due
        },
        "notification-daily-checks": {  # 08:00 Cairo: trial reminders and the admin summary arrive in the morning
            "task": "app.workers.tasks.notification_daily_checks",
            "schedule": crontab(hour=6, minute=0),
        },
    },
)


@worker_ready.connect
def _on_worker_ready(**_: object) -> None:
    # Resume runs interrupted by a restart.
    celery_app.send_task("app.workers.tasks.recover_stalled_runs", kwargs={"stale_minutes": 0})
