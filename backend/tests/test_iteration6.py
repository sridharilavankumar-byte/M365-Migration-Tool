"""
Iteration 6 backend tests — Real per-service content migration via Microsoft Graph.

Test scope (Azure creds NOT available — everything is verified either against
simulated mode, via HTTP surface behaviour, or via in-process monkeypatching):

1. graph_migrations module loads without import errors and DISPATCH has 9 keys
   matching the 9 service_types, each an async function.
2. graph_adapter.migrate_item return shape:
     - simulated (no creds): {status, error, duration_ms, stats:{}}
     - live w/ bad creds: {status:'failed', error:<msg>, duration_ms, stats:{}}
3. public_folders live-mode returns an unsupported error naming Graph +
   'Public Folders' + MRS/3rd-party guidance.
4. Regression — simulated project full job cycle: 5 exchange items,
   status=completed, progress=100, success+fail=5, each item has 'stats'
   (possibly {}).
5. Regression — all 9 service_types discoverable in simulated mode & job
   creation queues successfully for each.
6. Live-mode dispatch pre-flight: project with fake creds → POST /api/jobs
   returns HTTP 400 with 'Graph discovery failed' detail (NOT 500).
7. Stats persistence: monkeypatch graph_adapter.migrate_item in-process,
   invoke server._process_item directly, and verify:
     - db.jobs.items.$.stats == returned stats
     - db.jobs.aggregate_stats.<key> == $inc'd
"""
import asyncio
import inspect
import os
import sys
import time
import uuid

import pytest
import requests
from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip()
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@migratetool.com"
ADMIN_PASSWORD = "Admin@12345"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

SERVICE_TYPES = [
    "exchange", "sharepoint", "onedrive", "distribution_lists",
    "teams", "groups", "contacts", "calendars", "public_folders",
]


# ------------------------------ fixtures ------------------------------
@pytest.fixture(scope="module")
def auth_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"login failed: {r.text}"
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="module")
def mongo_db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def cleanup():
    tracker = {"projects": [], "jobs": [], "connections": []}
    yield tracker
    # Best-effort cleanup via HTTP
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code == 200:
        s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
        for pid in tracker["projects"]:
            try: s.delete(f"{API}/projects/{pid}")
            except Exception: pass
        for cid in tracker["connections"]:
            try: s.delete(f"{API}/tenant-connections/{cid}")
            except Exception: pass


@pytest.fixture(scope="module")
def sim_project_id(auth_client, cleanup):
    body = {
        "name": f"TEST_Iter6_Sim_{uuid.uuid4().hex[:6]}",
        "description": "iter6 simulated project",
        "source_tenant": {"domain": "src.com"},
        "destination_tenant": {"domain": "dst.com"},
    }
    r = auth_client.post(f"{API}/projects", json=body)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    cleanup["projects"].append(pid)
    return pid


@pytest.fixture(scope="module")
def live_fake_project_id(auth_client, cleanup):
    """Project with fake but structurally valid creds → live-mode path."""
    body = {
        "name": f"TEST_Iter6_Live_{uuid.uuid4().hex[:6]}",
        "description": "iter6 live-mode fake creds project",
        "source_tenant": {
            "tenant_id": str(uuid.uuid4()),
            "domain": "src.onmicrosoft.com",
            "client_id": str(uuid.uuid4()),
            "client_secret": "fake-secret-for-iter6-tests",
            "label": "src",
        },
        "destination_tenant": {
            "tenant_id": str(uuid.uuid4()),
            "domain": "dst.onmicrosoft.com",
            "client_id": str(uuid.uuid4()),
            "client_secret": "fake-secret-for-iter6-tests-dst",
            "label": "dst",
        },
    }
    r = auth_client.post(f"{API}/projects", json=body)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    cleanup["projects"].append(pid)
    return pid


