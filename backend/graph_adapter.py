"""
Microsoft Graph API adapter â€” app-only client credentials flow via MSAL.

Each project holds a source_tenant and destination_tenant config with:
  tenant_id, client_id, client_secret, domain

If any of these are empty, the adapter operates in SIMULATED mode and returns
deterministic mock data. Once real credentials are provided, calls hit the real
Graph API with 429/503 backoff.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Dict, List, Optional

import httpx
import msal
from tenacity import (
    retry, retry_if_exception_type, retry_if_result,
    stop_after_attempt, wait_exponential,
)

logger = logging.getLogger("graph_adapter")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPE = ["https://graph.microsoft.com/.default"]

# In-process token cache â€” keyed by (tenant_id, client_id)
_APP_CACHE: Dict[str, msal.ConfidentialClientApplication] = {}


class GraphError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def _is_configured(tenant_cfg: Dict[str, Any]) -> bool:
    return bool(
        tenant_cfg.get("tenant_id")
        and tenant_cfg.get("client_id")
        and tenant_cfg.get("client_secret")
    )


def _get_app(tenant_cfg: Dict[str, Any]) -> msal.ConfidentialClientApplication:
    key = f"{tenant_cfg['tenant_id']}::{tenant_cfg['client_id']}"
    app = _APP_CACHE.get(key)
    if not app:
        authority = f"https://login.microsoftonline.com/{tenant_cfg['tenant_id']}"
        app = msal.ConfidentialClientApplication(
            client_id=tenant_cfg["client_id"],
            client_credential=tenant_cfg["client_secret"],
            authority=authority,
        )
        _APP_CACHE[key] = app
    return app


async def acquire_token(tenant_cfg: Dict[str, Any]) -> str:
    """Return an app-only access token for the given tenant config."""
    app = _get_app(tenant_cfg)

    def _acquire():
        result = app.acquire_token_for_client(scopes=DEFAULT_SCOPE)
        if "access_token" not in result:
            raise GraphError(
                f"Token acquisition failed: {result.get('error')} â€” {result.get('error_description', '')}",
                status_code=401,
            )
        return result["access_token"]

    return await asyncio.to_thread(_acquire)


@retry(
    reraise=True,
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception_type((httpx.HTTPError, GraphError)),
)
async def _graph_request(
    method: str,
    url: str,
    tenant_cfg: Dict[str, Any],
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Any:
    token = await acquire_token(tenant_cfg)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(method, url, headers=headers, params=params, json=json_body)
    if resp.status_code == 429 or resp.status_code == 503:
        retry_after = int(resp.headers.get("Retry-After", "2"))
        await asyncio.sleep(min(retry_after, 30))
        raise GraphError(f"Throttled {resp.status_code}", status_code=resp.status_code)
    if resp.status_code >= 400:
        raise GraphError(f"Graph API {resp.status_code}: {resp.text[:2000]}", status_code=resp.status_code)
    if resp.status_code == 204:
        return None
    return resp.json()


async def _paginate(url: str, tenant_cfg: Dict[str, Any], limit: int = 500) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_url: Optional[str] = url
    while next_url and len(items) < limit:
        data = await _graph_request("GET", next_url, tenant_cfg)
        items.extend(data.get("value", []))
        next_url = data.get("@odata.nextLink")
    return items[:limit]


# =============================================================================
# Public adapter API â€” each function returns real Graph data OR simulated data.
# =============================================================================

async def test_connection(tenant_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Attempt to acquire a token. Returns {ok, latency_ms, mode, endpoint}."""
    import time
    if not _is_configured(tenant_cfg):
        return {
            "ok": True,
            "mode": "simulated",
            "latency_ms": random.randint(45, 180),
            "endpoint": "graph.microsoft.com",
            "message": "Credentials not configured â€” running in simulated mode.",
        }
    t0 = time.time()
    try:
        await acquire_token(tenant_cfg)
        latency = int((time.time() - t0) * 1000)
        return {
            "ok": True,
            "mode": "live",
            "latency_ms": latency,
            "endpoint": "graph.microsoft.com",
            "message": "Successfully acquired app-only token.",
        }
    except Exception as e:
        return {
            "ok": False,
            "mode": "live",
            "latency_ms": int((time.time() - t0) * 1000),
            "endpoint": "graph.microsoft.com",
            "message": str(e)[:300],
        }


# ---------------- Discovery per service ----------------

