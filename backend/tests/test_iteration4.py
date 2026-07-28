"""
Iteration 4 backend tests — Tenant Connections (saved Azure AD credential profiles).

Endpoints covered:
- POST   /api/tenant-connections        (create; response has masked secret, no client_secret)
- GET    /api/tenant-connections        (list; masked secrets)
- GET    /api/tenant-connections/{id}   (masked)
- GET    /api/tenant-connections/{id}?reveal=true (plaintext secret)
- PUT    /api/tenant-connections/{id}   (empty client_secret preserves stored; non-empty updates)
- DELETE /api/tenant-connections/{id}
- POST   /api/tenant-connections/{id}/test (real MSAL, ok:false with authority-config fail)

Regression: does NOT break projects/jobs/schedules from iter 1..3.
"""
import os
import uuid
import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip()
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@migratetool.com"
ADMIN_PASSWORD = "Admin@12345"


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def auth_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"login failed: {r.text}"
    token = r.json()["token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def created_ids():
    ids = []
    yield ids
    # teardown-safe delete
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code == 200:
        s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
        for cid in ids:
            try:
                s.delete(f"{API}/tenant-connections/{cid}")
            except Exception:
                pass


def _sample_payload(label_suffix=""):
    return {
        "label": f"TEST_Iter4_{label_suffix or uuid.uuid4().hex[:8]}",
        "domain": "contoso.onmicrosoft.com",
        "tenant_id": str(uuid.uuid4()),
        "client_id": str(uuid.uuid4()),
        "client_secret": f"secret_{uuid.uuid4().hex}",  # 39 chars, plenty to mask
        "notes": "iter4 pytest connection",
    }


# ---------------- tests ----------------
class TestTenantConnectionsCRUD:
    def test_create_masks_secret(self, auth_client, created_ids):
        payload = _sample_payload("create")
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "id" in data
        assert data["label"] == payload["label"]
        assert data["tenant_id"] == payload["tenant_id"]
        assert data["client_id"] == payload["client_id"]
        # Secret masking
        assert "client_secret" not in data, "raw client_secret must NOT leak in create response"
        assert "client_secret_masked" in data
        masked = data["client_secret_masked"]
        original = payload["client_secret"]
        assert masked != original, "masked must differ from original"
        assert masked.startswith(original[:2]), f"mask should keep first 2 chars; got {masked}"
        assert masked.endswith(original[-4:]), f"mask should keep last 4 chars; got {masked}"
        assert "•" in masked, "mask must contain bullet chars"
        created_ids.append(data["id"])

    def test_list_returns_masked(self, auth_client, created_ids):
        # ensure at least one exists
        if not created_ids:
            r = auth_client.post(f"{API}/tenant-connections", json=_sample_payload("list"))
            created_ids.append(r.json()["id"])
        r = auth_client.get(f"{API}/tenant-connections")
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list)
        assert len(arr) >= 1
        for item in arr:
            assert "client_secret" not in item, f"client_secret leaked in list item {item.get('id')}"
            assert "client_secret_masked" in item

    def test_get_without_reveal_is_masked(self, auth_client, created_ids):
        cid = created_ids[0]
        r = auth_client.get(f"{API}/tenant-connections/{cid}")
        assert r.status_code == 200
        data = r.json()
        assert "client_secret" not in data
        assert "client_secret_masked" in data

    def test_get_with_reveal_returns_plaintext(self, auth_client, created_ids):
        # Create fresh so we know the exact secret
        payload = _sample_payload("reveal")
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        cid = r.json()["id"]
        created_ids.append(cid)
        r = auth_client.get(f"{API}/tenant-connections/{cid}?reveal=true")
        assert r.status_code == 200
        data = r.json()
        assert data.get("client_secret") == payload["client_secret"], (
            f"reveal=true should return full plaintext client_secret, got: {data.get('client_secret')}"
        )
        # When reveal=true the masked field should be absent per _connection_out
        assert "client_secret_masked" not in data

    def test_put_empty_secret_preserves_existing(self, auth_client, created_ids):
        payload = _sample_payload("preserve")
        original_secret = payload["client_secret"]
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        cid = r.json()["id"]
        created_ids.append(cid)

        update_body = {
            "label": payload["label"] + "_updated",
            "domain": payload["domain"],
            "tenant_id": payload["tenant_id"],
            "client_id": payload["client_id"],
            "client_secret": "",  # empty → preserve
            "notes": "updated with empty secret",
        }
        r = auth_client.put(f"{API}/tenant-connections/{cid}", json=update_body)
        assert r.status_code == 200, r.text
        # Verify secret preserved via reveal
        r = auth_client.get(f"{API}/tenant-connections/{cid}?reveal=true")
        assert r.status_code == 200
        assert r.json().get("client_secret") == original_secret, (
            "PUT with empty client_secret must preserve original secret"
        )
        # Also verify other fields updated
        assert r.json().get("label") == update_body["label"]
        assert r.json().get("notes") == update_body["notes"]

    def test_put_nonempty_secret_updates(self, auth_client, created_ids):
        payload = _sample_payload("update")
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        cid = r.json()["id"]
        created_ids.append(cid)

        new_secret = f"newsecret_{uuid.uuid4().hex}"
        update_body = {**payload, "client_secret": new_secret}
        r = auth_client.put(f"{API}/tenant-connections/{cid}", json=update_body)
        assert r.status_code == 200
        r = auth_client.get(f"{API}/tenant-connections/{cid}?reveal=true")
        assert r.json().get("client_secret") == new_secret, "non-empty PUT must update the secret"

    def test_delete_removes_and_404(self, auth_client):
        payload = _sample_payload("delete")
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        cid = r.json()["id"]
        r = auth_client.delete(f"{API}/tenant-connections/{cid}")
        assert r.status_code == 200
        r = auth_client.get(f"{API}/tenant-connections/{cid}")
        assert r.status_code == 404

    def test_put_nonexistent_returns_404(self, auth_client):
        fake_id = "507f1f77bcf86cd799439011"  # valid ObjectId shape
        r = auth_client.put(f"{API}/tenant-connections/{fake_id}",
                            json=_sample_payload("nope"))
        assert r.status_code == 404


