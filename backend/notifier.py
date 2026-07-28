"""
Notifications — email (Resend, SendGrid) and generic webhooks.
Each project can configure its own recipients + webhook URL, or fall back to
global env-driven settings.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("notifier")


async def _send_resend(to: str, subject: str, html: str) -> Dict[str, Any]:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return {"ok": False, "provider": "resend", "error": "RESEND_API_KEY not set"}
    try:
        import resend
        resend.api_key = api_key
        params = {
            "from": os.environ.get("RESEND_SENDER", "onboarding@resend.dev"),
            "to": [to],
            "subject": subject,
            "html": html,
        }
        result = await asyncio.to_thread(resend.Emails.send, params)
        return {"ok": True, "provider": "resend", "id": result.get("id")}
    except Exception as e:
        return {"ok": False, "provider": "resend", "error": str(e)[:300]}


async def _send_sendgrid(to: str, subject: str, html: str) -> Dict[str, Any]:
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        return {"ok": False, "provider": "sendgrid", "error": "SENDGRID_API_KEY not set"}
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        message = Mail(
            from_email=os.environ.get("SENDGRID_SENDER", "no-reply@migratetool.com"),
            to_emails=to,
            subject=subject,
            html_content=html,
        )
        client = SendGridAPIClient(api_key)
        result = await asyncio.to_thread(client.send, message)
        return {"ok": True, "provider": "sendgrid", "status": result.status_code}
    except Exception as e:
        return {"ok": False, "provider": "sendgrid", "error": str(e)[:300]}


async def send_email(provider: str, to: str, subject: str, html: str) -> Dict[str, Any]:
    provider = (provider or "").lower()
    if provider == "resend":
        return await _send_resend(to, subject, html)
    if provider == "sendgrid":
        return await _send_sendgrid(to, subject, html)
    return {"ok": False, "provider": provider or "none", "error": "unknown provider"}


async def send_webhook(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not url:
        return {"ok": False, "error": "no webhook url"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
        return {"ok": 200 <= resp.status_code < 300, "status": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def render_job_completion_email(job: Dict[str, Any]) -> str:
    """Render a simple inline-CSS HTML email for job completion."""
    color_ok = "#00b3cc"
    row_style = "padding:8px 12px;border:1px solid #e5e7eb;font-family:'Segoe UI',sans-serif;font-size:13px;"
    return f"""
    <div style="font-family:'Segoe UI',sans-serif;color:#111;background:#f6f7f9;padding:24px;">
      <div style="max-width:560px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;">
        <div style="background:{color_ok};color:#000;padding:16px 20px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;font-size:12px;">
          Migration Job {job.get('status','completed').upper()}
        </div>
        <div style="padding:20px;">
          <h2 style="margin:0 0 10px 0;font-size:18px;">{job.get('project_name')} · {job.get('service_type')}</h2>
          <p style="margin:0 0 16px 0;color:#4b5563;font-size:13px;">Job ID: <code>{job.get('id')}</code></p>
          <table style="width:100%;border-collapse:collapse;">
            <tr><td style="{row_style}">Total Items</td><td style="{row_style}"><b>{job.get('total')}</b></td></tr>
            <tr><td style="{row_style}">Succeeded</td><td style="{row_style};color:#059669;"><b>{job.get('success_count')}</b></td></tr>
            <tr><td style="{row_style}">Failed</td><td style="{row_style};color:#dc2626;"><b>{job.get('fail_count')}</b></td></tr>
            <tr><td style="{row_style}">Mode</td><td style="{row_style}">{job.get('mode')}</td></tr>
            <tr><td style="{row_style}">Started</td><td style="{row_style}">{job.get('started_at','')}</td></tr>
            <tr><td style="{row_style}">Finished</td><td style="{row_style}">{job.get('finished_at','')}</td></tr>
          </table>
          <p style="margin-top:20px;color:#6b7280;font-size:12px;">M365 Migration Suite · automated notification</p>
        </div>
      </div>
    </div>
    """


async def notify_job_complete(project: Dict[str, Any], job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fire all configured notifications for a completed job."""
    settings = (project or {}).get("notification_settings") or {}
    results: List[Dict[str, Any]] = []

    subject = f"[Migration] {job.get('service_type')} — {job.get('status','completed').upper()} — {job.get('project_name')}"
    html = render_job_completion_email(job)

    provider = settings.get("email_provider") or os.environ.get("EMAIL_PROVIDER", "resend")
    recipient = settings.get("email_to")
    if recipient:
        results.append(await send_email(provider, recipient, subject, html))

    webhook = settings.get("webhook_url")
    if webhook:
        payload = {
            "event": "job.completed",
            "job_id": job.get("id"),
            "project_id": job.get("project_id"),
            "service_type": job.get("service_type"),
            "status": job.get("status"),
            "total": job.get("total"),
            "success_count": job.get("success_count"),
            "fail_count": job.get("fail_count"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
        }
        results.append(await send_webhook(webhook, payload))

    return results
