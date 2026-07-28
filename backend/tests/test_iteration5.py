"""
Iteration 5 backend tests — Secret encryption at rest.

Covers:
- POST/GET/PUT /api/tenant-connections encrypts client_secret in Mongo
  (raw doc starts with 'enc:v1:'), masks in response, reveals plaintext.
- PUT with empty client_secret preserves the encrypted value (still enc:v1:).
- PUT with a new client_secret re-encrypts (different token than before).
- POST /api/tenant-connections/{id}/test uses decrypted secret with MSAL.
- POST /api/projects encrypts both source_tenant.client_secret and
  destination_tenant.client_secret in the Mongo doc.
- GET /api/projects and /api/projects/{id} NEVER include client_secret;
  each tenant object exposes has_secret bool.
- Discover on a simulated (empty creds) project still returns mode=simulated
  and 64 items (exchange).
- test-connection on a simulated project returns simulated ok:true for both.
- Job creation + completion still works on a simulated project (no
  encryption crashes).
- Backward compat: a project with a legacy plaintext client_secret is
  still decryptable (passthrough) and discover/test-connection work.
"""
import os
import time
import uuid
import pytest
import requests
from bson import ObjectId
from pymongo import MongoClient

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip()
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@migratetool.com"
ADMIN_PASSWORD = "Admin@12345"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ENC_PREFIX = "enc:v1:"


# ----------------- fixtures -----------------
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
def mongo_db():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    client.close()


@pytest.fixture(scope="module")
def cleanup():
    conn_ids = []
    proj_ids = []
    yield {"connections": conn_ids, "projects": proj_ids}
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code == 200:
        s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
        for cid in conn_ids:
            try:
                s.delete(f"{API}/tenant-connections/{cid}")
            except Exception:
                pass
        for pid in proj_ids:
            try:
                s.delete(f"{API}/projects/{pid}")
            except Exception:
                pass


def _run_async(coro):
    """Deprecated helper — kept for API compat, no longer used."""
    raise NotImplementedError("use synchronous pymongo helpers below")


def _fetch_raw_connection(mongo_db, cid):
    return mongo_db.tenant_connections.find_one({"_id": ObjectId(cid)})


def _fetch_raw_project(mongo_db, pid):
    return mongo_db.projects.find_one({"_id": ObjectId(pid)})


def _insert_legacy_project(mongo_db, name, plain_secret):
    """Simulate a pre-iter5 record with plaintext client_secret."""
    doc = {
        "name": name,
        "description": "legacy pre-encryption record",
        "source_tenant": {
            "tenant_id": str(uuid.uuid4()),
            "domain": "legacy.onmicrosoft.com",
            "client_id": str(uuid.uuid4()),
            "client_secret": plain_secret,  # PLAINTEXT (legacy)
            "label": "legacy_src",
        },
        "destination_tenant": {
            "tenant_id": "",
            "domain": "legacy-dst.onmicrosoft.com",
            "client_id": "",
            "client_secret": "",
            "label": "legacy_dst",
        },
        "owner_id": "legacy_user",
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "active",
        "notification_settings": {},
    }
    r = mongo_db.projects.insert_one(doc)
    return str(r.inserted_id)


def _delete_project_raw(mongo_db, pid):
    mongo_db.projects.delete_one({"_id": ObjectId(pid)})