# ---------------- /test endpoint ----------------
class TestTenantConnectionLive:
    def test_test_endpoint_fake_creds_returns_live_failure(self, auth_client, created_ids):
        """Fake tenant_id/client_id/secret → MSAL will fail resolving authority.
        Expected: ok=false, mode='live', message includes auth-failure text, latency populated."""
        payload = _sample_payload("live_test")
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        cid = r.json()["id"]
        created_ids.append(cid)
        r = auth_client.post(f"{API}/tenant-connections/{cid}/test")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, f"fake creds should NOT auth successfully: {data}"
        assert data.get("mode") == "live", f"expected mode=live for configured creds: {data}"
        assert isinstance(data.get("latency_ms"), int) and data["latency_ms"] >= 0
        assert "message" in data and isinstance(data["message"], str) and len(data["message"]) > 0
        # message should reference authority / config / tenant failure
        msg = data["message"].lower()
        assert any(k in msg for k in [
            "authority", "tenant", "unable", "config", "token", "aadsts", "acquisition",
        ]), f"unexpected failure message: {data['message']}"

    def test_test_endpoint_404_for_missing(self, auth_client):
        fake_id = "507f1f77bcf86cd799439011"
        r = auth_client.post(f"{API}/tenant-connections/{fake_id}/test")
        assert r.status_code == 404


# ---------------- integration: project autofill from saved connection ----------------
class TestProjectAutofillFromConnection:
    def test_create_project_using_saved_connection_full_secret(self, auth_client, created_ids):
        """Simulates the frontend flow: create a saved connection, fetch with
        reveal=true, embed the full secret in the create-project payload,
        then verify the project doc stored the tenant_id + client_secret."""
        payload = _sample_payload("proj_autofill")
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        assert r.status_code == 200
        cid = r.json()["id"]
        created_ids.append(cid)

        r = auth_client.get(f"{API}/tenant-connections/{cid}?reveal=true")
        assert r.status_code == 200
        conn = r.json()
        assert conn["client_secret"] == payload["client_secret"]

        proj_body = {
            "name": f"TEST_Iter4_Autofill_{uuid.uuid4().hex[:8]}",
            "description": "iter4 autofill regression",
            "source_tenant": {
                "label": conn["label"],
                "domain": conn["domain"],
                "tenant_id": conn["tenant_id"],
                "client_id": conn["client_id"],
                "client_secret": conn["client_secret"],
            },
            "destination_tenant": {
                "label": "dst",
                "domain": "dest.onmicrosoft.com",
            },
        }
        r = auth_client.post(f"{API}/projects", json=proj_body)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]

        r = auth_client.get(f"{API}/projects/{pid}")
        assert r.status_code == 200
        p = r.json()
        assert p["source_tenant"]["tenant_id"] == payload["tenant_id"]
        assert p["source_tenant"]["client_id"] == payload["client_id"]
        # Iter5: project response NEVER includes client_secret; has_secret bool instead.
        assert "client_secret" not in p["source_tenant"], (
            "iter5: project response must not leak source_tenant.client_secret"
        )
        assert p["source_tenant"].get("has_secret") is True, (
            "iter5: has_secret must be True when a secret was submitted"
        )
        # cleanup
        auth_client.delete(f"{API}/projects/{pid}")


# ---------------- regression sanity ----------------
class TestRegressionSmoke:
    def test_projects_list_still_works(self, auth_client):
        r = auth_client.get(f"{API}/projects")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_dashboard_stats_still_works(self, auth_client):
        r = auth_client.get(f"{API}/dashboard/stats")
        assert r.status_code == 200
        d = r.json()
        for k in ("total_projects", "total_jobs", "running_jobs", "items_success"):
            assert k in d

    def test_schedules_list_still_works(self, auth_client):
        r = auth_client.get(f"{API}/schedules")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
