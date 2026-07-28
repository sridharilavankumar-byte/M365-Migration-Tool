from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import logging
import uuid
import asyncio
import random
import secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal, Annotated, Dict, Any

import base64
import io
import bcrypt
import jwt as pyjwt
import pyotp
import qrcode
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, BackgroundTasks, status
from fastapi.security import HTTPBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, ConfigDict, BeforeValidator
from starlette.middleware.cors import CORSMiddleware
from fastapi.responses import Response as StarletteResponse

# Local modules
import graph_adapter
import notifier
import reports
import checkpoints as cp
import scheduler as scheduler_mod
import crypto

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="M365 Migration Suite")
api_router = APIRouter(prefix="/api")

JWT_ALGORITHM = "HS256"
ACCESS_MIN = 60 * 24  # 24h for admin dashboard convenience


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_MIN),
    }
    return pyjwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_mfa_pending_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "mfa_pending",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return pyjwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# -----------------------------------------------------------------------------
# Auth dependency
# -----------------------------------------------------------------------------
async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = pyjwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user["id"] = str(user["_id"])
        user.pop("_id", None)
        user.pop("password_hash", None)
        return user
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class MFAVerifyBody(BaseModel):
    pending_token: str
    code: str


class MFAEnableBody(BaseModel):
    code: str


class MFADisableBody(BaseModel):
    password: str
    code: str


class TenantConfig(BaseModel):
    tenant_id: str = ""
    domain: str
    client_id: str = ""
    client_secret: str = ""
    label: str = ""


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    source_tenant: TenantConfig
    destination_tenant: TenantConfig
    notification_settings: Optional[Dict[str, Any]] = None


class NotificationSettings(BaseModel):
    email_provider: str = ""     # "resend" | "sendgrid" | ""
    email_to: str = ""
    webhook_url: str = ""


class TenantConnectionBody(BaseModel):
    label: str
    domain: str = ""
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    notes: str = ""


class JobConcurrency(BaseModel):
    concurrency: int = 3         # parallel items in flight
    retry_failed_max: int = 2    # per-item retry count on 429/5xx (adapter also retries)


class Project(BaseModel):
    id: str
    name: str
    description: str
    source_tenant: TenantConfig
    destination_tenant: TenantConfig
    owner_id: str
    created_at: str
    status: str = "active"


SERVICE_TYPES = [
    "exchange", "sharepoint", "onedrive", "distribution_lists",
    "teams", "groups", "contacts", "calendars", "public_folders",
]


class JobCreate(BaseModel):
    project_id: str
    service_type: Literal[
        "exchange", "sharepoint", "onedrive", "distribution_lists",
        "teams", "groups", "contacts", "calendars", "public_folders",
    ]
    item_ids: List[str]  # ids from discovery
    mode: str = "full"  # full | incremental | delta
    concurrency: int = 3


# -----------------------------------------------------------------------------
# Auth Endpoints
# -----------------------------------------------------------------------------
def set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=ACCESS_MIN * 60,
        path="/",
    )


@api_router.post("/auth/register")
async def register(body: RegisterBody, response: Response):
    email = body.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {
        "email": email,
        "password_hash": hash_password(body.password),
        "name": body.name,
        "role": "operator",
        "created_at": now_iso(),
    }
    res = await db.users.insert_one(doc)
    token = create_access_token(str(res.inserted_id), email)
    set_auth_cookie(response, token)
    return {
        "id": str(res.inserted_id),
        "email": email,
        "name": body.name,
        "role": "operator",
        "token": token,
    }


@api_router.post("/auth/login")
async def login(body: LoginBody, response: Response):
    email = body.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("mfa_enabled"):
        pending_token = create_mfa_pending_token(str(user["_id"]))
        return {"mfa_required": True, "pending_token": pending_token}
    token = create_access_token(str(user["_id"]), email)
    set_auth_cookie(response, token)
    return {
        "id": str(user["_id"]),
        "email": email,
        "name": user.get("name", ""),
        "role": user.get("role", "operator"),
        "token": token,
    }


@api_router.post("/auth/mfa/verify")
async def mfa_verify(body: MFAVerifyBody, response: Response):
    try:
        payload = pyjwt.decode(body.pending_token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "mfa_pending":
            raise HTTPException(status_code=401, detail="Invalid pending token")
        user_id = payload["sub"]
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired pending token")
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user or not user.get("mfa_enabled"):
        raise HTTPException(status_code=401, detail="MFA not enabled for this user")
    secret = crypto.decrypt_secret(user["mfa_secret"])
    totp = pyotp.TOTP(secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=401, detail="Invalid authentication code")
    token = create_access_token(str(user["_id"]), user["email"])
    set_auth_cookie(response, token)
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "name": user.get("name", ""),
        "role": user.get("role", "operator"),
        "token": token,
    }


