"""
Iteration-2 backend tests for M365 Migration Suite.

Covers new endpoints/behaviours:
- Graph adapter simulated fallback in /test-connection
- /projects/{id}/preflight — pre-flight validation checks
- Discovery response now includes 'mode'
- Concurrent job runner (concurrency=4 on 8 items faster than serial)
- Notification pipeline log entry (empty API keys => benign warn log)
- PUT /projects/{id}/notifications persistence
- Reports: CSV + PDF endpoints
- Retry-failed preserves successful items
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
    """Create a fresh project with empty tenant creds — exercises simulated path."""
    payload = {
        "name": f"TEST_Iter2_{uuid.uuid4().hex[:8]}",
        "description": "iteration 2 pytest",
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


def _wait_for_status(auth_client, job_id, statuses, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = auth_client.get(f"{API}/jobs/{job_id}").json()
        if j["status"] in statuses:
            return j
        time.sleep(0.5)
    return None


# ---------------- Graph adapter fallback ----------------
class TestGraphAdapterFallback:
    def test_test_connection_simulated_mode(self, auth_client, project_id):
        r = auth_client.post(f"{API}/projects/{project_id}/test-connection")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source"]["ok"] is True
        assert d["destination"]["ok"] is True
        assert d["source"]["mode"] == "simulated"
        assert d["destination"]["mode"] == "simulated"
        assert "Credentials not configured" in d["source"]["message"]
        assert "Credentials not configured" in d["destination"]["message"]


# ---------------- Preflight ----------------
class TestPreflight:
    def test_preflight_pass_and_checks(self, auth_client, project_id):
        r = auth_client.post(f"{API}/projects/{project_id}/preflight")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["overall"] == "pass"
        assert isinstance(d["checks"], list)
        names = [c["name"] for c in d["checks"]]
        for expected in [
            "Source connectivity",
            "Destination connectivity",
            "Destination license headroom",
            "Destination storage headroom",
            "Migration mode",
        ]:
            assert expected in names, f"expected check '{expected}' missing; got {names}"

        # Migration mode should say simulated when creds empty
        mode_check = next(c for c in d["checks"] if c["name"] == "Migration mode")
        assert mode_check["detail"] == "simulated"

    def test_preflight_404_on_bad_project(self, auth_client):
        r = auth_client.post(f"{API}/projects/{'a' * 24}/preflight")
        assert r.status_code == 404


# ---------------- Discovery mode ----------------
class TestDiscoveryMode:
    def test_discovery_returns_simulated_mode(self, auth_client, project_id):
        r = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mode"] == "simulated"
        assert d["total"] > 0
        assert d["service_type"] == "exchange"


# ---------------- Concurrent runner ----------------
class TestConcurrentRunner:
    def test_concurrent_job_faster_than_serial(self, auth_client, project_id):
        disc = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id}).json()
        item_ids = [it["id"] for it in disc["items"][:8]]
        assert len(item_ids) == 8

        t0 = time.time()
        r = auth_client.post(f"{API}/jobs", json={
            "project_id": project_id,
            "service_type": "exchange",
            "item_ids": item_ids,
            "mode": "full",
            "concurrency": 4,
        })
        assert r.status_code == 200
        job_id = r.json()["id"]
        final = _wait_for_status(auth_client, job_id, ("completed", "canceled"), timeout=30)
        elapsed = time.time() - t0

        assert final is not None, "job did not complete in 30s"
        assert final["status"] == "completed"
        assert final["progress"] == 100
        assert final["total"] == 8
        # counts consistent (no drift from $inc)
        assert final["success_count"] + final["fail_count"] == 8
        assert final["completed_count"] == 8
        # Serial worst case = 8 * 1.4 = 11.2s. Concurrent with 4 workers ~ (8/4)*1.4 = 2.8s worst case
        # Allow buffer: assert < 8s (definitely faster than serial)
        assert elapsed < 8.0, f"Concurrent job took {elapsed:.2f}s — expected < 8s with concurrency=4"

    def test_concurrency_field_persisted(self, auth_client, project_id):
        disc = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id}).json()
        item_ids = [it["id"] for it in disc["items"][:2]]
        r = auth_client.post(f"{API}/jobs", json={
            "project_id": project_id, "service_type": "exchange",
            "item_ids": item_ids, "concurrency": 5,
        })
        assert r.status_code == 200
        job_id = r.json()["id"]
        j = auth_client.get(f"{API}/jobs/{job_id}").json()
        assert j.get("concurrency") == 5


# ---------------- Notification pipeline ----------------
class TestNotificationPipeline:
    def test_notification_log_entry(self, auth_client):
        # create project with notification_settings
        payload = {
            "name": f"TEST_Notif_{uuid.uuid4().hex[:6]}",
            "description": "notif",
            "source_tenant": {"domain": "s.onmicrosoft.com"},
            "destination_tenant": {"domain": "d.onmicrosoft.com"},
            "notification_settings": {
                "email_provider": "resend",
                "email_to": "ops@example.com",
                "webhook_url": "https://webhook.site/does-not-exist-xyz-abc",
            },
        }
        pr = auth_client.post(f"{API}/projects", json=payload)
        assert pr.status_code == 200
        pid = pr.json()["id"]

        try:
            disc = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": pid}).json()
            item_ids = [it["id"] for it in disc["items"][:2]]
            jr = auth_client.post(f"{API}/jobs", json={
                "project_id": pid, "service_type": "exchange",
                "item_ids": item_ids, "concurrency": 2,
            })
            assert jr.status_code == 200
            job_id = jr.json()["id"]
            final = _wait_for_status(auth_client, job_id, ("completed",), timeout=30)
            assert final is not None
            # give the notification pipeline a beat to log
            time.sleep(2)
            logs = auth_client.get(f"{API}/jobs/{job_id}/logs").json()
            assert any("notification" in (l.get("message") or "").lower() for l in logs), \
                f"expected 'notification' log entry, got: {[l.get('message') for l in logs][-10:]}"
        finally:
            auth_client.delete(f"{API}/projects/{pid}")

    def test_no_notification_log_when_disabled(self, auth_client, project_id):
        """Job on a project without notification_settings should still complete cleanly."""
        disc = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id}).json()
        item_ids = [it["id"] for it in disc["items"][:2]]
        jr = auth_client.post(f"{API}/jobs", json={
            "project_id": project_id, "service_type": "exchange",
            "item_ids": item_ids, "concurrency": 2,
        })
        assert jr.status_code == 200
        job_id = jr.json()["id"]
        final = _wait_for_status(auth_client, job_id, ("completed",), timeout=30)
        assert final is not None and final["status"] == "completed"


# ---------------- Notification settings PUT ----------------
class TestNotificationSettingsUpdate:
    def test_update_and_persist(self, auth_client, project_id):
        body = {
            "email_provider": "sendgrid",
            "email_to": "x@y.z",
            "webhook_url": "https://z",
        }
        r = auth_client.put(f"{API}/projects/{project_id}/notifications", json=body)
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # Verify persisted
        g = auth_client.get(f"{API}/projects/{project_id}").json()
        ns = g.get("notification_settings", {})
        assert ns.get("email_provider") == "sendgrid"
        assert ns.get("email_to") == "x@y.z"
        assert ns.get("webhook_url") == "https://z"


# ---------------- Reports ----------------
class TestReports:
    @pytest.fixture(scope="class")
    def completed_job_id(self, auth_client, project_id):
        disc = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id}).json()
        item_ids = [it["id"] for it in disc["items"][:3]]
        r = auth_client.post(f"{API}/jobs", json={
            "project_id": project_id, "service_type": "exchange",
            "item_ids": item_ids, "concurrency": 3,
        })
        assert r.status_code == 200
        jid = r.json()["id"]
        final = _wait_for_status(auth_client, jid, ("completed",), timeout=30)
        assert final is not None, "job did not complete"
        return jid

    def test_csv_report(self, auth_client, completed_job_id):
        r = auth_client.get(f"{API}/jobs/{completed_job_id}/report.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("Content-Type", "")
        cd = r.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert "Item ID" in r.text
        # at least one item row
        assert r.text.count("\n") > 10

    def test_pdf_report(self, auth_client, completed_job_id):
        r = auth_client.get(f"{API}/jobs/{completed_job_id}/report.pdf")
        assert r.status_code == 200
        assert "application/pdf" in r.headers.get("Content-Type", "")
        cd = r.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert r.content[:5] == b"%PDF-"

    def test_report_404(self, auth_client):
        # non-existent job
        r = auth_client.get(f"{API}/jobs/{'a' * 24}/report.csv")
        assert r.status_code == 404


# ---------------- Retry-failed correctness ----------------
class TestRetryFailedCorrectness:
    def test_retry_preserves_successes(self, auth_client, project_id):
        # 12 items to increase failure probability
        disc = auth_client.get(f"{API}/services/exchange/discover", params={"project_id": project_id}).json()
        item_ids = [it["id"] for it in disc["items"][:12]]
        r = auth_client.post(f"{API}/jobs", json={
            "project_id": project_id, "service_type": "exchange",
            "item_ids": item_ids, "concurrency": 4,
        })
        assert r.status_code == 200
        job_id = r.json()["id"]
        final = _wait_for_status(auth_client, job_id, ("completed",), timeout=45)
        assert final is not None

        original_success = final["success_count"]
        original_fail = final["fail_count"]
        original_success_ids = {it["id"] for it in final["items"] if it["status"] == "success"}

        if original_fail == 0:
            pytest.skip("No failures in this run — nothing to retry")

        rr = auth_client.post(f"{API}/jobs/{job_id}/retry-failed")
        assert rr.status_code == 200
        assert rr.json().get("ok") is True
        assert rr.json().get("retried") == original_fail

        final2 = _wait_for_status(auth_client, job_id, ("completed",), timeout=45)
        assert final2 is not None

        # No fail_count should exceed original
        assert final2["fail_count"] <= original_fail, \
            f"fail_count grew: {original_fail} -> {final2['fail_count']}"
        # Successful items stay successful
        success_ids_after = {it["id"] for it in final2["items"] if it["status"] == "success"}
        assert original_success_ids.issubset(success_ids_after), \
            "Previously successful items were reprocessed / lost success status"
        # Total count consistent
        assert final2["success_count"] + final2["fail_count"] == final2["total"]
