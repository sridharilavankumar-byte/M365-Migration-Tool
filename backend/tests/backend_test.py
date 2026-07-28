"""
Backend API tests for M365 Migration Suite.
Covers: health, auth (login/register/me/logout), projects CRUD, test-connection,
service discovery (9 services), job lifecycle (create/pause/resume/cancel/retry),
job logs, and dashboard stats.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://exchange-share-mover.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@migratetool.com"
ADMIN_PASSWORD = "Admin@12345"

SERVICE_TYPES = [
    "exchange", "sharepoint", "onedrive", "distribution_lists",
    "teams", "groups", "contacts", "calendars", "public_folders",
]


# ---------------- Fixtures ----------------
@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(api_client):
    r = api_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data
    return data["token"]


@pytest.fixture(scope="session")
def auth_client(api_client, admin_token):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"})
    return s


@pytest.fixture(scope="session")
def project_id(auth_client):
    payload = {
        "name": f"TEST_Project_{uuid.uuid4().hex[:8]}",
        "description": "pytest project",
        "source_tenant": {"domain": "source.onmicrosoft.com", "label": "src"},
        "destination_tenant": {"domain": "dest.onmicrosoft.com", "label": "dst"},
    }
    r = auth_client.post(f"{API}/projects", json=payload)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    yield pid
    # teardown
    try:
        auth_client.delete(f"{API}/projects/{pid}")
    except Exception:
        pass


# ---------------- Health ----------------
class TestHealth:
    def test_root(self, api_client):
        r = api_client.get(f"{API}/")
        assert r.status_code == 200
        data = r.json()
        assert data.get("service") == "M365 Migration Suite"
        assert "version" in data


# ---------------- Auth ----------------
class TestAuth:
    def test_login_success(self, api_client):
        r = api_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == ADMIN_EMAIL
        assert d["role"] == "admin"
        assert isinstance(d["token"], str) and len(d["token"]) > 20
        # cookie should be set
        assert "access_token" in r.cookies

    def test_login_invalid(self, api_client):
        r = api_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_me(self, auth_client):
        r = auth_client.get(f"{API}/auth/me")
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == ADMIN_EMAIL
        assert d["role"] == "admin"
        assert "password_hash" not in d

    def test_me_unauth(self, api_client):
        # Use fresh session (no shared cookies)
        fresh = requests.Session()
        r = fresh.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_register_operator(self, api_client):
        email = f"test_op_{uuid.uuid4().hex[:8]}@example.com"
        r = api_client.post(f"{API}/auth/register", json={"email": email, "password": "Passw0rd!", "name": "Test Op"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "operator"
        assert d["email"] == email
        assert "token" in d

    def test_logout(self, api_client):
        # login first
        r = api_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        r2 = api_client.post(f"{API}/auth/logout")
        assert r2.status_code == 200
        assert r2.json().get("ok") is True


# ---------------- Projects ----------------
class TestProjects:
    def test_list_projects(self, auth_client, project_id):
        r = auth_client.get(f"{API}/projects")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        assert any(p["id"] == project_id for p in items)

    def test_get_project(self, auth_client, project_id):
        r = auth_client.get(f"{API}/projects/{project_id}")
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == project_id
        assert d["source_tenant"]["domain"] == "source.onmicrosoft.com"
        assert d["destination_tenant"]["domain"] == "dest.onmicrosoft.com"

    def test_delete_and_recreate(self, auth_client):
        # Create a temp project, delete it, verify 404
        payload = {
            "name": f"TEST_Delete_{uuid.uuid4().hex[:6]}",
            "description": "",
            "source_tenant": {"domain": "s.onmicrosoft.com"},
            "destination_tenant": {"domain": "d.onmicrosoft.com"},
        }
        r = auth_client.post(f"{API}/projects", json=payload)
        assert r.status_code == 200
        pid = r.json()["id"]
        d = auth_client.delete(f"{API}/projects/{pid}")
        assert d.status_code == 200
        g = auth_client.get(f"{API}/projects/{pid}")
        assert g.status_code == 404

    def test_test_connection(self, auth_client, project_id):
        r = auth_client.post(f"{API}/projects/{project_id}/test-connection")
        assert r.status_code == 200
        d = r.json()
        assert d["source"]["ok"] is True
        assert d["destination"]["ok"] is True
        assert isinstance(d["source"]["latency_ms"], int)
        assert isinstance(d["destination"]["latency_ms"], int)


# ---------------- Service Discovery ----------------
class TestDiscovery:
    @pytest.mark.parametrize("service_type", SERVICE_TYPES)
    def test_discover_each_service(self, auth_client, project_id, service_type):
        r = auth_client.get(f"{API}/services/{service_type}/discover", params={"project_id": project_id})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["service_type"] == service_type
        assert d["total"] == len(d["items"])
        assert d["total"] > 0
        first = d["items"][0]
        assert "id" in first
        assert "display_name" in first

    def test_discover_deterministic(self, auth_client, project_id):
        r1 = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id}).json()
        r2 = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id}).json()
        assert [it["id"] for it in r1["items"]] == [it["id"] for it in r2["items"]]

    def test_unknown_service(self, auth_client, project_id):
        r = auth_client.get(f"{API}/services/unknown/discover", params={"project_id": project_id})
        assert r.status_code == 400


# ---------------- Jobs ----------------
class TestJobs:
    def _create_job(self, auth_client, project_id, service_type="exchange", n_items=3):
        disc = auth_client.get(f"{API}/services/{service_type}/discover", params={"project_id": project_id}).json()
        item_ids = [it["id"] for it in disc["items"][:n_items]]
        r = auth_client.post(f"{API}/jobs", json={
            "project_id": project_id,
            "service_type": service_type,
            "item_ids": item_ids,
            "mode": "full",
        })
        assert r.status_code == 200, r.text
        return r.json()

    def test_create_and_complete_job(self, auth_client, project_id):
        job = self._create_job(auth_client, project_id, "exchange", n_items=3)
        job_id = job["id"]
        assert job["status"] in ("queued", "running")
        assert job["total"] == 3

        # Poll for completion
        deadline = time.time() + 60
        final = None
        while time.time() < deadline:
            r = auth_client.get(f"{API}/jobs/{job_id}")
            assert r.status_code == 200
            j = r.json()
            if j["status"] in ("completed", "canceled"):
                final = j
                break
            time.sleep(1)

        assert final is not None, "Job did not complete in 60s"
        assert final["status"] == "completed"
        assert final["progress"] == 100
        assert final["completed_count"] == 3
        assert final["success_count"] + final["fail_count"] == 3

    def test_job_logs(self, auth_client, project_id):
        job = self._create_job(auth_client, project_id, "onedrive", n_items=2)
        job_id = job["id"]
        # wait a bit
        time.sleep(4)
        r = auth_client.get(f"{API}/jobs/{job_id}/logs")
        assert r.status_code == 200
        logs = r.json()
        assert isinstance(logs, list)
        assert len(logs) >= 1
        assert "message" in logs[0]

    def test_pause_resume(self, auth_client, project_id):
        job = self._create_job(auth_client, project_id, "sharepoint", n_items=5)
        job_id = job["id"]
        # wait until running
        for _ in range(10):
            j = auth_client.get(f"{API}/jobs/{job_id}").json()
            if j["status"] == "running":
                break
            time.sleep(0.5)
        r = auth_client.post(f"{API}/jobs/{job_id}/pause")
        assert r.status_code == 200
        # wait up to 3s for pause to take effect
        paused = False
        for _ in range(6):
            j = auth_client.get(f"{API}/jobs/{job_id}").json()
            if j["status"] == "paused":
                paused = True
                break
            time.sleep(0.5)
        assert paused, "Job did not transition to paused"
        r = auth_client.post(f"{API}/jobs/{job_id}/resume")
        assert r.status_code == 200
        j = auth_client.get(f"{API}/jobs/{job_id}").json()
        assert j["status"] in ("running", "completed")
        # cleanup - cancel
        auth_client.post(f"{API}/jobs/{job_id}/cancel")

    def test_cancel(self, auth_client, project_id):
        job = self._create_job(auth_client, project_id, "teams", n_items=8)
        job_id = job["id"]
        time.sleep(1)
        r = auth_client.post(f"{API}/jobs/{job_id}/cancel")
        assert r.status_code == 200
        # give it time to observe cancel
        time.sleep(2)
        j = auth_client.get(f"{API}/jobs/{job_id}").json()
        assert j["status"] == "canceled"

    def test_retry_failed(self, auth_client, project_id):
        # Create job with more items to increase failure probability
        job = self._create_job(auth_client, project_id, "groups", n_items=10)
        job_id = job["id"]
        deadline = time.time() + 60
        while time.time() < deadline:
            j = auth_client.get(f"{API}/jobs/{job_id}").json()
            if j["status"] == "completed":
                break
            time.sleep(1)
        j = auth_client.get(f"{API}/jobs/{job_id}").json()
        r = auth_client.post(f"{API}/jobs/{job_id}/retry-failed")
        assert r.status_code == 200
        d = r.json()
        if j["fail_count"] > 0:
            assert d["ok"] is True
            assert d["retried"] == j["fail_count"]
        else:
            # no failures to retry
            assert d["ok"] is False

    def test_list_jobs_by_project(self, auth_client, project_id):
        r = auth_client.get(f"{API}/jobs", params={"project_id": project_id})
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        assert len(items) >= 1


# ---------------- Dashboard ----------------
class TestDashboard:
    def test_stats(self, auth_client, project_id):
        r = auth_client.get(f"{API}/dashboard/stats")
        assert r.status_code == 200
        d = r.json()
        for key in ["total_projects", "total_jobs", "running_jobs", "completed_jobs",
                    "items_success", "items_failed", "items_total", "by_service", "recent_jobs"]:
            assert key in d, f"missing key {key}"
        assert d["total_projects"] >= 1
        assert isinstance(d["by_service"], list)
        assert isinstance(d["recent_jobs"], list)
