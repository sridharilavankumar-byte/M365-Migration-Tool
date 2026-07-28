"""
Scheduler — cron and one-shot triggers for migration jobs.

A single asyncio loop scans the `schedules` collection every SCHEDULE_TICK_SEC
seconds and dispatches due schedules by creating jobs (same path as POST /jobs).

Schedule document shape:
  {
    _id: ObjectId,
    project_id: str,
    service_type: str,
    item_ids: List[str],
    mode: "full" | "incremental" | "delta",
    concurrency: int,
    trigger_type: "cron" | "one_shot",
    cron: "0 2 * * 0"           # only for cron
    run_at: "2026-03-15T22:00:00+00:00",  # only for one_shot
    enabled: bool,
    next_run_at: "2026-...",     # iso
    last_run_at: "...",
    last_job_id: "...",
    created_at, created_by
  }
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
from croniter import croniter

logger = logging.getLogger("scheduler")

SCHEDULE_TICK_SEC = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def compute_next_run(schedule: Dict[str, Any], base: Optional[datetime] = None) -> Optional[str]:
    base = base or _now()
    if schedule["trigger_type"] == "cron":
        cron_expr = schedule.get("cron") or ""
        if not croniter.is_valid(cron_expr):
            return None
        itr = croniter(cron_expr, base)
        return _iso(itr.get_next(datetime))
    if schedule["trigger_type"] == "one_shot":
        return schedule.get("run_at")
    return None


async def _dispatch_schedule(db, schedule: Dict[str, Any], run_job_fn) -> Optional[str]:
    """Create a Job from a schedule and enqueue it. Returns the job id."""
    project = await db.projects.find_one({"_id": ObjectId(schedule["project_id"])})
    if not project:
        return None

    doc = {
        "project_id": schedule["project_id"],
        "project_name": project["name"],
        "service_type": schedule["service_type"],
        "mode": schedule.get("mode", "full"),
        "concurrency": max(1, min(10, int(schedule.get("concurrency", 3) or 3))),
        "items": [
            {"id": iid, "display_name": iid, "meta": {}, "status": "pending",
             "error": None, "finished_at": None}
            for iid in schedule.get("item_ids", [])
        ],
        "status": "queued",
        "progress": 0,
        "success_count": 0,
        "fail_count": 0,
        "completed_count": 0,
        "total": len(schedule.get("item_ids", [])),
        "created_by": schedule.get("created_by", "scheduler"),
        "created_at": _iso(_now()),
        "started_at": None,
        "finished_at": None,
        "triggered_by_schedule": str(schedule["_id"]),
    }
    res = await db.jobs.insert_one(doc)
    job_id = str(res.inserted_id)
    # Fire the background task
    asyncio.create_task(run_job_fn(job_id))
    return job_id


async def _tick(db, run_job_fn):
    now = _now()
    now_iso = _iso(now)
    cursor = db.schedules.find({"enabled": True, "next_run_at": {"$lte": now_iso}})
    async for sched in cursor:
        try:
            job_id = await _dispatch_schedule(db, sched, run_job_fn)
            update = {"last_run_at": now_iso, "last_job_id": job_id}

            if sched["trigger_type"] == "cron":
                next_iso = compute_next_run(sched, base=now)
                update["next_run_at"] = next_iso
            else:
                # one-shot — disable after firing
                update["enabled"] = False
                update["next_run_at"] = None

            await db.schedules.update_one({"_id": sched["_id"]}, {"$set": update})
            logger.info(f"Scheduler dispatched schedule {sched['_id']} → job {job_id}")
        except Exception as e:
            logger.exception(f"Scheduler dispatch failed for {sched.get('_id')}: {e}")


async def scheduler_loop(db, run_job_fn):
    """Long-lived background task. Cancel with .cancel() on shutdown."""
    logger.info("Scheduler loop starting")
    while True:
        try:
            await _tick(db, run_job_fn)
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
            raise
        except Exception as e:
            logger.exception(f"Scheduler tick error: {e}")
        await asyncio.sleep(SCHEDULE_TICK_SEC)
