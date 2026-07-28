"""
Delta / incremental sync — per-project, per-service checkpoint tracking.

For each (project_id, service_type) we store a document in the `checkpoints`
collection:

  {
    project_id: "...",
    service_type: "exchange",
    last_sync_at: "2026-02-22T...",
    items: {
       "mbx_0001": {status: "success", synced_at: "..."},
       "mbx_0002": {status: "failed",  synced_at: "..."},
       ...
    }
  }

Behaviour:
- On successful item migration the checkpoint entry is upserted with status='success'.
- On failure the entry gets status='failed' (so a later delta run can retry).
- When mode is 'delta' or 'incremental', discovery attaches a `checkpoint_status`
  field to each item so the UI can filter, and the backend can auto-skip already
  synced items when the operator opts in.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_checkpoint(db, project_id: str, service_type: str) -> Dict[str, Any]:
    doc = await db.checkpoints.find_one(
        {"project_id": project_id, "service_type": service_type}
    )
    if not doc:
        return {
            "project_id": project_id,
            "service_type": service_type,
            "last_sync_at": None,
            "items": {},
        }
    doc.pop("_id", None)
    doc.setdefault("items", {})
    return doc


async def annotate_items(db, project_id: str, service_type: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach checkpoint_status (never|success|failed) to each item."""
    cp = await get_checkpoint(db, project_id, service_type)
    known = cp.get("items", {})
    for it in items:
        entry = known.get(it["id"])
        it["checkpoint_status"] = entry["status"] if entry else "never"
        it["last_synced_at"] = entry["synced_at"] if entry else None
    return items


async def record_item_result(db, project_id: str, service_type: str, item_id: str, status: str):
    """Upsert per-item status into the checkpoint document."""
    await db.checkpoints.update_one(
        {"project_id": project_id, "service_type": service_type},
        {"$set": {
            f"items.{item_id}": {"status": status, "synced_at": _now_iso()},
            "last_sync_at": _now_iso(),
            "project_id": project_id,
            "service_type": service_type,
        }},
        upsert=True,
    )


async def reset_checkpoint(db, project_id: str, service_type: str):
    await db.checkpoints.delete_one({"project_id": project_id, "service_type": service_type})


def filter_by_mode(items: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    """
    - full          : return all items as-is
    - incremental   : return items whose checkpoint_status is not 'success'
                      (retries failed + processes never-synced)
    - delta         : return only 'never' — brand-new since last sync
    """
    if mode == "incremental":
        return [it for it in items if it.get("checkpoint_status") != "success"]
    if mode == "delta":
        return [it for it in items if it.get("checkpoint_status") == "never"]
    return items
