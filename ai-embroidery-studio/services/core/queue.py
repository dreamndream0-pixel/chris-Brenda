"""Job dispatch. The DB job row is the source of truth; the queue only carries the job id.

Modes (EMB_QUEUE_MODE):
  rq     - Redis + separate `rq worker` processes (scales out)
  thread - background threads inside the API process (single free-tier container, no Redis)
  inline - run synchronously (tests)
"""
from __future__ import annotations

import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from .settings import get_settings

QUEUE_NAME = "emb"
JOB_TIMEOUT_S = 600

_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _thread_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            workers = max(1, int(os.environ.get("EMB_WORKER_THREADS", "1")))
            _pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="emb-job")
        return _pool


def _run_safely(job_id: str) -> None:
    from services.worker.tasks import run_job
    try:
        run_job(job_id)  # run_job records its own failures; this only guards the thread
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def enqueue(job_id: str) -> None:
    settings = get_settings()
    if settings.queue_mode == "inline":
        from services.worker.tasks import run_job
        run_job(job_id)
        return
    if settings.queue_mode == "thread":
        _thread_pool().submit(_run_safely, job_id)
        return
    from redis import Redis
    from rq import Queue
    Queue(QUEUE_NAME, connection=Redis.from_url(settings.redis_url)).enqueue(
        "services.worker.tasks.run_job", job_id, job_timeout=JOB_TIMEOUT_S, job_id=f"emb-{job_id}",
    )


def recover_jobs() -> tuple[int, int]:
    """Thread mode keeps jobs in memory, so a restart loses them. Re-queue jobs that never started
    and fail the ones that were interrupted, instead of leaving them "running" forever."""
    from sqlalchemy import select, update

    from . import db
    with db.get_engine().begin() as conn:
        queued = [r[0] for r in conn.execute(select(db.jobs.c.id).where(db.jobs.c.status == "queued"))]
        running = [s for s in db.ACTIVE_JOB_STATUSES if s != "queued"]
        res = conn.execute(update(db.jobs).where(db.jobs.c.status.in_(running)).values(
            status="failed", error_code="server_restarted", error_message="server restarted during the job",
            updated_at=db.now()))
    for job_id in queued:
        enqueue(job_id)
    return len(queued), res.rowcount or 0