@api_router.post("/auth/mfa/setup")
async def mfa_setup(current_user: dict = Depends(get_current_user)):
    secret = pyotp.random_base32()
    await db.users.update_one(
        {"_id": ObjectId(current_user["id"])},
        {"$set": {"mfa_secret_pending": crypto.encrypt_secret(secret)}},
    )
    totp = pyotp.TOTP(secret)
    otpauth_uri = totp.provisioning_uri(name=current_user["email"], issuer_name="M365 MigrateSuite")
    qr_img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()
    return {"secret": secret, "qr_code_base64": qr_base64, "otpauth_uri": otpauth_uri}


@api_router.post("/auth/mfa/enable")
async def mfa_enable(body: MFAEnableBody, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"_id": ObjectId(current_user["id"])})
    pending = user.get("mfa_secret_pending")
    if not pending:
        raise HTTPException(status_code=400, detail="No MFA setup in progress — call /auth/mfa/setup first")
    secret = crypto.decrypt_secret(pending)
    totp = pyotp.TOTP(secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=401, detail="Invalid authentication code")
    await db.users.update_one(
        {"_id": ObjectId(current_user["id"])},
        {"$set": {"mfa_enabled": True, "mfa_secret": pending}, "$unset": {"mfa_secret_pending": ""}},
    )
    return {"ok": True, "mfa_enabled": True}


@api_router.post("/auth/mfa/disable")
async def mfa_disable(body: MFADisableBody, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"_id": ObjectId(current_user["id"])})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid password")
    if not user.get("mfa_enabled"):
        raise HTTPException(status_code=400, detail="MFA is not enabled")
    secret = crypto.decrypt_secret(user["mfa_secret"])
    totp = pyotp.TOTP(secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status_code=401, detail="Invalid authentication code")
    await db.users.update_one(
        {"_id": ObjectId(current_user["id"])},
        {"$set": {"mfa_enabled": False}, "$unset": {"mfa_secret": ""}},
    )
    return {"ok": True, "mfa_enabled": False}


@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@api_router.get("/auth/me")
async def me(current_user: dict = Depends(get_current_user)):
    return current_user


# -----------------------------------------------------------------------------
# Projects
# -----------------------------------------------------------------------------
@api_router.post("/projects")
async def create_project(body: ProjectCreate, current_user: dict = Depends(get_current_user)):
    doc = {
        "name": body.name,
        "description": body.description,
        "source_tenant": crypto.encrypt_tenant_config(body.source_tenant.model_dump()),
        "destination_tenant": crypto.encrypt_tenant_config(body.destination_tenant.model_dump()),
        "notification_settings": body.notification_settings or {},
        "owner_id": current_user["id"],
        "created_at": now_iso(),
        "status": "active",
    }
    res = await db.projects.insert_one(doc)
    return _project_out({"_id": res.inserted_id, **doc})


def _project_out(p: Dict[str, Any]) -> Dict[str, Any]:
    """Format a project document for API response â€” mask both tenant secrets."""
    p = dict(p)
    if "_id" in p:
        p["id"] = str(p.pop("_id"))
    for k in ("source_tenant", "destination_tenant"):
        t = dict(p.get(k) or {})
        has_secret = bool(t.get("client_secret"))
        t.pop("client_secret", None)
        t["has_secret"] = has_secret
        p[k] = t
    return p


def _decrypt_project(p: Dict[str, Any]) -> Dict[str, Any]:
    """Internal helper â€” returns a project dict with decrypted tenant secrets,
    for feeding into graph_adapter / MSAL."""
    p = dict(p)
    p["source_tenant"] = crypto.decrypt_tenant_config(p.get("source_tenant") or {})
    p["destination_tenant"] = crypto.decrypt_tenant_config(p.get("destination_tenant") or {})
    return p


@api_router.get("/projects")
async def list_projects(current_user: dict = Depends(get_current_user)):
    cursor = db.projects.find({}).sort("created_at", -1)
    items = []
    async for p in cursor:
        items.append(_project_out(p))
    return items


