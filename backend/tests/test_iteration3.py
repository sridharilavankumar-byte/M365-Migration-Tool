"""
Iteration-3 backend tests for M365 Migration Suite.

Covers:
- Schedule CRUD: create (cron+one_shot), list, get, toggle, delete, run-now
- Schedule dispatch loop (cron '*/1 * * * *' fires within ~90s)
- One-shot schedule fires once and disables itself
- Checkpoint endpoint GET/DELETE, stats accuracy
- Discovery annotation with checkpoint_status
- Delta / incremental mode filtering in POST /jobs
- Delta with failed items: incremental picks up only failed
"""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://exchange-share-mover.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@migratetool.com"
ADMIN_PASSWORD = "Admin@12345"


# ---------------- Shared fixtures ----------------
@pytest.fixture(scope="module")
def auth_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    token = r.json()["token"]
    s.headers["Authorization"] = f"Bearer {token}"
    return s


@pytest.fixture(scope="module")
def project_id(auth_client):
    payload = {
        "name": f"TEST_Iter3_{uuid.uuid4().hex[:8]}",
        "description": "iteration 3 pytest",
        "source_tenant": {"domain": "source.onmicrosoft.com", "label": "src"},
        "destination_tenant": {"domain": "dest.onmicrosoft.com", "label": "dst"},
    }
    r = auth_client.post(f"{API}/projects", json=payload)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    yield pid
    try:
        auth_client.delete(f"{API}/projects/{pid}")
    except Exception:
        pass


def _wait_for_status(auth_client, job_id, statuses, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = auth_client.get(f"{API}/jobs/{job_id}").json()
        if j.get("status") in statuses:
            return j
        time.sleep(0.5)
    return None


def _discover_ids(auth_client, project_id, n=5):
    d = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id}).json()
    return [it["id"] for it in d["items"][:n]], d["items"][:n]


# ================================================================
# Schedule CRUD
# ================================================================
class TestScheduleCRUD:
    def test_create_cron_schedule(self, auth_client, project_id):
        ids, _ = _discover_ids(auth_client, project_id, 2)
        r = auth_client.post(f"{API}/schedules", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "mode": "full",
            "concurrency": 2,
            "trigger_type": "cron",
            "cron": "*/2 * * * *",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["trigger_type"] == "cron"
        assert d["cron"] == "*/2 * * * *"
        assert d["enabled"] is True
        assert d["next_run_at"] is not None

        # next_run_at should be within ~2 minutes
        nxt = datetime.fromisoformat(d["next_run_at"])
        delta = (nxt - datetime.now(timezone.utc)).total_seconds()
        assert 0 <= delta <= 130, f"next_run_at ({delta:.1f}s away) not within 2 min"

        # cleanup
        auth_client.delete(f"{API}/schedules/{d['id']}")

    def test_create_cron_invalid(self, auth_client, project_id):
        ids, _ = _discover_ids(auth_client, project_id, 1)
        r = auth_client.post(f"{API}/schedules", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "trigger_type": "cron",
            "cron": "not-a-cron",
        })
        assert r.status_code == 400
        assert "cron" in r.json().get("detail", "").lower()

    def test_create_one_shot_schedule(self, auth_client, project_id):
        ids, _ = _discover_ids(auth_client, project_id, 1)
        run_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        r = auth_client.post(f"{API}/schedules", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "trigger_type": "one_shot",
            "run_at": run_at,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["trigger_type"] == "one_shot"
        assert d["next_run_at"] == run_at
        auth_client.delete(f"{API}/schedules/{d['id']}")

    def test_create_one_shot_missing_run_at(self, auth_client, project_id):
        ids, _ = _discover_ids(auth_client, project_id, 1)
        r = auth_client.post(f"{API}/schedules", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "trigger_type": "one_shot",
        })
        assert r.status_code == 400
        assert "run_at" in r.json().get("detail", "").lower()

    def test_run_now(self, auth_client, project_id):
        ids, _ = _discover_ids(auth_client, project_id, 2)
        # create a far-future cron schedule so it doesn't auto-fire
        r = auth_client.post(f"{API}/schedules", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "trigger_type": "cron",
            "cron": "0 3 * * 0",  # 3am Sunday
        })
        assert r.status_code == 200
        sched_id = r.json()["id"]

        rn = auth_client.post(f"{API}/schedules/{sched_id}/run-now")
        assert rn.status_code == 200, rn.text
        data = rn.json()
        assert data["ok"] is True
        assert data["job_id"]

        # Verify job exists and gets triggered_by_schedule
        j = auth_client.get(f"{API}/jobs/{data['job_id']}").json()
        assert j["triggered_by_schedule"] == sched_id

        auth_client.delete(f"{API}/schedules/{sched_id}")

    def test_toggle_schedule(self, auth_client, project_id):
        ids, _ = _discover_ids(auth_client, project_id, 1)
        r = auth_client.post(f"{API}/schedules", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "trigger_type": "cron",
            "cron": "0 3 * * 0",
        })
        sched_id = r.json()["id"]

        # Toggle off
        t1 = auth_client.put(f"{API}/schedules/{sched_id}/toggle")
        assert t1.status_code == 200
        assert t1.json()["enabled"] is False
        g = auth_client.get(f"{API}/schedules/{sched_id}").json()
        assert g["enabled"] is False

        # Toggle on
        t2 = auth_client.put(f"{API}/schedules/{sched_id}/toggle")
        assert t2.status_code == 200
        assert t2.json()["enabled"] is True
        g2 = auth_client.get(f"{API}/schedules/{sched_id}").json()
        assert g2["enabled"] is True
        assert g2["next_run_at"] is not None

        auth_client.delete(f"{API}/schedules/{sched_id}")

    def test_delete_schedule(self, auth_client, project_id):
        ids, _ = _discover_ids(auth_client, project_id, 1)
        r = auth_client.post(f"{API}/schedules", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "trigger_type": "cron",
            "cron": "0 3 * * 0",
        })
        sched_id = r.json()["id"]
        d = auth_client.delete(f"{API}/schedules/{sched_id}")
        assert d.status_code == 200
        g = auth_client.get(f"{API}/schedules/{sched_id}")
        assert g.status_code == 404


