"""Job dispatch. The DB job row is the source of truth; Redis/RQ only carries the job id."""
from __future__ import annotations

from .settings import get_settings

QUEUE_NAME = "emb"
JOB_TIMEOUT_S = 600


def enqueue(job_id: str) -> None:
    settings = get_settings()
    if settings.queue_mode == "inline":
        from services.worker.tasks import run_job
        run_job(job_id)
        return
    from redis import Redis
    from rq import Queue
    Queue(QUEUE_NAME, connection=Redis.from_url(settings.redis_url)).enqueue(
        "services.worker.tasks.run_job", job_id, job_timeout=JOB_TIMEOUT_S, job_id=f"emb-{job_id}",
    )
