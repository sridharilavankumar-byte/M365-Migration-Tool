"""
Report generation â€” CSV and PDF for completed migration jobs.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)


def render_csv(job: Dict[str, Any]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Job ID", job.get("id")])
    writer.writerow(["Project", job.get("project_name")])
    writer.writerow(["Service", job.get("service_type")])
    writer.writerow(["Status", job.get("status")])
    writer.writerow(["Mode", job.get("mode")])
    writer.writerow(["Started", job.get("started_at") or ""])
    writer.writerow(["Finished", job.get("finished_at") or ""])
    writer.writerow(["Total", job.get("total")])
    writer.writerow(["Success", job.get("success_count")])
    writer.writerow(["Failed", job.get("fail_count")])
    writer.writerow([])
    writer.writerow(["Item ID", "Display Name", "Status", "Finished At", "Error"])
    for it in job.get("items", []):
        writer.writerow([
            it.get("id"), it.get("display_name"), it.get("status"),
            it.get("finished_at") or "", it.get("error") or "",
        ])
    return buf.getvalue().encode("utf-8")


def render_consolidated_pdf(jobs: List[Dict[str, Any]], filter_desc: str = "") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="M365 Migration Suite - Consolidated Report",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Heading1"],
        fontName="Helvetica-Bold", fontSize=16, spaceAfter=8, textColor=colors.HexColor("#0a0a0a"),
    )
    subtitle_style = ParagraphStyle(
        "subtitle", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#6b7280"), spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "section", parent=styles["Heading2"],
        fontName="Helvetica-Bold", fontSize=11, textColor=colors.HexColor("#111827"),
        spaceBefore=12, spaceAfter=6,
    )

    total_jobs = len(jobs)
    total_success = sum(j.get("success_count", 0) for j in jobs)
    total_failed = sum(j.get("fail_count", 0) for j in jobs)

    story = []
    story.append(Paragraph("M365 Migration Suite - Consolidated Report", title_style))
    subtitle = f"Generated for {total_jobs} job(s)"
    if filter_desc:
        subtitle += f" ({filter_desc})"
    story.append(Paragraph(subtitle, subtitle_style))

    summary_rows = [
        ["Total Jobs", str(total_jobs)],
        ["Items Succeeded", str(total_success)],
        ["Items Failed", str(total_failed)],
    ]
    t = Table(summary_rows, colWidths=[45 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)

    story.append(Paragraph("Job Detail", section_style))
    header = ["Project", "Service", "Status", "Success", "Failed", "Started"]
    data = [header]
    for j in jobs:
        data.append([
            (j.get("project_name") or "")[:30],
            j.get("service_type", ""),
            j.get("status", ""),
            str(j.get("success_count", 0)),
            str(j.get("fail_count", 0)),
            (j.get("started_at") or "")[:19],
        ])
    dt = Table(data, colWidths=[40 * mm, 28 * mm, 22 * mm, 18 * mm, 18 * mm, 44 * mm], repeatRows=1)
    dt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(dt)

    doc.build(story)
    return buf.getvalue()


def render_pdf(job: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Migration Report {job.get('id')}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Heading1"],
        fontName="Helvetica-Bold", fontSize=16, spaceAfter=8, textColor=colors.HexColor("#0a0a0a"),
    )
    subtitle_style = ParagraphStyle(
        "subtitle", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#6b7280"), spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "section", parent=styles["Heading2"],
        fontName="Helvetica-Bold", fontSize=11, textColor=colors.HexColor("#111827"),
        spaceBefore=12, spaceAfter=6,
    )
    body = styles["Normal"]

    story: List = []
    story.append(Paragraph("M365 Migration Suite â€” Job Report", title_style))
    story.append(Paragraph(f"Generated for job <b>{job.get('id')}</b>", subtitle_style))

    # Summary table
    summary_rows = [
        ["Project", job.get("project_name")],
        ["Service", job.get("service_type")],
        ["Mode", job.get("mode")],
        ["Status", job.get("status")],
        ["Started", job.get("started_at") or "â€”"],
        ["Finished", job.get("finished_at") or "â€”"],
        ["Total Items", str(job.get("total"))],
        ["Succeeded", str(job.get("success_count"))],
        ["Failed", str(job.get("fail_count"))],
    ]
    t = Table(summary_rows, colWidths=[45 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)

    story.append(Paragraph("Item Detail", section_style))

    header = ["ID", "Display Name", "Status", "Error"]
    data = [header]
    for it in job.get("items", []):
        data.append([
            it.get("id", ""),
            (it.get("display_name") or "")[:60],
            it.get("status", ""),
            (it.get("error") or "")[:80],
        ])
    dt = Table(data, colWidths=[28 * mm, 65 * mm, 22 * mm, 55 * mm], repeatRows=1)
    dt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(dt)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("Rollback Instructions", section_style))
    story.append(Paragraph(
        "1. Retain source tenant data until 30 days post-cutover.<br/>"
        "2. Reverse-map successful items using the ID column above.<br/>"
        "3. Failed items can be replayed via 'Retry Failed' in the Job Detail view.<br/>",
        body,
    ))

    doc.build(story)
    return buf.getvalue()