# ================================================================
# Schedule dispatch (background loop)
# ================================================================
class TestScheduleDispatch:
    def test_cron_schedule_dispatches(self, auth_client, project_id):
        ids, _ = _discover_ids(auth_client, project_id, 2)
        r = auth_client.post(f"{API}/schedules", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "trigger_type": "cron",
            "cron": "*/1 * * * *",
        })
        assert r.status_code == 200
        sched_id = r.json()["id"]
        initial_next = r.json()["next_run_at"]
        try:
            # Wait up to 90s for scheduler tick (15s tick, cron */1 fires at :00)
            deadline = time.time() + 100
            fired = False
            while time.time() < deadline:
                s = auth_client.get(f"{API}/schedules/{sched_id}").json()
                if s.get("last_job_id"):
                    fired = True
                    break
                time.sleep(3)
            assert fired, "Cron schedule never dispatched within 100s"

            s = auth_client.get(f"{API}/schedules/{sched_id}").json()
            assert s["last_job_id"] is not None
            assert s["last_run_at"] is not None
            # next_run_at should advance
            assert s["next_run_at"] != initial_next

            # Verify the job doc has triggered_by_schedule set
            job = auth_client.get(f"{API}/jobs/{s['last_job_id']}").json()
            assert job["triggered_by_schedule"] == sched_id
        finally:
            auth_client.delete(f"{API}/schedules/{sched_id}")

    def test_one_shot_fires_once(self, auth_client, project_id):
        ids, _ = _discover_ids(auth_client, project_id, 1)
        # run_at slightly in the past
        run_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        r = auth_client.post(f"{API}/schedules", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "trigger_type": "one_shot",
            "run_at": run_at,
        })
        assert r.status_code == 200
        sched_id = r.json()["id"]
        try:
            deadline = time.time() + 40
            while time.time() < deadline:
                s = auth_client.get(f"{API}/schedules/{sched_id}").json()
                if s.get("last_job_id"):
                    break
                time.sleep(2)
            s = auth_client.get(f"{API}/schedules/{sched_id}").json()
            assert s.get("last_job_id"), "one-shot did not fire within 40s"
            assert s["enabled"] is False
            assert s["next_run_at"] is None
        finally:
            auth_client.delete(f"{API}/schedules/{sched_id}")