# ==================== 1. DISPATCH module correctness ====================
class TestDispatchModule:

    def test_import_and_dispatch_shape(self):
        import graph_migrations as gm
        assert hasattr(gm, "DISPATCH")
        assert isinstance(gm.DISPATCH, dict)
        expected = set(SERVICE_TYPES)
        actual = set(gm.DISPATCH.keys())
        assert actual == expected, f"DISPATCH keys mismatch: missing={expected-actual}, extra={actual-expected}"
        assert len(gm.DISPATCH) == 9

    def test_every_dispatch_entry_is_async_fn(self):
        import graph_migrations as gm
        for k, v in gm.DISPATCH.items():
            assert callable(v), f"{k} is not callable"
            assert inspect.iscoroutinefunction(v), f"{k} is not async"

    def test_dispatcher_signatures(self):
        """Each fn takes (item, src, dst, _graph_request)."""
        import graph_migrations as gm
        for k, fn in gm.DISPATCH.items():
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            assert len(params) == 4, f"{k}: expected 4 params, got {params}"


# ==================== 2. migrate_item return shape ====================
class TestMigrateItemShape:

    def test_simulated_shape(self):
        import graph_adapter
        async def run():
            return await graph_adapter.migrate_item(
                "exchange", {"id": "x", "display_name": "y"}, {}, {}
            )
        r = asyncio.run(run())
        assert set(r.keys()) >= {"status", "error", "duration_ms", "stats"}
        assert r["status"] in ("success", "failed")
        assert r["stats"] == {}
        assert isinstance(r["duration_ms"], int)

    def test_live_bad_creds_shape(self):
        import graph_adapter
        bad = {
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "client_id": "00000000-0000-0000-0000-000000000000",
            "client_secret": "bad-secret",
        }
        async def run():
            return await graph_adapter.migrate_item(
                "exchange", {"id": "x", "display_name": "y"}, bad, bad
            )
        r = asyncio.run(run())
        assert r["status"] == "failed"
        assert isinstance(r["error"], str) and len(r["error"]) > 0
        assert isinstance(r["duration_ms"], int)
        assert r["stats"] == {}

    def test_live_unknown_service_type(self):
        import graph_adapter
        bad = {
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "client_id": "00000000-0000-0000-0000-000000000000",
            "client_secret": "bad",
        }
        async def run():
            return await graph_adapter.migrate_item(
                "not_a_real_service", {"id": "x", "display_name": "y"}, bad, bad
            )
        r = asyncio.run(run())
        assert r["status"] == "failed"
        # Bad creds may fail at acquire_token first, or at dispatch lookup —
        # either way it's a failed dict with stats={}.
        assert r["stats"] == {}


# ==================== 3. public_folders unsupported message ====================
class TestPublicFoldersUnsupported:

    def test_migrate_public_folder_returns_structured_unsupported(self):
        import graph_migrations as gm
        async def run():
            return await gm.migrate_public_folder(
                {"id": "pf_1", "display_name": "x"}, {}, {}, None
            )
        r = asyncio.run(run())
        assert r["status"] == "failed"
        err = r.get("error") or ""
        assert "Public Folders" in err, f"missing 'Public Folders' in: {err!r}"
        assert ("MRS" in err) or ("3rd-party" in err) or ("PowerShell" in err), (
            f"missing MRS / 3rd-party guidance in: {err!r}"
        )
        assert r["stats"] == {}


# ==================== 4. Simulated regression — exchange, 5 items ====================
class TestSimulatedRegression:

    def test_full_exchange_job_5_items_with_stats_field(
        self, auth_client, sim_project_id
    ):
        # Discover
        r = auth_client.get(
            f"{API}/services/exchange/discover",
            params={"project_id": sim_project_id},
        )
        assert r.status_code == 200
        assert r.json()["mode"] == "simulated"
        item_ids = [it["id"] for it in r.json()["items"][:5]]
        assert len(item_ids) == 5

        # Create job
        r = auth_client.post(f"{API}/jobs", json={
            "project_id": sim_project_id,
            "service_type": "exchange",
            "item_ids": item_ids,
            "mode": "full",
            "concurrency": 3,
        })
        assert r.status_code == 200, r.text
        job_id = r.json()["id"]

        # Poll for completion (max ~30s)
        deadline = time.time() + 30
        final = None
        while time.time() < deadline:
            g = auth_client.get(f"{API}/jobs/{job_id}")
            assert g.status_code == 200
            final = g.json()
            if final["status"] in ("completed", "canceled"):
                break
            time.sleep(0.5)

        assert final is not None
        assert final["status"] == "completed", f"job did not complete: {final}"
        assert final["progress"] == 100
        assert final["success_count"] + final["fail_count"] == 5
        for it in final["items"]:
            assert it["status"] in ("success", "failed")
            # NEW iter6 requirement — every item has a 'stats' field (may be {})
            assert "stats" in it, f"item missing stats field: {it}"
            assert isinstance(it["stats"], dict)


