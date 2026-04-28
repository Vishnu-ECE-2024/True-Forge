"""
Phase 4: Evidence package generator.

Generates a structured evidence report for a match alert.
Used to document unauthorized redistribution for:
- DMCA takedown notices
- Platform abuse reports
- Legal proceedings

Output: JSON (machine-readable) + HTML (human-readable, printable)
No external PDF library needed — browser print-to-PDF from HTML.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.db.database import get_db_session
from src.db.models import Asset, MatchAlert, MonitorJob

logger = logging.getLogger(__name__)


def generate_evidence_report(alert_id: str) -> dict:
    """
    Build a complete evidence report for a match alert.
    Returns a dict that can be serialized to JSON or rendered as HTML.
    """
    with get_db_session() as db:
        alert = db.get(MatchAlert, alert_id)
        if not alert:
            raise ValueError(f"Alert {alert_id} not found")

        asset = db.get(Asset, alert.matched_asset_id)
        job = db.get(MonitorJob, alert.job_id) if alert.job_id else None

        # Extract all values inside the session — ORM objects become detached on close
        report = {
            "report_id": alert_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "summary": {
                "match_type": alert.match_type,
                "similarity_score": alert.similarity_score,
                "similarity_percent": f"{alert.similarity_score * 100:.1f}%",
                "platform": alert.platform,
                "source_url": alert.source_url,
                "video_title": alert.video_title or "Unknown",
            },
            "original_content": {
                "asset_id": alert.matched_asset_id,
                "filename": asset.original_filename if asset else "Unknown",
                "registered_at": asset.created_at.isoformat() + "Z" if asset else None,
                "duration_seconds": asset.duration_seconds if asset else None,
                "sha256": asset.sha256 if asset else None,
            },
            "suspected_copy": {
                "url": alert.source_url,
                "platform": alert.platform,
                "title": alert.video_title,
                "duration_seconds": job.video_duration if job else None,
                "discovered_at": alert.created_at.isoformat() + "Z",
            },
            "technical_evidence": {
                "visual_fingerprint_match": True,
                "watermark_detected": alert.watermark_detected,
                "similarity_score": alert.similarity_score,
                "tamper_score": alert.tamper_score,
                "tamper_details": _parse_tamper_details(alert.tamper_details),
            },
            "legal_notice": (
                "This report documents a potential unauthorized use of copyrighted content. "
                "Fingerprint comparison was performed using perceptual hashing. "
                "This report should be reviewed by a qualified legal professional before "
                "submitting any formal legal claim."
            ),
        }

    return report


def _parse_tamper_details(details_str: str | None) -> dict:
    if not details_str:
        return {}
    try:
        return json.loads(details_str)
    except Exception:
        pass
    try:
        import ast
        return ast.literal_eval(details_str)
    except Exception:
        return {"raw": details_str}


def report_to_html(report: dict) -> str:
    """
    Render evidence report as a print-ready HTML page.
    Inline styles for email/PDF compatibility.
    """
    s = report["summary"]
    o = report["original_content"]
    c = report["suspected_copy"]
    t = report["technical_evidence"]

    match_color = {"exact": "#dc2626", "near_duplicate": "#d97706", "partial": "#ca8a04"}.get(
        s["match_type"], "#6b7280"
    )

    tamper_flags = t.get("tamper_details", {}).get("flags", [])
    flags_html = "".join(f"<li>{f}</li>" for f in tamper_flags) if tamper_flags else "<li>None detected</li>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Evidence Report — {report['report_id'][:8]}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; color: #111; font-size: 14px; }}
  h1 {{ color: #1e3a5f; border-bottom: 2px solid #1e3a5f; padding-bottom: 8px; }}
  h2 {{ color: #374151; margin-top: 24px; font-size: 15px; text-transform: uppercase; letter-spacing: .05em; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  td {{ padding: 6px 8px; border: 1px solid #e5e7eb; }}
  td:first-child {{ font-weight: 600; background: #f9fafb; width: 40%; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 4px; font-weight: bold;
            background: {match_color}; color: white; font-size: 13px; }}
  .score-bar-bg {{ background:#e5e7eb; border-radius:4px; height:10px; margin-top:4px; }}
  .score-bar {{ background:{match_color}; border-radius:4px; height:10px;
                width:{s['similarity_score']*100:.0f}%; }}
  .notice {{ background:#fffbeb; border:1px solid #fcd34d; padding:12px; border-radius:4px; font-size:12px; margin-top:24px; }}
  @media print {{ body {{ margin: 20px; }} }}
</style>
</head>
<body>
<h1>Copyright Infringement Evidence Report</h1>
<p><strong>Report ID:</strong> {report['report_id']}</p>
<p><strong>Generated:</strong> {report['generated_at']}</p>
<p><strong>Match type:</strong> <span class="badge">{s['match_type'].upper()}</span></p>
<div class="score-bar-bg"><div class="score-bar"></div></div>
<p style="font-size:12px;color:#6b7280">Similarity: {s['similarity_percent']}</p>

<h2>Original Content</h2>
<table>
  <tr><td>File</td><td>{o['filename']}</td></tr>
  <tr><td>Asset ID</td><td><code>{o['asset_id']}</code></td></tr>
  <tr><td>Registered</td><td>{o['registered_at'] or 'Unknown'}</td></tr>
  <tr><td>Duration</td><td>{f"{o['duration_seconds']:.1f}s" if o['duration_seconds'] else 'Unknown'}</td></tr>
  <tr><td>SHA-256</td><td><code style="font-size:11px">{o['sha256'] or 'N/A'}</code></td></tr>
</table>

<h2>Suspected Copy</h2>
<table>
  <tr><td>Platform</td><td>{c['platform'].title()}</td></tr>
  <tr><td>URL</td><td><a href="{c['url']}">{c['url']}</a></td></tr>
  <tr><td>Title</td><td>{c['title'] or 'Unknown'}</td></tr>
  <tr><td>Duration</td><td>{f"{c['duration_seconds']:.1f}s" if c['duration_seconds'] else 'Unknown'}</td></tr>
  <tr><td>Discovered</td><td>{c['discovered_at']}</td></tr>
</table>

<h2>Technical Evidence</h2>
<table>
  <tr><td>Visual fingerprint match</td><td>{'Yes ✓' if t['visual_fingerprint_match'] else 'No'}</td></tr>
  <tr><td>Watermark detected</td><td>{'Yes ✓' if t['watermark_detected'] else 'No / Not embedded'}</td></tr>
  <tr><td>Similarity score</td><td>{t['similarity_score']:.4f} ({t['similarity_score']*100:.1f}%)</td></tr>
  <tr><td>Tamper score</td><td>{t['tamper_score']:.4f} (0=clean, 1=heavily modified)</td></tr>
  <tr><td>Tamper indicators</td><td><ul style="margin:0;padding-left:16px">{flags_html}</ul></td></tr>
</table>

<div class="notice">{report['legal_notice']}</div>

<p style="margin-top:32px;font-size:11px;color:#9ca3af">
  Generated by Sports Media Protection System · {report['generated_at']}
</p>
</body>
</html>"""