# ================================================================
# Checkpoint endpoint & discovery annotation
# ================================================================
class TestCheckpoint:
    def test_empty_checkpoint(self, auth_client, project_id):
        # fresh project should have empty checkpoint for a service not yet used
        # Use a distinct service (sharepoint) to guarantee empty
        r = auth_client.get(f"{API}/projects/{project_id}/services/sharepoint/checkpoint")
        assert r.status_code == 200
        d = r.json()
        assert d["items"] == {}
        assert d["stats"] == {"total_known": 0, "success": 0, "failed": 0}
        assert d["last_sync_at"] is None

    def test_checkpoint_stats_after_job(self, auth_client, project_id):
        # Run a full job on 5 exchange items so they enter checkpoint
        ids, _ = _discover_ids(auth_client, project_id, 5)
        r = auth_client.post(f"{API}/jobs", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": ids,
            "mode": "full",
            "concurrency": 3,
        })
        assert r.status_code == 200
        job_id = r.json()["id"]
        final = _wait_for_status(auth_client, job_id, ("completed",), timeout=45)
        assert final is not None, "job never completed"

        # small beat for checkpoint writes
        time.sleep(1)
        cp = auth_client.get(f"{API}/projects/{project_id}/services/exchange/checkpoint").json()
        assert cp["stats"]["total_known"] >= 5
        assert cp["stats"]["success"] >= 1
        assert cp["last_sync_at"] is not None

    def test_discovery_annotates_checkpoint_status(self, auth_client, project_id):
        d = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id}).json()
        assert d["total"] > 0
        for it in d["items"]:
            assert "checkpoint_status" in it
            assert it["checkpoint_status"] in ("never", "success", "failed")
        # After the prior test, at least some items should be 'success'
        statuses = [it["checkpoint_status"] for it in d["items"]]
        assert "success" in statuses, f"expected at least one success annotation, got {set(statuses)}"

    def test_checkpoint_reset(self, auth_client, project_id):
        # Create a temp project just for reset test to not interfere with other tests
        pr = auth_client.post(f"{API}/projects", json={
            "name": f"TEST_Iter3_Reset_{uuid.uuid4().hex[:6]}",
            "description": "reset test",
            "source_tenant": {"domain": "s.onmicrosoft.com"},
            "destination_tenant": {"domain": "d.onmicrosoft.com"},
        })
        pid = pr.json()["id"]
        try:
            ids, _ = _discover_ids(auth_client, pid, 2)
            j = auth_client.post(f"{API}/jobs", json={
                "project_id": pid, "service_type": "exchange",
                "item_ids": ids, "mode": "full", "concurrency": 2,
            }).json()
            _wait_for_status(auth_client, j["id"], ("completed",), timeout=30)
            time.sleep(1)
            cp1 = auth_client.get(f"{API}/projects/{pid}/services/exchange/checkpoint").json()
            assert cp1["stats"]["total_known"] >= 2

            # Reset
            dr = auth_client.delete(f"{API}/projects/{pid}/services/exchange/checkpoint")
            assert dr.status_code == 200

            cp2 = auth_client.get(f"{API}/projects/{pid}/services/exchange/checkpoint").json()
            assert cp2["stats"]["total_known"] == 0
            assert cp2["items"] == {}
        finally:
            auth_client.delete(f"{API}/projects/{pid}")