# ==================== 5. All 9 service_types discoverable + job-creatable ====================
class TestAllServiceTypesJobCreatable:

    @pytest.mark.parametrize("service_type", SERVICE_TYPES)
    def test_discover_and_create_job(self, auth_client, sim_project_id, service_type):
        r = auth_client.get(
            f"{API}/services/{service_type}/discover",
            params={"project_id": sim_project_id},
        )
        assert r.status_code == 200, f"{service_type} discover: {r.text}"
        data = r.json()
        assert data["mode"] == "simulated"
        assert data["total"] > 0, f"{service_type} returned 0 items"

        item_ids = [it["id"] for it in data["items"][:2]]
        r = auth_client.post(f"{API}/jobs", json={
            "project_id": sim_project_id,
            "service_type": service_type,
            "item_ids": item_ids,
            "mode": "full",
            "concurrency": 2,
        })
        assert r.status_code == 200, f"{service_type} create_job: {r.text}"
        job = r.json()
        assert job["status"] in ("queued", "running")
        assert job["total"] == len(item_ids)


# ==================== 6. Live-mode dispatch pre-flight → clean 400 ====================
class TestLiveModeDispatchPreflight:

    def test_create_job_with_fake_creds_returns_400_graph_failure(
        self, auth_client, live_fake_project_id
    ):
        """Live-mode: create_job calls _discover which calls DISCOVERY_MAP,
        MSAL fails on fake tenant_id, and _discover raises HTTPException(400)
        with 'Graph discovery failed:' prefix. Must NOT be 500."""
        r = auth_client.post(f"{API}/jobs", json={
            "project_id": live_fake_project_id,
            "service_type": "exchange",
            "item_ids": ["mbx_0001"],  # arbitrary, since discovery will fail first
            "mode": "full",
            "concurrency": 1,
        })
        assert r.status_code == 400, (
            f"expected 400 for live-mode with bad creds, got {r.status_code}: {r.text}"
        )
        detail = (r.json().get("detail") or "").lower()
        assert "graph discovery failed" in detail, (
            f"expected 'Graph discovery failed' in detail, got: {detail!r}"
        )


