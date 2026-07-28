"""
Per-service migration primitives using Microsoft Graph API.

Each function is called by graph_adapter.migrate_item once BOTH source and
destination tenants have valid app-only credentials. Returns a dict:

    {
        "status": "success" | "failed" | "partial",
        "error": Optional[str],
        "stats": Dict[str, int]     # e.g. {"messages_copied": 240, "bytes": 1234567}
    }

Design notes:
- Cross-tenant migration via Graph works by (1) reading source with app-only
  token that has *_all permissions in the source tenant, (2) writing to the
  destination with app-only token that has *_all permissions in the
  destination tenant.
- 429/503 retry is handled by graph_adapter._graph_request (tenacity).
- Attachments, chunked uploads, and pagination are handled explicitly.
- Public Folders are NOT exposed via Graph ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â that function returns a
  structured "unsupported" error.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("graph_migrations")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
CHUNK = 5 * 1024 * 1024  # 5 MB upload chunks
PAGE_TOP = 50


# =============================================================================
# Lookup helpers
# =============================================================================

async def _get(_graph_request, url: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    return await _graph_request("GET", url, cfg)


async def _post(_graph_request, url: str, cfg: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    return await _graph_request("POST", url, cfg, json_body=body)


async def _paginate(_graph_request, url: str, cfg: Dict[str, Any], limit: int = 5000) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    next_url: Optional[str] = url
    while next_url and len(items) < limit:
        data = await _graph_request("GET", next_url, cfg)
        items.extend(data.get("value", []))
        next_url = data.get("@odata.nextLink")
    return items[:limit]


async def _find_or_provision_dest_user(
    _graph_request, src_upn: str, source_user: Dict[str, Any], dst_cfg: Dict[str, Any],
) -> Tuple[str, bool]:
    """Return (destination_user_id, provisioned_now). Looks up by UPN; if
    missing, provisions a new user in the destination with a temporary
    password (real deployments should use a proper user provisioning stage)."""
    # Compute the destination-mapped UPN up front so lookups match provisioning
    dest_domain_lookup = (dst_cfg.get("domain") or "").strip()
    mapped_upn = f"{src_upn.split(chr(64))[0]}@{dest_domain_lookup}" if dest_domain_lookup else src_upn
    # 1. Try direct lookup by mapped UPN, then fall back to source UPN
    for candidate in {mapped_upn, src_upn}:
        try:
            u = await _get(_graph_request, f"{GRAPH_BASE}/users/{candidate}", dst_cfg)
            return u["id"], False
        except Exception:
            continue
    # 2. Try filter by mail (either candidate)
    for candidate in {mapped_upn, src_upn}:
        try:
            data = await _get(_graph_request, f"{GRAPH_BASE}/users?$filter=mail eq '{candidate}'&$top=1", dst_cfg)
            arr = data.get("value", [])
            if arr:
                return arr[0]["id"], False
        except Exception:
            continue
    # 3. Provision - build the new UPN on the destination tenant own
    # verified domain, not the source domain (which the dest tenant cannot own).
    local_part = src_upn.split("@")[0]
    dest_domain = (dst_cfg.get("domain") or "").strip()
    new_upn = f"{local_part}@{dest_domain}" if dest_domain else src_upn
    display_name = source_user.get("displayName") or local_part
    body = {
        "accountEnabled": True,
        "displayName": display_name,
        "mailNickname": local_part,
        "userPrincipalName": new_upn,
        "passwordProfile": {
            "forceChangePasswordNextSignIn": True,
            "password": "M!" + base64.urlsafe_b64encode(new_upn.encode()).decode()[:12] + "9x",
        },
    }
    created = await _post(_graph_request, f"{GRAPH_BASE}/users", dst_cfg, body)
    return created["id"], True


# =============================================================================
# Exchange ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â mailbox content (messages)
# =============================================================================

async def migrate_exchange(item, src, dst, _graph_request) -> Dict[str, Any]:
    """
    Copy mail folders + messages + attachments from source user's mailbox to
    the destination user's mailbox.

    Requires app-only permissions in BOTH tenants:
      source:      Mail.ReadWrite / Mail.Read (application)
      destination: Mail.ReadWrite (application), User.ReadWrite.All
    """
    src_uid = item["id"]
    upn = item.get("primary_smtp") or item.get("userPrincipalName") or ""
    if not upn:
        return {"status": "failed", "error": "no source UPN/SMTP available", "stats": {}}

    src_user = await _get(_graph_request, f"{GRAPH_BASE}/users/{src_uid}", src)
    dst_uid, provisioned = await _find_or_provision_dest_user(_graph_request, upn, src_user, dst)

    stats = {"messages_copied": 0, "folders_copied": 0, "attachments_copied": 0, "bytes": 0, "provisioned_user": int(provisioned)}

    # Enumerate top-level mail folders
    folders = await _paginate(_graph_request, f"{GRAPH_BASE}/users/{src_uid}/mailFolders?$top={PAGE_TOP}", src)

    # Cache: source folder id -> destination folder id
    dst_folder_map: Dict[str, str] = {}

    for folder in folders:
        # Create/find matching folder in destination
        try:
            new_folder = await _post(
                _graph_request, f"{GRAPH_BASE}/users/{dst_uid}/mailFolders", dst,
                {"displayName": folder["displayName"]},
            )
            dst_folder_map[folder["id"]] = new_folder["id"]
            stats["folders_copied"] += 1
        except Exception:
            # Folder may already exist ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â try to look it up
            try:
                data = await _get(
                    _graph_request,
                    f"{GRAPH_BASE}/users/{dst_uid}/mailFolders?$filter=displayName eq '{folder['displayName']}'&$top=1",
                    dst,
                )
                arr = data.get("value", [])
                if arr:
                    dst_folder_map[folder["id"]] = arr[0]["id"]
            except Exception:
                continue

        # Copy messages in this folder
        try:
            messages = await _paginate(
                _graph_request,
                f"{GRAPH_BASE}/users/{src_uid}/mailFolders/{folder['id']}/messages?$top={PAGE_TOP}",
                src,
                limit=10000,
            )
        except Exception as e:
            logger.warning(f"failed to list messages in {folder['displayName']}: {e}")
            continue

        dst_folder_id = dst_folder_map.get(folder["id"])
        if not dst_folder_id:
            continue

        for msg in messages:
            try:
                # Build message payload
                payload = {
                    "subject": msg.get("subject", ""),
                    "body": msg.get("body", {}),
                    "toRecipients": msg.get("toRecipients", []),
                    "ccRecipients": msg.get("ccRecipients", []),
                    "bccRecipients": msg.get("bccRecipients", []),
                    "from": msg.get("from"),
                    "sender": msg.get("sender"),
                    "importance": msg.get("importance", "normal"),
                    "isRead": msg.get("isRead", True),
                }
                # Extended MAPI properties: clear the unsent/draft flag
                # (PR_MESSAGE_FLAGS, 0x0E07) so Exchange treats this as a
                # normal received message, and preserve the original
                # received timestamp (PR_MESSAGE_DELIVERY_TIME, 0x0E06).
                ext_props = [{"id": "Integer 0x0E07", "value": "1"}]
                if msg.get("receivedDateTime"):
                    ext_props.append({
                        "id": "SystemTime 0x0E06",
                        "value": msg["receivedDateTime"],
                    })
                payload["singleValueExtendedProperties"] = ext_props
                created = await _post(
                    _graph_request,
                    f"{GRAPH_BASE}/users/{dst_uid}/mailFolders/{dst_folder_id}/messages",
                    dst, payload,
                )
                stats["messages_copied"] += 1

                # Copy attachments if any
                if msg.get("hasAttachments"):
                    try:
                        atts = await _paginate(
                            _graph_request,
                            f"{GRAPH_BASE}/users/{src_uid}/messages/{msg['id']}/attachments",
                            src, limit=200,
                        )
                        for att in atts:
                            att_payload = {
                                "@odata.type": att.get("@odata.type", "#microsoft.graph.fileAttachment"),
                                "name": att.get("name", "attachment"),
                                "contentBytes": att.get("contentBytes", ""),
                                "contentType": att.get("contentType", "application/octet-stream"),
                                "isInline": att.get("isInline", False),
                            }
                            if att.get("contentId"):
                                att_payload["contentId"] = att["contentId"]
                            await _post(
                                _graph_request,
                                f"{GRAPH_BASE}/users/{dst_uid}/messages/{created['id']}/attachments",
                                dst, att_payload,
                            )
                            stats["attachments_copied"] += 1
                            stats["bytes"] += att.get("size", 0) or 0
                    except Exception as ae:
                        logger.warning(f"attachment copy failed for msg {msg.get('id')}: {ae}")
            except Exception as e:
                logger.warning(f"message copy failed: {e}")
                continue

    return {"status": "success", "error": None, "stats": stats}


# =============================================================================
# Calendars
# =============================================================================

async def migrate_calendar(item, src, dst, _graph_request) -> Dict[str, Any]:
    upn = item.get("owner") or item.get("primary_smtp") or ""
    if not upn:
        return {"status": "failed", "error": "no source UPN/owner", "stats": {}}
    src_uid = item["id"]
    src_user = await _get(_graph_request, f"{GRAPH_BASE}/users/{src_uid}", src)
    dst_uid, prov = await _find_or_provision_dest_user(_graph_request, upn, src_user, dst)

    stats = {"events_copied": 0, "provisioned_user": int(prov)}

    events = await _paginate(_graph_request, f"{GRAPH_BASE}/users/{src_uid}/events?$top={PAGE_TOP}", src, limit=10000)
    for ev in events:
        try:
            payload = {
                "subject": ev.get("subject", ""),
                "body": ev.get("body", {}),
                "start": ev.get("start"),
                "end": ev.get("end"),
                "location": ev.get("location"),
                "attendees": ev.get("attendees", []),
                "isAllDay": ev.get("isAllDay", False),
                "isReminderOn": ev.get("isReminderOn", False),
                "recurrence": ev.get("recurrence"),
                "categories": ev.get("categories", []),
                "importance": ev.get("importance", "normal"),
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            await _post(_graph_request, f"{GRAPH_BASE}/users/{dst_uid}/events", dst, payload)
            stats["events_copied"] += 1
        except Exception as e:
            logger.warning(f"event copy failed: {e}")
    return {"status": "success", "error": None, "stats": stats}


# =============================================================================
# Contacts
# =============================================================================

async def migrate_contacts_for_user(item, src, dst, _graph_request) -> Dict[str, Any]:
    """Copy personal contacts for the target user."""
    src_uid = item["id"]
    upn = item.get("owner") or item.get("email") or item.get("primary_smtp") or ""
    if not upn:
        return {"status": "failed", "error": "no source UPN", "stats": {}}
    src_user = await _get(_graph_request, f"{GRAPH_BASE}/users/{src_uid}", src)
    dst_uid, prov = await _find_or_provision_dest_user(_graph_request, upn, src_user, dst)

    stats = {"contacts_copied": 0, "provisioned_user": int(prov)}
    contacts = await _paginate(_graph_request, f"{GRAPH_BASE}/users/{src_uid}/contacts?$top={PAGE_TOP}", src, limit=10000)
    for c in contacts:
        try:
            payload = {k: c.get(k) for k in [
                "displayName", "givenName", "surname", "emailAddresses", "businessPhones",
                "mobilePhone", "companyName", "jobTitle", "department", "personalNotes",
                "businessAddress", "homeAddress", "birthday",
            ] if c.get(k) is not None}
            await _post(_graph_request, f"{GRAPH_BASE}/users/{dst_uid}/contacts", dst, payload)
            stats["contacts_copied"] += 1
        except Exception as e:
            logger.warning(f"contact copy failed: {e}")
    return {"status": "success", "error": None, "stats": stats}


# =============================================================================
# OneDrive ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â full file tree copy with chunked upload
# =============================================================================

async def migrate_onedrive(item, src, dst, _graph_request) -> Dict[str, Any]:
    src_uid = item["id"]
    upn = item.get("owner") or item.get("primary_smtp") or ""
    if not upn:
        return {"status": "failed", "error": "no source UPN/owner", "stats": {}}
    src_user = await _get(_graph_request, f"{GRAPH_BASE}/users/{src_uid}", src)
    dst_uid, prov = await _find_or_provision_dest_user(_graph_request, upn, src_user, dst)

    # Ensure destination drive is provisioned by touching /drive
    try:
        await _get(_graph_request, f"{GRAPH_BASE}/users/{dst_uid}/drive", dst)
    except Exception:
        pass  # will retry lazily

    stats = {"files_copied": 0, "folders_created": 0, "bytes": 0, "provisioned_user": int(prov)}
    await _copy_drive_children(
        _graph_request,
        src_uid=src_uid, dst_uid=dst_uid,
        src=src, dst=dst,
        src_path="root", dst_path_prefix="",
        stats=stats,
    )
    return {"status": "success", "error": None, "stats": stats}


async def _copy_drive_children(
    _graph_request, *, src_uid, dst_uid, src, dst,
    src_path: str, dst_path_prefix: str, stats: Dict[str, int],
):
    url = f"{GRAPH_BASE}/users/{src_uid}/drive/{src_path}/children?$top={PAGE_TOP}"
    items = await _paginate(_graph_request, url, src, limit=20000)
    for it in items:
        name = it.get("name", "unnamed")
        rel_path = f"{dst_path_prefix}/{name}".lstrip("/")
        if it.get("folder"):
            # Create folder in destination
            try:
                await _post(
                    _graph_request,
                    f"{GRAPH_BASE}/users/{dst_uid}/drive/root:/{dst_path_prefix}:/children" if dst_path_prefix else f"{GRAPH_BASE}/users/{dst_uid}/drive/root/children",
                    dst,
                    {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"},
                )
                stats["folders_created"] += 1
            except Exception as e:
                logger.warning(f"folder create failed: {e}")
            # Recurse
            await _copy_drive_children(
                _graph_request, src_uid=src_uid, dst_uid=dst_uid, src=src, dst=dst,
                src_path=f"items/{it['id']}", dst_path_prefix=rel_path, stats=stats,
            )
        else:
            size = it.get("size", 0) or 0
            try:
                await _copy_file(_graph_request, src, dst, src_uid, dst_uid, it, rel_path)
                stats["files_copied"] += 1
                stats["bytes"] += size
            except Exception as e:
                logger.warning(f"file copy failed for {name}: {e}")


async def _copy_file(_graph_request, src, dst, src_uid, dst_uid, item, dst_rel_path: str):
    """Download bytes from source, upload to destination. Uses createUploadSession for >4MB."""
    dl_url = item.get("@microsoft.graph.downloadUrl")
    if not dl_url:
        # Refetch item with metadata to get the download URL
        fresh = await _get(_graph_request, f"{GRAPH_BASE}/users/{src_uid}/drive/items/{item['id']}?select=@microsoft.graph.downloadUrl,size,name", src)
        dl_url = fresh.get("@microsoft.graph.downloadUrl")
    if not dl_url:
        raise RuntimeError("no download URL for item")

    size = item.get("size", 0) or 0

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(dl_url)
        r.raise_for_status()
        content = r.content

    if size <= 4 * 1024 * 1024:
        # Small file ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â PUT direct
        # Use graph adapter's plain httpx via token
        from graph_adapter import acquire_token
        token = await acquire_token(dst)
        put_url = f"{GRAPH_BASE}/users/{dst_uid}/drive/root:/{dst_rel_path}:/content"
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.put(
                put_url,
                content=content,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
            )
            r.raise_for_status()
        return

    # Large file ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â createUploadSession + chunked PUT
    session = await _post(
        _graph_request,
        f"{GRAPH_BASE}/users/{dst_uid}/drive/root:/{dst_rel_path}:/createUploadSession",
        dst,
        {"item": {"@microsoft.graph.conflictBehavior": "rename", "name": item.get("name", "unnamed")}},
    )
    upload_url = session["uploadUrl"]
    async with httpx.AsyncClient(timeout=120.0) as client:
        for start in range(0, size, CHUNK):
            end = min(start + CHUNK, size) - 1
            chunk = content[start:end + 1]
            headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            }
            r = await client.put(upload_url, content=chunk, headers=headers)
            r.raise_for_status()


# =============================================================================
# M365 Groups
# =============================================================================

async def migrate_group(item, src, dst, _graph_request) -> Dict[str, Any]:
    src_gid = item["id"]
    stats = {"members_copied": 0, "owners_copied": 0}
    group = await _get(_graph_request, f"{GRAPH_BASE}/groups/{src_gid}", src)
    body = {
        "displayName": group.get("displayName", ""),
        "description": group.get("description", ""),
        "mailNickname": group.get("mailNickname") or group.get("displayName", "grp").replace(" ", "-").lower()[:60],
        "mailEnabled": bool(group.get("mailEnabled", True)),
        "securityEnabled": bool(group.get("securityEnabled", False)),
        "groupTypes": group.get("groupTypes", ["Unified"]),
        "visibility": group.get("visibility", "Private"),
    }
    created = await _post(_graph_request, f"{GRAPH_BASE}/groups", dst, body)
    dst_gid = created["id"]

    # Members
    members = await _paginate(_graph_request, f"{GRAPH_BASE}/groups/{src_gid}/members?$select=id,userPrincipalName,mail", src, limit=5000)
    for m in members:
        upn = m.get("userPrincipalName") or m.get("mail")
        if not upn:
            continue
        try:
            dst_user = await _get(_graph_request, f"{GRAPH_BASE}/users/{upn}", dst)
            await _post(
                _graph_request, f"{GRAPH_BASE}/groups/{dst_gid}/members/$ref", dst,
                {"@odata.id": f"{GRAPH_BASE}/directoryObjects/{dst_user['id']}"},
            )
            stats["members_copied"] += 1
        except Exception:
            continue

    # Owners
    owners = await _paginate(_graph_request, f"{GRAPH_BASE}/groups/{src_gid}/owners?$select=id,userPrincipalName", src, limit=200)
    for o in owners:
        upn = o.get("userPrincipalName")
        if not upn:
            continue
        try:
            dst_user = await _get(_graph_request, f"{GRAPH_BASE}/users/{upn}", dst)
            await _post(
                _graph_request, f"{GRAPH_BASE}/groups/{dst_gid}/owners/$ref", dst,
                {"@odata.id": f"{GRAPH_BASE}/directoryObjects/{dst_user['id']}"},
            )
            stats["owners_copied"] += 1
        except Exception:
            continue

    return {"status": "success", "error": None, "stats": stats}


# =============================================================================
# Distribution Lists (mail-enabled, non-security groups)
# =============================================================================

async def migrate_distribution_list(item, src, dst, _graph_request) -> Dict[str, Any]:
    src_gid = item["id"]
    stats = {"members_copied": 0}
    group = await _get(_graph_request, f"{GRAPH_BASE}/groups/{src_gid}", src)
    body = {
        "displayName": group.get("displayName", ""),
        "description": group.get("description", ""),
        "mailNickname": group.get("mailNickname") or "dl-" + str(src_gid[:6]),
        "mailEnabled": True,
        "securityEnabled": False,
    }
    created = await _post(_graph_request, f"{GRAPH_BASE}/groups", dst, body)
    dst_gid = created["id"]
    members = await _paginate(_graph_request, f"{GRAPH_BASE}/groups/{src_gid}/members?$select=id,userPrincipalName", src, limit=5000)
    for m in members:
        upn = m.get("userPrincipalName") or m.get("mail")
        if not upn:
            continue
        try:
            dst_user = await _get(_graph_request, f"{GRAPH_BASE}/users/{upn}", dst)
            await _post(
                _graph_request, f"{GRAPH_BASE}/groups/{dst_gid}/members/$ref", dst,
                {"@odata.id": f"{GRAPH_BASE}/directoryObjects/{dst_user['id']}"},
            )
            stats["members_copied"] += 1
        except Exception:
            continue
    return {"status": "success", "error": None, "stats": stats}


# =============================================================================
# SharePoint ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â site shell + document library files
# =============================================================================

async def migrate_sharepoint_site(item, src, dst, _graph_request) -> Dict[str, Any]:
    """Provision a communication site in the destination with the same title,
    then copy the default document library contents (drive)."""
    src_site_id = item["id"]
    stats = {"files_copied": 0, "folders_created": 0, "bytes": 0, "site_created": 0}

    src_site = await _get(_graph_request, f"{GRAPH_BASE}/sites/{src_site_id}", src)

    # Provision a Team site in destination via Groups (Team-connected site)
    display_name = src_site.get("displayName") or src_site.get("name", "Migrated Site")
    alias = display_name.replace(" ", "-").lower()[:60] or "migrated-site"
    group_body = {
        "displayName": display_name,
        "description": src_site.get("description", ""),
        "mailNickname": alias,
        "mailEnabled": True,
        "securityEnabled": False,
        "groupTypes": ["Unified"],
        "visibility": "Private",
    }
    created_group = await _post(_graph_request, f"{GRAPH_BASE}/groups", dst, group_body)
    stats["site_created"] = 1

    # Wait for site to be provisioned via the group, then copy drive contents
    await asyncio.sleep(3)
    try:
        # Get root site of the new group
        dst_site = await _get(_graph_request, f"{GRAPH_BASE}/groups/{created_group['id']}/sites/root", dst)
        dst_site_id = dst_site["id"]
    except Exception as e:
        return {"status": "partial", "error": f"site provisioned but drive lookup failed: {e}", "stats": stats}

    # Copy default drive
    try:
        await _copy_site_drive(_graph_request, src, dst, src_site_id, dst_site_id, "", stats)
    except Exception as e:
        return {"status": "partial", "error": f"site created; drive copy failed: {e}", "stats": stats}

    return {"status": "success", "error": None, "stats": stats}


async def _copy_site_drive(_graph_request, src, dst, src_site_id, dst_site_id, path_prefix: str, stats):
    src_children_url = (
        f"{GRAPH_BASE}/sites/{src_site_id}/drive/root/children?$top={PAGE_TOP}"
        if not path_prefix else
        f"{GRAPH_BASE}/sites/{src_site_id}/drive/root:/{path_prefix}:/children?$top={PAGE_TOP}"
    )
    items = await _paginate(_graph_request, src_children_url, src, limit=20000)
    for it in items:
        name = it.get("name", "unnamed")
        rel = f"{path_prefix}/{name}".lstrip("/")
        if it.get("folder"):
            try:
                target_url = (
                    f"{GRAPH_BASE}/sites/{dst_site_id}/drive/root/children" if not path_prefix else
                    f"{GRAPH_BASE}/sites/{dst_site_id}/drive/root:/{path_prefix}:/children"
                )
                await _post(_graph_request, target_url, dst,
                            {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"})
                stats["folders_created"] += 1
            except Exception:
                pass
            await _copy_site_drive(_graph_request, src, dst, src_site_id, dst_site_id, rel, stats)
        else:
            size = it.get("size", 0) or 0
            try:
                await _copy_site_file(_graph_request, src, dst, src_site_id, dst_site_id, it, rel)
                stats["files_copied"] += 1
                stats["bytes"] += size
            except Exception as e:
                logger.warning(f"site file copy failed: {e}")


async def _copy_site_file(_graph_request, src, dst, src_site_id, dst_site_id, item, dst_rel_path):
    dl_url = item.get("@microsoft.graph.downloadUrl")
    if not dl_url:
        fresh = await _get(_graph_request, f"{GRAPH_BASE}/sites/{src_site_id}/drive/items/{item['id']}?select=@microsoft.graph.downloadUrl,size,name", src)
        dl_url = fresh.get("@microsoft.graph.downloadUrl")
    if not dl_url:
        raise RuntimeError("no download URL for item")
    size = item.get("size", 0) or 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(dl_url)
        r.raise_for_status()
        content = r.content

    from graph_adapter import acquire_token
    token = await acquire_token(dst)
    if size <= 4 * 1024 * 1024:
        put_url = f"{GRAPH_BASE}/sites/{dst_site_id}/drive/root:/{dst_rel_path}:/content"
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.put(put_url, content=content,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"})
            r.raise_for_status()
        return
    session = await _post(
        _graph_request,
        f"{GRAPH_BASE}/sites/{dst_site_id}/drive/root:/{dst_rel_path}:/createUploadSession",
        dst,
        {"item": {"@microsoft.graph.conflictBehavior": "rename", "name": item.get("name", "unnamed")}},
    )
    upload_url = session["uploadUrl"]
    async with httpx.AsyncClient(timeout=120.0) as client:
        for start in range(0, size, CHUNK):
            end = min(start + CHUNK, size) - 1
            chunk = content[start:end + 1]
            r = await client.put(upload_url, content=chunk,
                                 headers={"Content-Length": str(len(chunk)),
                                          "Content-Range": f"bytes {start}-{end}/{size}"})
            r.raise_for_status()


# =============================================================================
# Teams ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â team shell + channels (+ message import when supported)
# =============================================================================

async def migrate_team(item, src, dst, _graph_request) -> Dict[str, Any]:
    src_tid = item["id"]
    stats = {"team_created": 0, "channels_created": 0, "members_copied": 0}

    src_team = await _get(_graph_request, f"{GRAPH_BASE}/teams/{src_tid}", src)
    # Get associated group to derive display name & privacy
    src_group = await _get(_graph_request, f"{GRAPH_BASE}/groups/{src_tid}", src)

    # Create matching group + team in destination
    group_body = {
        "displayName": src_group.get("displayName", "Migrated Team"),
        "description": src_group.get("description", ""),
        "mailNickname": (src_group.get("mailNickname") or "team")[:60],
        "mailEnabled": True,
        "securityEnabled": False,
        "groupTypes": ["Unified"],
        "visibility": src_group.get("visibility", "Private"),
    }
    created_group = await _post(_graph_request, f"{GRAPH_BASE}/groups", dst, group_body)
    dst_group_id = created_group["id"]

    # Convert group to team
    team_body = {
        "memberSettings": src_team.get("memberSettings", {}),
        "messagingSettings": src_team.get("messagingSettings", {}),
        "funSettings": src_team.get("funSettings", {}),
    }
    try:
        await _graph_request("PUT", f"{GRAPH_BASE}/groups/{dst_group_id}/team", dst, json_body=team_body)
        stats["team_created"] = 1
    except Exception as e:
        return {"status": "partial", "error": f"group created; team creation failed: {e}", "stats": stats}

    # Copy channels (skip default "General")
    channels = await _paginate(_graph_request, f"{GRAPH_BASE}/teams/{src_tid}/channels", src, limit=200)
    for ch in channels:
        if ch.get("displayName") == "General":
            continue
        try:
            await _post(_graph_request, f"{GRAPH_BASE}/teams/{dst_group_id}/channels", dst, {
                "displayName": ch.get("displayName"),
                "description": ch.get("description", ""),
                "membershipType": ch.get("membershipType", "standard"),
            })
            stats["channels_created"] += 1
        except Exception:
            continue

    # Add members
    members = await _paginate(_graph_request, f"{GRAPH_BASE}/groups/{src_tid}/members?$select=id,userPrincipalName", src, limit=5000)
    for m in members:
        upn = m.get("userPrincipalName")
        if not upn:
            continue
        try:
            dst_user = await _get(_graph_request, f"{GRAPH_BASE}/users/{upn}", dst)
            await _post(_graph_request, f"{GRAPH_BASE}/groups/{dst_group_id}/members/$ref", dst,
                        {"@odata.id": f"{GRAPH_BASE}/directoryObjects/{dst_user['id']}"})
            stats["members_copied"] += 1
        except Exception:
            continue

    # Note on messages: Teams message migration requires "import mode" ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â
    # POST /teams with createdDateTime + Teamwork.Migrate.All. That's a
    # different code path (recreate team in migration mode). Not covered here.
    return {"status": "success", "error": None, "stats": stats, "note": "Team shell + channels + members migrated. Chat messages require Teams import-mode API + Teamwork.Migrate.All permission."}


# =============================================================================
# Public Folders ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â NOT exposed via Microsoft Graph
# =============================================================================

async def migrate_public_folder(item, src, dst, _graph_request) -> Dict[str, Any]:
    return {
        "status": "failed",
        "error": (
            "Microsoft Graph does not expose Public Folders. "
            "Cross-tenant Public Folder migration requires Exchange PowerShell "
            "(New-PublicFolderMigrationRequest / MRS) or a 3rd-party tool "
            "(BitTitan, Quest, ShareGate)."
        ),
        "stats": {},
    }


# =============================================================================
# Dispatcher
# =============================================================================

DISPATCH = {
    "exchange": migrate_exchange,
    "calendars": migrate_calendar,
    "contacts": migrate_contacts_for_user,
    "onedrive": migrate_onedrive,
    "groups": migrate_group,
    "distribution_lists": migrate_distribution_list,
    "sharepoint": migrate_sharepoint_site,
    "teams": migrate_team,
    "public_folders": migrate_public_folder,
}