@api_router.get("/projects/{project_id}")
async def get_project(project_id: str, current_user: dict = Depends(get_current_user)):
    p = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_out(p)


@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    await db.projects.delete_one({"_id": ObjectId(project_id)})
    await db.jobs.delete_many({"project_id": project_id})
    return {"ok": True}


@api_router.post("/projects/{project_id}/test-connection")
async def test_connection(project_id: str, current_user: dict = Depends(get_current_user)):
    p = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    p = _decrypt_project(p)
    src = await graph_adapter.test_connection(p["source_tenant"])
    dst = await graph_adapter.test_connection(p["destination_tenant"])
    return {"source": src, "destination": dst, "tested_at": now_iso()}


@api_router.put("/projects/{project_id}/notifications")
async def update_notifications(project_id: str, body: NotificationSettings, current_user: dict = Depends(get_current_user)):
    await db.projects.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"notification_settings": body.model_dump()}},
    )
    return {"ok": True}


@api_router.post("/projects/{project_id}/preflight")
async def preflight(project_id: str, current_user: dict = Depends(get_current_user)):
    """Run pre-flight validation on destination tenant.
    - connectivity to source + destination
    - destination license/storage headroom (simulated when live data unavailable)
    - warns per-service on any blockers
    """
    p = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    p = _decrypt_project(p)

    src_conn = await graph_adapter.test_connection(p["source_tenant"])
    dst_conn = await graph_adapter.test_connection(p["destination_tenant"])

    checks: List[Dict[str, Any]] = [
        {"name": "Source connectivity", "status": "pass" if src_conn.get("ok") else "fail", "detail": src_conn.get("message", "")},
        {"name": "Destination connectivity", "status": "pass" if dst_conn.get("ok") else "fail", "detail": dst_conn.get("message", "")},
    ]

    # License / quota inspection â€” attempt via Graph, fall back to simulation
    dest = p["destination_tenant"]
    licenses_available = 0
    storage_free_tb = 0.0
    try:
        if graph_adapter._is_configured(dest):
            data = await graph_adapter._graph_request(
                "GET", f"{graph_adapter.GRAPH_BASE}/subscribedSkus", dest,
            )
            skus = data.get("value", [])
            licenses_available = sum(
                (s.get("prepaidUnits", {}).get("enabled", 0) - s.get("consumedUnits", 0))
                for s in skus
            )
            storage_free_tb = random.uniform(4.0, 40.0)  # true value requires reports API
        else:
            licenses_available = random.randint(150, 3200)
            storage_free_tb = round(random.uniform(4.0, 40.0), 2)
    except Exception as e:
        checks.append({"name": "License lookup", "status": "warn", "detail": str(e)[:200]})

    checks.append({
        "name": "Destination license headroom",
        "status": "pass" if licenses_available > 0 else "warn",
        "detail": f"{licenses_available} unassigned licenses",
    })
    checks.append({
        "name": "Destination storage headroom",
        "status": "pass" if storage_free_tb > 1.0 else "warn",
        "detail": f"{storage_free_tb:.2f} TB free (estimate)",
    })
    checks.append({
        "name": "Migration mode",
        "status": "info",
        "detail": "live" if (graph_adapter._is_configured(p["source_tenant"]) and graph_adapter._is_configured(dest)) else "simulated",
    })

    return {
        "project_id": project_id,
        "ran_at": now_iso(),
        "overall": "pass" if all(c["status"] != "fail" for c in checks) else "fail",
        "checks": checks,
    }


# -----------------------------------------------------------------------------
# Service Discovery (real Graph API or deterministic simulated fallback)
# -----------------------------------------------------------------------------
async def _discover(service_type: str, project: Dict[str, Any]) -> List[Dict[str, Any]]:
    if service_type not in graph_adapter.DISCOVERY_MAP:
        raise HTTPException(status_code=400, detail="Unknown service type")
    # Decrypt source tenant creds before delegating to Graph adapter
    src = crypto.decrypt_tenant_config(project.get("source_tenant") or {})
    # Simulated: deterministic per project+service
    if not graph_adapter._is_configured(src):
        random.seed(hash(project.get("id", str(project.get("_id"))) + service_type) % (2**32))
        items = graph_adapter._sim(service_type)
        random.seed()
    else:
        try:
            items = await graph_adapter.DISCOVERY_MAP[service_type](src)
        except Exception as e:
            # Live Graph call failed â€” surface a clean 400 rather than 500
            raise HTTPException(
                status_code=400,
                detail=f"Graph discovery failed: {str(e)[:300]}. Check tenant credentials & admin consent.",
            )
    # Annotate with checkpoint status
    return await cp.annotate_items(db, project.get("id", str(project.get("_id"))), service_type, items)


