import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = Celery(
    "swim_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.analyze"]
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Seoul",
    task_routes={
        "tasks.analyze.run_analysis": {"queue": "swim-analysis"},
    },
)