# ================== TENANT CONNECTION ENCRYPTION ==================
class TestTenantConnectionEncryption:

    def test_create_encrypts_in_mongo_and_masks_in_response(
        self, auth_client, mongo_db, cleanup
    ):
        plain = "plaintext-value-abc"
        payload = {
            "label": f"TEST_Iter5_enc_{uuid.uuid4().hex[:6]}",
            "domain": "contoso.onmicrosoft.com",
            "tenant_id": str(uuid.uuid4()),
            "client_id": str(uuid.uuid4()),
            "client_secret": plain,
            "notes": "iter5 encryption test",
        }
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        cid = data["id"]
        cleanup["connections"].append(cid)

        # Response is masked — no plaintext leak
        assert "client_secret" not in data
        assert "client_secret_masked" in data
        masked = data["client_secret_masked"]
        # mask is based on original plaintext ('pl' + bullets + 'abc'... but wait
        # last-4 kept when len>6. plaintext-value-abc = 19 chars → last 4 = '-abc').
        assert masked.startswith(plain[:2])
        assert masked.endswith(plain[-4:])
        assert "•" in masked

        # Raw Mongo doc has enc:v1: prefix
        raw = _fetch_raw_connection(mongo_db, cid)
        assert raw is not None
        stored = raw.get("client_secret", "")
        assert stored.startswith(ENC_PREFIX), (
            f"raw client_secret must start with '{ENC_PREFIX}', got: {stored[:40]!r}"
        )
        # And it must NOT be the plaintext
        assert plain not in stored, "raw stored secret must not contain plaintext"

        # Reveal returns original plaintext
        rr = auth_client.get(f"{API}/tenant-connections/{cid}?reveal=true")
        assert rr.status_code == 200
        assert rr.json()["client_secret"] == plain

    def test_put_empty_secret_keeps_encrypted_blob(
        self, auth_client, mongo_db, cleanup
    ):
        plain = f"orig-{uuid.uuid4().hex}"
        payload = {
            "label": f"TEST_Iter5_preserve_{uuid.uuid4().hex[:6]}",
            "domain": "d.com",
            "tenant_id": str(uuid.uuid4()),
            "client_id": str(uuid.uuid4()),
            "client_secret": plain,
        }
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        cid = r.json()["id"]
        cleanup["connections"].append(cid)

        raw_before = _fetch_raw_connection(mongo_db, cid)["client_secret"]
        assert raw_before.startswith(ENC_PREFIX)

        # PUT with empty client_secret
        upd = {**payload, "client_secret": "", "label": payload["label"] + "_u"}
        r = auth_client.put(f"{API}/tenant-connections/{cid}", json=upd)
        assert r.status_code == 200

        raw_after = _fetch_raw_connection(mongo_db, cid)["client_secret"]
        assert raw_after == raw_before, (
            "PUT with empty secret must not touch the encrypted blob"
        )
        # Reveal still returns original plaintext
        rr = auth_client.get(f"{API}/tenant-connections/{cid}?reveal=true")
        assert rr.json()["client_secret"] == plain

    def test_put_new_secret_reencrypts_with_different_token(
        self, auth_client, mongo_db, cleanup
    ):
        payload = {
            "label": f"TEST_Iter5_rot_{uuid.uuid4().hex[:6]}",
            "domain": "d.com",
            "tenant_id": str(uuid.uuid4()),
            "client_id": str(uuid.uuid4()),
            "client_secret": "orig-secret-value-123",
        }
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        cid = r.json()["id"]
        cleanup["connections"].append(cid)
        raw_before = _fetch_raw_connection(mongo_db, cid)["client_secret"]

        new_plain = f"rotated-{uuid.uuid4().hex}"
        upd = {**payload, "client_secret": new_plain}
        r = auth_client.put(f"{API}/tenant-connections/{cid}", json=upd)
        assert r.status_code == 200

        raw_after = _fetch_raw_connection(mongo_db, cid)["client_secret"]
        assert raw_after.startswith(ENC_PREFIX)
        assert raw_after != raw_before, "rotated secret must yield a new enc token"
        assert new_plain not in raw_after

        rr = auth_client.get(f"{API}/tenant-connections/{cid}?reveal=true")
        assert rr.json()["client_secret"] == new_plain

    def test_test_endpoint_uses_decrypted_secret_and_no_500(
        self, auth_client, cleanup
    ):
        """Fake but valid-looking creds → MSAL should attempt real Graph and
        surface an authority-config/token error (ok:false, mode:live).
        Crucially: no 500 (encryption path is invisible to MSAL)."""
        payload = {
            "label": f"TEST_Iter5_live_{uuid.uuid4().hex[:6]}",
            "domain": "contoso.onmicrosoft.com",
            "tenant_id": str(uuid.uuid4()),
            "client_id": str(uuid.uuid4()),
            "client_secret": "encrypted-in-mongo-value",
        }
        r = auth_client.post(f"{API}/tenant-connections", json=payload)
        cid = r.json()["id"]
        cleanup["connections"].append(cid)
        r = auth_client.post(f"{API}/tenant-connections/{cid}/test")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, f"fake creds should not auth: {data}"
        assert data.get("mode") == "live"
        msg = (data.get("message") or "").lower()
        assert any(
            k in msg for k in
            ["authority", "tenant", "unable", "config", "token", "aadsts", "acquisition"]
        ), f"unexpected error message: {data.get('message')!r}"