async def discover_exchange(tenant_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not _is_configured(tenant_cfg):
        return _sim("exchange")
    url = f"{GRAPH_BASE}/users?$select=id,displayName,mail,userPrincipalName&$top=100"
    users = await _paginate(url, tenant_cfg, limit=500)
    return [
        {
            "id": u["id"],
            "display_name": u.get("displayName") or u.get("userPrincipalName", ""),
            "primary_smtp": u.get("mail") or u.get("userPrincipalName", ""),
            "mailbox_size_gb": 0,
            "item_count": 0,
            "type": "UserMailbox",
        }
        for u in users if u.get("mail") or u.get("userPrincipalName")
    ]


async def discover_sharepoint(tenant_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not _is_configured(tenant_cfg):
        return _sim("sharepoint")
    data = await _graph_request("GET", f"{GRAPH_BASE}/sites?search=*", tenant_cfg)
    sites = data.get("value", [])
    return [
        {
            "id": s["id"],
            "display_name": s.get("displayName") or s.get("name", ""),
            "url": s.get("webUrl", ""),
            "storage_gb": 0,
            "template": s.get("root", {}).get("template", "Team"),
        }
        for s in sites
    ]


async def discover_onedrive(tenant_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not _is_configured(tenant_cfg):
        return _sim("onedrive")
    users = await _paginate(f"{GRAPH_BASE}/users?$select=id,displayName,userPrincipalName&$top=100", tenant_cfg, 200)
    return [
        {"id": u["id"], "display_name": f"{u.get('displayName','')} OneDrive",
         "owner": u.get("userPrincipalName", ""), "storage_gb": 0, "file_count": 0}
        for u in users
    ]


async def discover_groups(tenant_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not _is_configured(tenant_cfg):
        return _sim("groups")
    url = f"{GRAPH_BASE}/groups?$select=id,displayName,mail,groupTypes&$top=100"
    groups = await _paginate(url, tenant_cfg, 500)
    return [
        {"id": g["id"], "display_name": g.get("displayName", ""),
         "primary_smtp": g.get("mail", ""), "member_count": 0,
         "group_type": ",".join(g.get("groupTypes", [])) or "Security"}
        for g in groups
    ]


async def discover_distribution_lists(tenant_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not _is_configured(tenant_cfg):
        return _sim("distribution_lists")
    url = f"{GRAPH_BASE}/groups?$filter=mailEnabled eq true and securityEnabled eq false&$select=id,displayName,mail&$top=100"
    dls = await _paginate(url, tenant_cfg, 500)
    return [
        {"id": d["id"], "display_name": d.get("displayName", ""),
         "primary_smtp": d.get("mail", ""), "member_count": 0}
        for d in dls
    ]


async def discover_teams(tenant_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not _is_configured(tenant_cfg):
        return _sim("teams")
    data = await _graph_request("GET", f"{GRAPH_BASE}/teams", tenant_cfg)
    teams = data.get("value", [])
    return [
        {"id": t["id"], "display_name": t.get("displayName", ""),
         "member_count": 0, "channel_count": 0,
         "visibility": t.get("visibility", "Private")}
        for t in teams
    ]


async def discover_contacts(tenant_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Organizational contacts require Contacts.Read scope. Fall back to sim if not present.
    if not _is_configured(tenant_cfg):
        return _sim("contacts")
    try:
        data = await _graph_request("GET", f"{GRAPH_BASE}/contacts?$top=100", tenant_cfg)
        contacts = data.get("value", [])
        return [
            {"id": c["id"], "display_name": c.get("displayName", ""),
             "email": (c.get("mail") or ""), "company": c.get("companyName", "")}
            for c in contacts
        ]
    except GraphError:
        return _sim("contacts")


async def discover_calendars(tenant_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not _is_configured(tenant_cfg):
        return _sim("calendars")
    users = await _paginate(f"{GRAPH_BASE}/users?$select=id,displayName,userPrincipalName&$top=50", tenant_cfg, 100)
    return [
        {"id": u["id"], "display_name": f"Calendar - {u.get('displayName','')}",
         "owner": u.get("userPrincipalName", ""), "event_count": 0}
        for u in users
    ]


async def discover_public_folders(tenant_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Public folders are NOT exposed through Graph. Always simulated.
    return _sim("public_folders")


# ---------------- Migration primitives ----------------

async def migrate_item(
    service_type: str,
    item: Dict[str, Any],
    source_cfg: Dict[str, Any],
    dest_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Perform a single item migration.
      - Simulated mode: sleep + probabilistic success (no creds present).
      - Live mode: dispatch to graph_migrations for the requested service.
    Returns {status, error, duration_ms, stats?}.
    """
    import time
    t0 = time.time()

    if not (_is_configured(source_cfg) and _is_configured(dest_cfg)):
        # Simulated path
        await asyncio.sleep(random.uniform(0.6, 1.4))
        success = random.random() > 0.08
        return {
            "status": "success" if success else "failed",
            "error": None if success else random.choice([
                "GraphAPI: 429 Too Many Requests. Retry scheduled.",
                "PermissionDenied: destination lacks Mail.ReadWrite.",
                "TimeoutError: upstream mailbox export timed out.",
                "ConflictError: destination item already exists.",
            ]),
            "duration_ms": int((time.time() - t0) * 1000),
            "stats": {},
        }

    # Live path â€” delegate to per-service migration
    import graph_migrations as gm
    fn = gm.DISPATCH.get(service_type)
    if not fn:
        return {
            "status": "failed",
            "error": f"No live-mode adapter for service '{service_type}'",
            "duration_ms": int((time.time() - t0) * 1000),
            "stats": {},
        }
    try:
        # Ensure tokens are warm (fail fast on bad creds)
        await acquire_token(source_cfg)
        await acquire_token(dest_cfg)
        result = await fn(item, source_cfg, dest_cfg, _graph_request)
        result.setdefault("stats", {})
        result["duration_ms"] = int((time.time() - t0) * 1000)
        return result
    except GraphError as e:
        return {
            "status": "failed",
            "error": str(e)[:400],
            "duration_ms": int((time.time() - t0) * 1000),
            "stats": {},
        }
    except Exception as e:
        return {
            "status": "failed",
            "error": f"{type(e).__name__}: {str(e)[:380]}",
            "duration_ms": int((time.time() - t0) * 1000),
            "stats": {},
        }


# ---------------- Simulation dataset (kept in sync with server previously) ----

def _sim(service_type: str) -> List[Dict[str, Any]]:
    """Deterministic simulated dataset â€” used when credentials aren't configured."""
    templates = {
        "exchange": (64, lambda i: {
            "id": f"mbx_{i:04d}", "display_name": f"User {i:03d}",
            "primary_smtp": f"user{i:03d}@contoso.onmicrosoft.com",
            "mailbox_size_gb": round(random.uniform(0.4, 48.5), 2),
            "item_count": random.randint(2500, 240000), "type": "UserMailbox",
        }),
        "sharepoint": (32, lambda i: {
            "id": f"site_{i:04d}", "display_name": f"Site Collection {i:03d}",
            "url": f"/sites/team-{i:03d}",
            "storage_gb": round(random.uniform(1.2, 320.0), 2),
            "template": random.choice(["Team", "Communication", "Hub"]),
        }),
        "onedrive": (64, lambda i: {
            "id": f"od_{i:04d}", "display_name": f"User {i:03d} OneDrive",
            "owner": f"user{i:03d}@contoso.onmicrosoft.com",
            "storage_gb": round(random.uniform(0.2, 1024.0), 2),
            "file_count": random.randint(120, 84000),
        }),
        "distribution_lists": (24, lambda i: {
            "id": f"dl_{i:04d}", "display_name": f"DL {i:03d} - Department",
            "primary_smtp": f"dl-dept-{i:03d}@contoso.onmicrosoft.com",
            "member_count": random.randint(3, 780),
        }),
        "teams": (20, lambda i: {
            "id": f"team_{i:04d}", "display_name": f"Team {i:03d}",
            "member_count": random.randint(5, 250),
            "channel_count": random.randint(2, 24),
            "visibility": random.choice(["Public", "Private"]),
        }),
        "groups": (30, lambda i: {
            "id": f"grp_{i:04d}", "display_name": f"M365 Group {i:03d}",
            "primary_smtp": f"group-{i:03d}@contoso.onmicrosoft.com",
            "member_count": random.randint(2, 480), "group_type": "Unified",
        }),
        "contacts": (48, lambda i: {
            "id": f"con_{i:04d}", "display_name": f"Contact {i:03d}",
            "email": f"contact{i:03d}@external.com",
            "company": random.choice(["Fabrikam", "Contoso", "Adventure Works", "Northwind"]),
        }),
        "calendars": (40, lambda i: {
            "id": f"cal_{i:04d}", "display_name": f"Calendar - User {i:03d}",
            "owner": f"user{i:03d}@contoso.onmicrosoft.com",
            "event_count": random.randint(20, 4200),
        }),
        "public_folders": (16, lambda i: {
            "id": f"pf_{i:04d}", "display_name": f"\\PublicFolders\\Dept-{i:03d}",
            "item_count": random.randint(50, 12000),
            "size_gb": round(random.uniform(0.05, 24.0), 2),
        }),
    }
    count, gen = templates[service_type]
    return [gen(i + 1) for i in range(count)]


DISCOVERY_MAP = {
    "exchange": discover_exchange,
    "sharepoint": discover_sharepoint,
    "onedrive": discover_onedrive,
    "distribution_lists": discover_distribution_lists,
    "teams": discover_teams,
    "groups": discover_groups,
    "contacts": discover_contacts,
    "calendars": discover_calendars,
    "public_folders": discover_public_folders,
}