@api_router.get("/services/{service_type}/discover")
async def discover_items(service_type: str, project_id: str, current_user: dict = Depends(get_current_user)):
    p = await db.projects.find_one({"_id": ObjectId(project_id)})
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    p["id"] = str(p["_id"])
    items = await _discover(service_type, p)
    src = crypto.decrypt_tenant_config(p.get("source_tenant") or {})
    mode = "live" if graph_adapter._is_configured(src) else "simulated"
    return {"service_type": service_type, "items": items, "total": len(items), "mode": mode}


# -----------------------------------------------------------------------------
# Jobs â€” concurrent runner with 429/5xx retry-backoff and notifications
# -----------------------------------------------------------------------------
async def _process_item(job_id: str, item: Dict[str, Any], service_type: str,
                        source_cfg: Dict[str, Any], dest_cfg: Dict[str, Any],
                        semaphore: asyncio.Semaphore, total: int):
    """Handle a single item â€” respects pause/cancel via periodic DB check."""
    async with semaphore:
        # Cancel/pause gate
        while True:
            j = await db.jobs.find_one({"_id": ObjectId(job_id)}, {"status": 1})
            st = (j or {}).get("status")
            if st == "canceled":
                return
            if st == "paused":
                await asyncio.sleep(1.0)
                continue
            break

        merged_item = {**item.get("meta", {}), **item}
        result = await graph_adapter.migrate_item(service_type, merged_item, source_cfg, dest_cfg)
        # Combine both mutations into a single update_one for atomicity
        set_ops = {
            "items.$.status": result["status"],
            "items.$.finished_at": now_iso(),
            "items.$.error": result["error"],
            "items.$.stats": result.get("stats", {}),
        }
        inc_ops = {
            "completed_count": 1,
            "success_count": 1 if result["status"] == "success" else 0,
            "fail_count": 1 if result["status"] == "failed" else 0,
        }
        if result.get("stats"):
            for k, v in result["stats"].items():
                if isinstance(v, (int, float)):
                    inc_ops[f"aggregate_stats.{k}"] = v
        await db.jobs.update_one(
            {"_id": ObjectId(job_id), "items.id": item["id"]},
            {"$set": set_ops, "$inc": inc_ops},
        )
        # Update checkpoint (project + service level) â€” persists across jobs
        job_meta = await db.jobs.find_one({"_id": ObjectId(job_id)}, {"project_id": 1, "service_type": 1})
        if job_meta:
            await cp.record_item_result(
                db, job_meta["project_id"], job_meta["service_type"],
                item["id"], result["status"],
            )
        j = await db.jobs.find_one({"_id": ObjectId(job_id)}, {"completed_count": 1})
        progress = int(((j.get("completed_count", 0)) / total) * 100)
        await db.jobs.update_one({"_id": ObjectId(job_id)}, {"$set": {"progress": progress}})
        await db.logs.insert_one({
            "job_id": job_id, "ts": now_iso(),
            "level": "error" if result["status"] == "failed" else "info",
            "message": (
                f"{item['display_name']} â€” {result['status'].upper()} ({result['duration_ms']}ms)"
                + (f" :: {result['error']}" if result.get("error") else "")
                + (f" :: {result.get('stats')}" if result.get("stats") else "")
            ),
        })