# ================== PROJECT ENCRYPTION ==================
class TestProjectSecretEncryption:

    def test_create_project_encrypts_both_tenant_secrets(
        self, auth_client, mongo_db, cleanup
    ):
        src_plain = "src-plain"
        dst_plain = "dst-plain"
        body = {
            "name": f"TEST_Iter5_ProjEnc_{uuid.uuid4().hex[:6]}",
            "description": "iter5 project encryption",
            "source_tenant": {
                "tenant_id": str(uuid.uuid4()),
                "domain": "src.onmicrosoft.com",
                "client_id": str(uuid.uuid4()),
                "client_secret": src_plain,
                "label": "src",
            },
            "destination_tenant": {
                "tenant_id": str(uuid.uuid4()),
                "domain": "dst.onmicrosoft.com",
                "client_id": str(uuid.uuid4()),
                "client_secret": dst_plain,
                "label": "dst",
            },
        }
        r = auth_client.post(f"{API}/projects", json=body)
        assert r.status_code == 200, r.text
        p = r.json()
        pid = p["id"]
        cleanup["projects"].append(pid)

        # Response must not contain client_secret; has_secret is true
        for k in ("source_tenant", "destination_tenant"):
            assert "client_secret" not in p[k], (
                f"{k} must not include client_secret in create response"
            )
            assert p[k].get("has_secret") is True

        # Raw Mongo doc: both stored secrets are enc:v1:
        raw = _fetch_raw_project(mongo_db, pid)
        src_stored = raw["source_tenant"]["client_secret"]
        dst_stored = raw["destination_tenant"]["client_secret"]
        assert src_stored.startswith(ENC_PREFIX), src_stored[:40]
        assert dst_stored.startswith(ENC_PREFIX), dst_stored[:40]
        assert src_plain not in src_stored
        assert dst_plain not in dst_stored

    def test_list_and_get_never_include_client_secret(
        self, auth_client, cleanup
    ):
        # reuse a project or create one
        body = {
            "name": f"TEST_Iter5_ListMask_{uuid.uuid4().hex[:6]}",
            "description": "",
            "source_tenant": {
                "domain": "s.com",
                "tenant_id": str(uuid.uuid4()),
                "client_id": str(uuid.uuid4()),
                "client_secret": "abcabcabcabc",
            },
            "destination_tenant": {
                "domain": "d.com",
            },
        }
        r = auth_client.post(f"{API}/projects", json=body)
        pid = r.json()["id"]
        cleanup["projects"].append(pid)

        # list
        r = auth_client.get(f"{API}/projects")
        assert r.status_code == 200
        for item in r.json():
            for k in ("source_tenant", "destination_tenant"):
                assert "client_secret" not in (item.get(k) or {}), (
                    f"list: {k} leaked client_secret in project {item.get('id')}"
                )
                # has_secret should be present
                assert "has_secret" in (item.get(k) or {})

        # get one
        r = auth_client.get(f"{API}/projects/{pid}")
        assert r.status_code == 200
        p = r.json()
        assert "client_secret" not in p["source_tenant"]
        assert p["source_tenant"]["has_secret"] is True
        assert "client_secret" not in p["destination_tenant"]
        assert p["destination_tenant"]["has_secret"] is False