# ==================== 7. Stats persistence via in-process _process_item ====================
class TestStatsPersistence:
    """Directly invoke server._process_item with a monkeypatched
    graph_adapter.migrate_item, then verify the Mongo doc has:
      - items.0.stats == returned stats
      - aggregate_stats.<numeric key> incremented
    """

    def test_process_item_persists_item_stats_and_aggregate(self, mongo_db):
        # Late import so pytest collection isn't affected by server-side deps
        import server, graph_adapter, checkpoints as cp
        from motor.motor_asyncio import AsyncIOMotorClient

        # Insert a fake job doc with 1 pending item
        item = {
            "id": f"iter6_item_{uuid.uuid4().hex[:8]}",
            "display_name": "Iter6 Fake Item",
            "meta": {},
            "status": "pending",
            "error": None,
            "finished_at": None,
        }
        job_doc = {
            "project_id": "iter6_fake_project",
            "project_name": "Iter6 Fake Project",
            "service_type": "exchange",
            "mode": "full",
            "concurrency": 1,
            "items": [item],
            "status": "running",
            "progress": 0,
            "success_count": 0,
            "fail_count": 0,
            "completed_count": 0,
            "total": 1,
            "created_by": "iter6_test",
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": None,
        }
        r = mongo_db.jobs.insert_one(job_doc)
        job_id = str(r.inserted_id)

        # Save originals for restoration
        orig_migrate = graph_adapter.migrate_item
        orig_record = cp.record_item_result
        orig_db = server.db

        async def fake_migrate_item(service_type, item, src_cfg, dst_cfg):
            return {
                "status": "success",
                "error": None,
                "duration_ms": 100,
                "stats": {"messages_copied": 5, "bytes": 1024, "folders_copied": 2},
            }

        async def noop_record(*a, **k):
            return None

        try:
            async def _run():
                # Bind motor to this loop
                mclient = AsyncIOMotorClient(MONGO_URL)
                server.db = mclient[DB_NAME]
                graph_adapter.migrate_item = fake_migrate_item
                cp.record_item_result = noop_record

                sem = asyncio.Semaphore(1)
                await server._process_item(
                    job_id, item, "exchange", {}, {}, sem, 1,
                )
                mclient.close()

            asyncio.run(_run())

            # Verify persistence via pymongo
            updated = mongo_db.jobs.find_one({"_id": ObjectId(job_id)})
            assert updated is not None
            assert updated["items"][0]["status"] == "success"
            assert updated["items"][0]["error"] is None
            assert updated["items"][0]["stats"] == {
                "messages_copied": 5, "bytes": 1024, "folders_copied": 2,
            }
            agg = updated.get("aggregate_stats", {})
            assert agg.get("messages_copied") == 5, f"aggregate_stats={agg}"
            assert agg.get("bytes") == 1024, f"aggregate_stats={agg}"
            assert agg.get("folders_copied") == 2, f"aggregate_stats={agg}"
            assert updated["success_count"] == 1
            assert updated["fail_count"] == 0
            assert updated["completed_count"] == 1
            assert updated["progress"] == 100
        finally:
            graph_adapter.migrate_item = orig_migrate
            cp.record_item_result = orig_record
            server.db = orig_db
            mongo_db.jobs.delete_one({"_id": ObjectId(job_id)})
            mongo_db.logs.delete_many({"job_id": job_id})

    def test_process_item_empty_stats_does_not_touch_aggregate(self, mongo_db):
        """Simulated-mode (stats={}) must NOT add an aggregate_stats field."""
        import server, graph_adapter, checkpoints as cp
        from motor.motor_asyncio import AsyncIOMotorClient

        item = {
            "id": f"iter6_empty_{uuid.uuid4().hex[:8]}",
            "display_name": "Iter6 Empty Stats",
            "meta": {},
            "status": "pending",
            "error": None,
            "finished_at": None,
        }
        job_doc = {
            "project_id": "iter6_fake_project",
            "project_name": "Iter6 Empty",
            "service_type": "exchange",
            "mode": "full",
            "concurrency": 1,
            "items": [item],
            "status": "running",
            "progress": 0,
            "success_count": 0,
            "fail_count": 0,
            "completed_count": 0,
            "total": 1,
            "created_by": "iter6_test",
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": None,
        }
        r = mongo_db.jobs.insert_one(job_doc)
        job_id = str(r.inserted_id)

        orig_migrate = graph_adapter.migrate_item
        orig_record = cp.record_item_result
        orig_db = server.db

        async def fake_migrate_item(service_type, item, src_cfg, dst_cfg):
            return {"status": "success", "error": None, "duration_ms": 50, "stats": {}}

        async def noop_record(*a, **k):
            return None

        try:
            async def _run():
                mclient = AsyncIOMotorClient(MONGO_URL)
                server.db = mclient[DB_NAME]
                graph_adapter.migrate_item = fake_migrate_item
                cp.record_item_result = noop_record
                sem = asyncio.Semaphore(1)
                await server._process_item(job_id, item, "exchange", {}, {}, sem, 1)
                mclient.close()

            asyncio.run(_run())

            updated = mongo_db.jobs.find_one({"_id": ObjectId(job_id)})
            assert updated["items"][0]["stats"] == {}
            # aggregate_stats should be absent (or empty dict)
            agg = updated.get("aggregate_stats")
            assert agg is None or agg == {}, (
                f"empty stats should NOT populate aggregate_stats, got {agg!r}"
            )
        finally:
            graph_adapter.migrate_item = orig_migrate
            cp.record_item_result = orig_record
            server.db = orig_db
            mongo_db.jobs.delete_one({"_id": ObjectId(job_id)})
            mongo_db.logs.delete_many({"job_id": job_id})