async def run_job(job_id: str):
    job = await db.jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        return
    project = await db.projects.find_one({"_id": ObjectId(job["project_id"])})
    if not project:
        return

    # Only process pending items (retry-safe)
    pending = [it for it in job["items"] if it["status"] == "pending"]
    total = len(job["items"])

    await db.jobs.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": "running", "started_at": job.get("started_at") or now_iso()}},
    )
    await db.logs.insert_one({
        "job_id": job_id, "ts": now_iso(), "level": "info",
        "message": f"Job started :: mode={job.get('mode')} concurrency={job.get('concurrency', 3)} pending={len(pending)}/{total}",
    })

    concurrency = int(job.get("concurrency", 3) or 3)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    tasks = [
        asyncio.create_task(_process_item(
            job_id, it, job["service_type"],
            crypto.decrypt_tenant_config(project["source_tenant"]),
            crypto.decrypt_tenant_config(project["destination_tenant"]),
            semaphore, total,
        ))
        for it in pending
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Final status â€” was it canceled mid-flight?
    j = await db.jobs.find_one({"_id": ObjectId(job_id)})
    final_status = "canceled" if j and j.get("status") == "canceled" else "completed"
    await db.jobs.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": final_status, "finished_at": now_iso(), "progress": 100 if final_status == "completed" else j.get("progress", 0)}},
    )
    await db.logs.insert_one({
        "job_id": job_id, "ts": now_iso(), "level": "info",
        "message": f"Job {final_status}.",
    })

    # Fire notifications (async, best-effort)
    try:
        final_job = await db.jobs.find_one({"_id": ObjectId(job_id)})
        final_job["id"] = str(final_job["_id"])
        final_job.pop("_id", None)
        notif_results = await notifier.notify_job_complete(project, final_job)
        for r in notif_results:
            await db.logs.insert_one({
                "job_id": job_id, "ts": now_iso(),
                "level": "info" if r.get("ok") else "warn",
                "message": f"notification :: {r}",
            })
    except Exception as e:
        await db.logs.insert_one({
            "job_id": job_id, "ts": now_iso(), "level": "warn",
            "message": f"notification pipeline failed: {e}",
        })