# ================== SIMULATED-MODE PROJECT (empty creds) ==================
class TestSimulatedProjectFlow:

    @pytest.fixture(scope="class")
    def sim_project_id(self, auth_client, cleanup):
        body = {
            "name": f"TEST_Iter5_Sim_{uuid.uuid4().hex[:6]}",
            "description": "empty creds → simulated",
            "source_tenant": {"domain": "src.com"},
            "destination_tenant": {"domain": "dst.com"},
        }
        r = auth_client.post(f"{API}/projects", json=body)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        cleanup["projects"].append(pid)
        return pid

    def test_discover_returns_simulated_and_64_items(
        self, auth_client, sim_project_id
    ):
        r = auth_client.get(
            f"{API}/services/exchange/discover",
            params={"project_id": sim_project_id},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "simulated"
        assert data["total"] == 64, f"expected 64 items got {data['total']}"

    def test_test_connection_simulated_both_ok(
        self, auth_client, sim_project_id
    ):
        r = auth_client.post(f"{API}/projects/{sim_project_id}/test-connection")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source"]["mode"] == "simulated"
        assert d["source"]["ok"] is True
        assert d["destination"]["mode"] == "simulated"
        assert d["destination"]["ok"] is True
        assert "tested_at" in d

    def test_preflight_no_crash(self, auth_client, sim_project_id):
        r = auth_client.post(f"{API}/projects/{sim_project_id}/preflight")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["overall"] in ("pass", "fail")
        assert isinstance(d.get("checks"), list) and len(d["checks"]) >= 3

    def test_job_runs_to_completion(self, auth_client, sim_project_id):
        # discover first 3 items
        r = auth_client.get(
            f"{API}/services/exchange/discover",
            params={"project_id": sim_project_id},
        )
        items = r.json()["items"][:3]
        item_ids = [it["id"] for it in items]

        r = auth_client.post(
            f"{API}/jobs",
            json={
                "project_id": sim_project_id,
                "service_type": "exchange",
                "item_ids": item_ids,
                "mode": "full",
                "concurrency": 3,
            },
        )
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
        assert final["success_count"] > 0, f"no successes: {final}"


# ================== BACKWARD COMPAT: legacy plaintext record ==================
class TestLegacyPlaintextCompat:

    def test_crypto_decrypt_secret_passthrough(self):
        """Unit-level: decrypt_secret must return legacy plaintext unchanged
        (no enc:v1: prefix)."""
        import sys
        sys.path.insert(0, "/app/backend")
        # Load backend .env so CONN_ENCRYPTION_KEY is present for Fernet init
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        import crypto as crypto_mod
        # Force fernet reinit in case the module was imported earlier without key
        crypto_mod._fernet = None
        for legacy in ["", "plainABC123", "hunter2", "with-symbols!@#$%^&*()"]:
            assert crypto_mod.decrypt_secret(legacy) == legacy
        # And encrypt+decrypt round-trip yields original
        enc = crypto_mod.encrypt_secret("round-trip-value")
        assert enc.startswith("enc:v1:"), f"expected enc:v1: prefix, got {enc[:20]!r}"
        assert crypto_mod.decrypt_secret(enc) == "round-trip-value"

    def test_legacy_project_discover_and_test_connection(
        self, auth_client, mongo_db
    ):
        legacy_plain = "legacy-plaintext-secret-xyz"
        pid = _insert_legacy_project(
            mongo_db, f"TEST_Iter5_Legacy_{uuid.uuid4().hex[:6]}", legacy_plain
        )
        try:
            # Raw mongo doc has plaintext (no enc:v1: prefix)
            raw = _fetch_raw_project(mongo_db, pid)
            assert raw["source_tenant"]["client_secret"] == legacy_plain
            assert not raw["source_tenant"]["client_secret"].startswith(ENC_PREFIX)

            # GET must still respond and mask (never leak plaintext)
            r = auth_client.get(f"{API}/projects/{pid}")
            assert r.status_code == 200
            p = r.json()
            assert "client_secret" not in p["source_tenant"]
            assert p["source_tenant"]["has_secret"] is True

            # test-connection should not 500 — legacy plaintext is passed
            # through decrypt_secret unchanged, so MSAL is attempted with real
            # creds (fake here) → ok:false live.
            r = auth_client.post(f"{API}/projects/{pid}/test-connection")
            assert r.status_code == 200, r.text
            d = r.json()
            # source has creds (legacy) → live-mode attempt
            assert d["source"]["mode"] in ("live", "simulated")
            # destination has empty creds → simulated ok
            assert d["destination"]["mode"] == "simulated"
            assert d["destination"]["ok"] is True

            # discover on source: with legacy fake creds MSAL will fail
            # authority resolution. Iter6 wraps MSAL errors in a clean
            # HTTPException(400) "Graph discovery failed: ..." (previously
            # this leaked as 500). Accept 200 (adapter simulated), 400
            # (iter6 clean-error path), or 500 (legacy). What we verify:
            # the failure is NOT caused by decryption — if crypto were broken
            # we'd get a RuntimeError about CONN_ENCRYPTION_KEY.
            r = auth_client.get(
                f"{API}/services/exchange/discover",
                params={"project_id": pid},
            )
            assert r.status_code in (200, 400, 500), r.text
            if r.status_code in (400, 500):
                body_txt = r.text.lower()
                assert "decrypt" not in body_txt and "conn_encryption_key" not in body_txt, (
                    f"error must NOT be caused by decrypt failure: {r.text}"
                )
            else:
                data = r.json()
                assert "mode" in data and "items" in data
        finally:
            _delete_project_raw(mongo_db, pid)


# ================== REGRESSION SMOKE ==================
class TestRegressionSmoke:
    def test_dashboard_stats(self, auth_client):
        r = auth_client.get(f"{API}/dashboard/stats")
        assert r.status_code == 200
        for k in ("total_projects", "total_jobs", "running_jobs"):
            assert k in r.json()

    def test_schedules_list(self, auth_client):
        r = auth_client.get(f"{API}/schedules")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_tenant_connections_list(self, auth_client):
        r = auth_client.get(f"{API}/tenant-connections")
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list)
        for it in arr:
            assert "client_secret" not in it, "list must not leak plaintext"