# ================================================================
# Delta / incremental filter in POST /jobs
# ================================================================
class TestDeltaFilter:
    def test_delta_incremental_filter_blocks_when_all_success(self, auth_client, project_id):
        # Isolated project so we control checkpoint state
        pr = auth_client.post(f"{API}/projects", json={
            "name": f"TEST_Iter3_Delta_{uuid.uuid4().hex[:6]}",
            "description": "delta filter test",
            "source_tenant": {"domain": "s.onmicrosoft.com"},
            "destination_tenant": {"domain": "d.onmicrosoft.com"},
        })
        pid = pr.json()["id"]
        try:
            # Try multiple attempts to get 5 all-success items
            success_ids = None
            for attempt in range(3):
                ids, _ = _discover_ids(auth_client, pid, 5)
                j = auth_client.post(f"{API}/jobs", json={
                    "project_id": pid, "service_type": "exchange",
                    "item_ids": ids, "mode": "full", "concurrency": 3,
                }).json()
                final = _wait_for_status(auth_client, j["id"], ("completed",), timeout=45)
                assert final is not None
                time.sleep(1)
                # get discover with annotation
                disc = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": pid}).json()
                by_id = {it["id"]: it for it in disc["items"]}
                success_ids = [i for i in ids if by_id.get(i, {}).get("checkpoint_status") == "success"]
                if len(success_ids) >= 3:
                    break
                # Retry: reset & do another job
                auth_client.delete(f"{API}/projects/{pid}/services/exchange/checkpoint")

            assert success_ids and len(success_ids) >= 3, "could not obtain enough all-success items"

            # delta mode → expect 400 (no 'never' items among selection)
            r_delta = auth_client.post(f"{API}/jobs", json={
                "project_id": pid, "service_type": "exchange",
                "item_ids": success_ids, "mode": "delta", "concurrency": 2,
            })
            assert r_delta.status_code == 400
            assert "delta" in r_delta.json().get("detail", "").lower() or "no items" in r_delta.json().get("detail", "").lower()

            # incremental mode → expect 400 (all already success)
            r_inc = auth_client.post(f"{API}/jobs", json={
                "project_id": pid, "service_type": "exchange",
                "item_ids": success_ids, "mode": "incremental", "concurrency": 2,
            })
            assert r_inc.status_code == 400

            # full mode → works
            r_full = auth_client.post(f"{API}/jobs", json={
                "project_id": pid, "service_type": "exchange",
                "item_ids": success_ids, "mode": "full", "concurrency": 2,
            })
            assert r_full.status_code == 200
        finally:
            auth_client.delete(f"{API}/projects/{pid}")

    def test_incremental_picks_up_failed_only(self, auth_client, project_id):
        pr = auth_client.post(f"{API}/projects", json={
            "name": f"TEST_Iter3_Failed_{uuid.uuid4().hex[:6]}",
            "description": "incremental picks failed",
            "source_tenant": {"domain": "s.onmicrosoft.com"},
            "destination_tenant": {"domain": "d.onmicrosoft.com"},
        })
        pid = pr.json()["id"]
        try:
            # Retry up to a few times to get at least one failure (~8% failure rate)
            failed_ids = []
            success_ids = []
            ids = None
            for attempt in range(4):
                ids, _ = _discover_ids(auth_client, pid, 8)
                j = auth_client.post(f"{API}/jobs", json={
                    "project_id": pid, "service_type": "exchange",
                    "item_ids": ids, "mode": "full", "concurrency": 4,
                }).json()
                final = _wait_for_status(auth_client, j["id"], ("completed",), timeout=45)
                assert final is not None
                time.sleep(1)
                disc = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": pid}).json()
                by_id = {it["id"]: it for it in disc["items"]}
                failed_ids = [i for i in ids if by_id.get(i, {}).get("checkpoint_status") == "failed"]
                success_ids = [i for i in ids if by_id.get(i, {}).get("checkpoint_status") == "success"]
                if failed_ids:
                    break
                # reset and retry
                auth_client.delete(f"{API}/projects/{pid}/services/exchange/checkpoint")

            if not failed_ids:
                pytest.skip("Could not produce any failed items after 4 attempts (simulation randomness)")

            # incremental with mix → should only pick failed ones
            all_ids = failed_ids + success_ids
            r_inc = auth_client.post(f"{API}/jobs", json={
                "project_id": pid, "service_type": "exchange",
                "item_ids": all_ids, "mode": "incremental", "concurrency": 3,
            })
            assert r_inc.status_code == 200, r_inc.text
            new_job = r_inc.json()
            assert new_job["total"] == len(failed_ids), f"expected {len(failed_ids)} items, got {new_job['total']}"
        finally:
            auth_client.delete(f"{API}/projects/{pid}")
