"""Конфигурация Celery (раздел 13.1, 14.5).

В Фазе 1 очередь нужна даже при малом числе задач — это закладка инфраструктуры
(раздел 7.1 «асинхронность с самого начала»).
"""

from celery import Celery

from fasttender.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "fasttender",
    broker=settings.redis_url_str,
    backend=settings.redis_url_str,
    include=[
        "fasttender.tasks.parse",
        "fasttender.tasks.normalize",
        "fasttender.tasks.match",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=10,
    task_default_max_retries=3,
)