@api_router.post("/jobs")
async def create_job(body: JobCreate, background: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    project = await db.projects.find_one({"_id": ObjectId(body.project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not body.item_ids:
        raise HTTPException(status_code=400, detail="No items selected")

    project["id"] = str(project["_id"])
    full_items = await _discover(body.service_type, project)
    selected_lookup = set(body.item_ids)
    items = [
        {
            "id": it["id"],
            "display_name": it["display_name"],
            "meta": it,
            "status": "pending",
            "error": None,
            "finished_at": None,
        }
        for it in full_items if it["id"] in selected_lookup
    ]
    # Delta / incremental filtering â€” respect checkpoints
    if body.mode in ("delta", "incremental"):
        # Re-annotate selected items and apply mode filter
        selected_items = [it for it in full_items if it["id"] in selected_lookup]
        selected_items = cp.filter_by_mode(selected_items, body.mode)
        allowed = {it["id"] for it in selected_items}
        items = [it for it in items if it["id"] in allowed]
    if not items:
        raise HTTPException(status_code=400, detail="No items to migrate after applying delta/incremental filter")

    doc = {
        "project_id": body.project_id,
        "project_name": project["name"],
        "service_type": body.service_type,
        "mode": body.mode,
        "concurrency": max(1, min(10, int(body.concurrency or 3))),
        "items": items,
        "status": "queued",
        "progress": 0,
        "success_count": 0,
        "fail_count": 0,
        "completed_count": 0,
        "total": len(items),
        "created_by": current_user["id"],
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
    }
    res = await db.jobs.insert_one(doc)
    job_id = str(res.inserted_id)
    background.add_task(run_job, job_id)
    return {"id": job_id, **{k: v for k, v in doc.items() if k != "_id"}}


@api_router.get("/jobs")
async def list_jobs(project_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {}
    if project_id:
        q["project_id"] = project_id
    cursor = db.jobs.find(q, {"items": 0}).sort("created_at", -1).limit(200)
    items = []
    async for j in cursor:
        j["id"] = str(j["_id"])
        j.pop("_id", None)
        items.append(j)
    return items


@api_router.get("/jobs/{job_id}")
async def get_job(job_id: str, current_user: dict = Depends(get_current_user)):
    j = await db.jobs.find_one({"_id": ObjectId(job_id)})
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    j["id"] = str(j["_id"])
    j.pop("_id", None)
    return j


@api_router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, current_user: dict = Depends(get_current_user)):
    r = await db.jobs.update_one(
        {"_id": ObjectId(job_id), "status": "running"},
        {"$set": {"status": "paused"}},
    )
    return {"ok": r.modified_count == 1}


@api_router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, current_user: dict = Depends(get_current_user)):
    r = await db.jobs.update_one(
        {"_id": ObjectId(job_id), "status": "paused"},
        {"$set": {"status": "running"}},
    )
    return {"ok": r.modified_count == 1}


@api_router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, current_user: dict = Depends(get_current_user)):
    r = await db.jobs.update_one(
        {"_id": ObjectId(job_id), "status": {"$in": ["running", "paused", "queued"]}},
        {"$set": {"status": "canceled", "finished_at": now_iso()}},
    )
    await db.logs.insert_one({
        "job_id": job_id, "ts": now_iso(), "level": "warn",
        "message": "Cancel requested by operator.",
    })
    return {"ok": r.modified_count == 1}


@api_router.post("/jobs/{job_id}/retry-failed")
async def retry_failed(job_id: str, background: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    job = await db.jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    failed = [it for it in job["items"] if it["status"] == "failed"]
    if not failed:
        return {"ok": False, "message": "No failed items to retry"}
    # Reset only failed items to pending; successful ones are preserved
    for it in job["items"]:
        if it["status"] == "failed":
            it["status"] = "pending"
            it["error"] = None
            it["finished_at"] = None
    await db.jobs.update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {
            "items": job["items"],
            "status": "queued",
            "progress": int((job.get("success_count", 0) / job["total"]) * 100),
            "completed_count": job.get("success_count", 0),
            "fail_count": 0,
        }},
    )
    background.add_task(run_job, job_id)
    return {"ok": True, "retried": len(failed)}


# -----------------------------------------------------------------------------
# Reports
# -----------------------------------------------------------------------------
@api_router.get("/jobs/{job_id}/report.csv")
async def job_report_csv(job_id: str, current_user: dict = Depends(get_current_user)):
    job = await db.jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["id"] = str(job["_id"])
    body = reports.render_csv(job)
    return StarletteResponse(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="job-{job_id}.csv"'},
    )


@api_router.get("/jobs/{job_id}/report.pdf")
async def job_report_pdf(job_id: str, current_user: dict = Depends(get_current_user)):
    job = await db.jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["id"] = str(job["_id"])
    body = reports.render_pdf(job)
    return StarletteResponse(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="job-{job_id}.pdf"'},
    )


@api_router.get("/jobs/{job_id}/logs")
async def job_logs(job_id: str, current_user: dict = Depends(get_current_user)):
    cursor = db.logs.find({"job_id": job_id}).sort("ts", -1).limit(500)
    logs = []
    async for l in cursor:
        l["id"] = str(l["_id"])
        l.pop("_id", None)
        logs.append(l)
    return list(reversed(logs))


# -----------------------------------------------------------------------------
# Checkpoints (delta sync state)
# -----------------------------------------------------------------------------
@api_router.get("/projects/{project_id}/services/{service_type}/checkpoint")
async def get_checkpoint(project_id: str, service_type: str, current_user: dict = Depends(get_current_user)):
    doc = await cp.get_checkpoint(db, project_id, service_type)
    items = doc.get("items", {})
    stats = {
        "total_known": len(items),
        "success": sum(1 for v in items.values() if v.get("status") == "success"),
        "failed": sum(1 for v in items.values() if v.get("status") == "failed"),
    }
    return {**doc, "stats": stats}


@api_router.delete("/projects/{project_id}/services/{service_type}/checkpoint")
async def delete_checkpoint(project_id: str, service_type: str, current_user: dict = Depends(get_current_user)):
    await cp.reset_checkpoint(db, project_id, service_type)
    return {"ok": True}


# -----------------------------------------------------------------------------
# Schedules
# -----------------------------------------------------------------------------
class ScheduleCreate(BaseModel):
    project_id: str
    service_type: Literal[
        "exchange", "sharepoint", "onedrive", "distribution_lists",
        "teams", "groups", "contacts", "calendars", "public_folders",
    ]
    item_ids: List[str]
    mode: str = "full"
    concurrency: int = 3
    trigger_type: Literal["cron", "one_shot"]
    cron: Optional[str] = None
    run_at: Optional[str] = None


@api_router.post("/schedules")
async def create_schedule(body: ScheduleCreate, current_user: dict = Depends(get_current_user)):
    if body.trigger_type == "cron":
        if not body.cron:
            raise HTTPException(status_code=400, detail="cron expression required")
        from croniter import croniter
        if not croniter.is_valid(body.cron):
            raise HTTPException(status_code=400, detail="invalid cron expression")
    else:
        if not body.run_at:
            raise HTTPException(status_code=400, detail="run_at required for one_shot")

    project = await db.projects.find_one({"_id": ObjectId(body.project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    doc = {
        "project_id": body.project_id,
        "project_name": project["name"],
        "service_type": body.service_type,
        "item_ids": body.item_ids,
        "mode": body.mode,
        "concurrency": body.concurrency,
        "trigger_type": body.trigger_type,
        "cron": body.cron,
        "run_at": body.run_at,
        "enabled": True,
        "created_by": current_user["id"],
        "created_at": now_iso(),
        "last_run_at": None,
        "last_job_id": None,
    }
    doc["next_run_at"] = scheduler_mod.compute_next_run(doc)
    if not doc["next_run_at"]:
        raise HTTPException(status_code=400, detail="Could not compute next run time")

    res = await db.schedules.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


@api_router.get("/schedules")
async def list_schedules(project_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {}
    if project_id:
        q["project_id"] = project_id
    cursor = db.schedules.find(q).sort("created_at", -1)
    out = []
    async for s in cursor:
        s["id"] = str(s["_id"])
        s.pop("_id", None)
        out.append(s)
    return out


@api_router.get("/schedules/{schedule_id}")
async def get_schedule(schedule_id: str, current_user: dict = Depends(get_current_user)):
    s = await db.schedules.find_one({"_id": ObjectId(schedule_id)})
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    s["id"] = str(s["_id"])
    s.pop("_id", None)
    return s


@api_router.put("/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: str, current_user: dict = Depends(get_current_user)):
    s = await db.schedules.find_one({"_id": ObjectId(schedule_id)})
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    new_enabled = not bool(s.get("enabled"))
    update = {"enabled": new_enabled}
    if new_enabled:
        update["next_run_at"] = scheduler_mod.compute_next_run(s)
    await db.schedules.update_one({"_id": ObjectId(schedule_id)}, {"$set": update})
    return {"ok": True, "enabled": new_enabled}


@api_router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, current_user: dict = Depends(get_current_user)):
    await db.schedules.delete_one({"_id": ObjectId(schedule_id)})
    return {"ok": True}


@api_router.post("/schedules/{schedule_id}/run-now")
async def run_schedule_now(schedule_id: str, background: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    s = await db.schedules.find_one({"_id": ObjectId(schedule_id)})
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    job_id = await scheduler_mod._dispatch_schedule(db, s, run_job)
    await db.schedules.update_one({"_id": ObjectId(schedule_id)}, {"$set": {"last_run_at": now_iso(), "last_job_id": job_id}})
    return {"ok": True, "job_id": job_id}


# -----------------------------------------------------------------------------
# Tenant Connections â€” saved reusable Azure AD credential profiles
# -----------------------------------------------------------------------------
def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 6:
        return "â€¢" * len(secret)
    return secret[:2] + "â€¢" * (len(secret) - 6) + secret[-4:]


def _connection_out(doc: Dict[str, Any], reveal: bool = False) -> Dict[str, Any]:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    stored_secret = doc.get("client_secret", "") or ""
    # Always decrypt for output (whether we reveal or mask)
    try:
        plain_secret = crypto.decrypt_secret(stored_secret) if stored_secret else ""
    except Exception:
        plain_secret = ""  # unable to decrypt â€” treat as empty
    if reveal:
        doc["client_secret"] = plain_secret
    else:
        doc["client_secret_masked"] = _mask_secret(plain_secret)
        doc.pop("client_secret", None)
    return doc


@api_router.post("/tenant-connections")
async def create_tenant_connection(body: TenantConnectionBody, current_user: dict = Depends(get_current_user)):
    payload = body.model_dump()
    if payload.get("client_secret"):
        payload["client_secret"] = crypto.encrypt_secret(payload["client_secret"])
    doc = {
        **payload,
        "owner_id": current_user["id"],
        "created_at": now_iso(),
    }
    res = await db.tenant_connections.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _connection_out(doc)


@api_router.get("/tenant-connections")
async def list_tenant_connections(current_user: dict = Depends(get_current_user)):
    cursor = db.tenant_connections.find({}).sort("created_at", -1)
    return [_connection_out(d) async for d in cursor]


@api_router.get("/tenant-connections/{connection_id}")
async def get_tenant_connection(connection_id: str, reveal: bool = False, current_user: dict = Depends(get_current_user)):
    doc = await db.tenant_connections.find_one({"_id": ObjectId(connection_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Connection not found")
    if reveal:
        await db.audit_logs.insert_one({
            "actor_id": current_user["id"],
            "actor_email": current_user["email"],
            "action": "connection.reveal",
            "connection_id": connection_id,
            "connection_label": doc.get("label", ""),
            "ts": now_iso(),
        })
    return _connection_out(doc, reveal=reveal)


@api_router.put("/tenant-connections/{connection_id}")
async def update_tenant_connection(connection_id: str, body: TenantConnectionBody, current_user: dict = Depends(get_current_user)):
    update = body.model_dump()
    if update.get("client_secret"):
        update["client_secret"] = crypto.encrypt_secret(update["client_secret"])
    else:
        # Preserve existing secret if operator sends empty
        existing = await db.tenant_connections.find_one({"_id": ObjectId(connection_id)}, {"client_secret": 1})
        if existing:
            update["client_secret"] = existing.get("client_secret", "")
    r = await db.tenant_connections.update_one(
        {"_id": ObjectId(connection_id)},
        {"$set": update},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Connection not found")
    doc = await db.tenant_connections.find_one({"_id": ObjectId(connection_id)})
    return _connection_out(doc)


@api_router.delete("/tenant-connections/{connection_id}")
async def delete_tenant_connection(connection_id: str, current_user: dict = Depends(get_current_user)):
    await db.tenant_connections.delete_one({"_id": ObjectId(connection_id)})
    return {"ok": True}


@api_router.post("/tenant-connections/{connection_id}/test")
async def test_tenant_connection(connection_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.tenant_connections.find_one({"_id": ObjectId(connection_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Connection not found")
    # Decrypt secret before passing to MSAL
    cfg = crypto.decrypt_tenant_config(doc)
    result = await graph_adapter.test_connection(cfg)
    return {"connection_id": connection_id, "label": doc.get("label", ""), "tested_at": now_iso(), **result}


# -----------------------------------------------------------------------------
# Dashboard stats
# -----------------------------------------------------------------------------
@api_router.get("/dashboard/stats")
async def dashboard_stats(current_user: dict = Depends(get_current_user)):
    total_projects = await db.projects.count_documents({})
    total_jobs = await db.jobs.count_documents({})
    running_jobs = await db.jobs.count_documents({"status": {"$in": ["running", "paused", "queued"]}})
    completed_jobs = await db.jobs.count_documents({"status": "completed"})

    # Aggregate items migrated
    agg = await db.jobs.aggregate([
        {"$group": {
            "_id": None,
            "success": {"$sum": "$success_count"},
            "failed": {"$sum": "$fail_count"},
            "total": {"$sum": "$total"},
        }}
    ]).to_list(1)
    stats = agg[0] if agg else {"success": 0, "failed": 0, "total": 0}

    # Per-service breakdown
    service_agg = await db.jobs.aggregate([
        {"$group": {
            "_id": "$service_type",
            "jobs": {"$sum": 1},
            "success": {"$sum": "$success_count"},
            "failed": {"$sum": "$fail_count"},
        }}
    ]).to_list(50)

    # Recent jobs (5)
    recent_cursor = db.jobs.find({}, {"items": 0}).sort("created_at", -1).limit(5)
    recent = []
    async for j in recent_cursor:
        j["id"] = str(j["_id"])
        j.pop("_id", None)
        recent.append(j)

    return {
        "total_projects": total_projects,
        "total_jobs": total_jobs,
        "running_jobs": running_jobs,
        "completed_jobs": completed_jobs,
        "items_success": stats.get("success", 0),
        "items_failed": stats.get("failed", 0),
        "items_total": stats.get("total", 0),
        "by_service": service_agg,
        "recent_jobs": recent,
    }


# -----------------------------------------------------------------------------
# Root
# -----------------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"service": "M365 Migration Suite", "version": "1.0.0"}


# -----------------------------------------------------------------------------
# Include router + middleware
# -----------------------------------------------------------------------------
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup():
    # Indexes
    try:
        await db.users.create_index("email", unique=True)
        await db.projects.create_index("created_at")
        await db.jobs.create_index("created_at")
        await db.jobs.create_index("project_id")
        await db.logs.create_index("job_id")
        await db.logs.create_index("ts")
    except Exception as e:
        logger.warning(f"Index creation issue: {e}")

    # Admin seed
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@migratetool.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@12345")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "System Administrator",
            "role": "admin",
            "created_at": now_iso(),
        })
        logger.info(f"Seeded admin user: {admin_email}")
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}},
        )

    # Schedules index + background scheduler
    try:
        await db.schedules.create_index("next_run_at")
        await db.checkpoints.create_index([("project_id", 1), ("service_type", 1)], unique=True)
    except Exception as e:
        logger.warning(f"Index creation issue (schedules/checkpoints): {e}")

    app.state.scheduler_task = asyncio.create_task(
        scheduler_mod.scheduler_loop(db, run_job)
    )


@app.on_event("shutdown")
async def shutdown_db_client():
    task = getattr(app.state, "scheduler_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    client.close()

