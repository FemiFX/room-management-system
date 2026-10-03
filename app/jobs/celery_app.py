from __future__ import annotations

from types import SimpleNamespace

try:
    from celery import Celery
    from celery.schedules import crontab
except ModuleNotFoundError:  # pragma: no cover
    Celery = None

    def crontab(**kwargs):
        return kwargs

from app.core.config import get_settings

settings = get_settings()

if Celery is None:  # pragma: no cover
    class _DummyCelery:
        def __init__(self):
            self.conf = SimpleNamespace(timezone="UTC", task_default_queue="rms", beat_schedule={})

        def task(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def autodiscover_tasks(self, *_args, **_kwargs):
            return None

    celery_app = _DummyCelery()
else:
    celery_app = Celery("rms", broker=settings.redis_url, backend=settings.redis_url)
    celery_app.conf.timezone = settings.default_timezone
    celery_app.conf.task_default_queue = "rms"
    celery_app.conf.beat_schedule = {
        "nextcloud-person-sync": {
            "task": "app.jobs.tasks.sync_nextcloud_person_parties",
            "schedule": crontab(minute=0),
        },
        "lease-expiry-scan": {
            "task": "app.jobs.tasks.scan_lease_expiry",
            "schedule": crontab(minute=0, hour=2),
        },
        "booking-integrity-scan": {
            "task": "app.jobs.tasks.scan_booking_conflicts",
            "schedule": crontab(minute=0, hour="*/2"),
        },
        "unreturned-key-scan": {
            "task": "app.jobs.tasks.scan_unreturned_keys",
            "schedule": crontab(minute=15, hour=2),
        },
    }
    celery_app.autodiscover_tasks(["app.jobs"])
