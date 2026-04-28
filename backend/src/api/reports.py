"""
Phase 4: Evidence report endpoints.

GET /api/reports/{alert_id}       — JSON evidence report
GET /api/reports/{alert_id}/html  — Printable HTML evidence report
GET /api/reports/{alert_id}/tamper — Raw tamper analysis for an alert
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import MatchAlert
from src.reports.evidence import generate_evidence_report, report_to_html

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports")


@router.get("/{alert_id}")
def get_report_json(alert_id: str, db: Session = Depends(get_db)) -> dict:
    """Get the machine-readable JSON evidence report for a match alert."""
    alert = db.get(MatchAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    try:
        return generate_evidence_report(alert_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{alert_id}/html", response_class=HTMLResponse)
def get_report_html(alert_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """
    Get a printable HTML evidence report.
    Open in browser and use File → Print → Save as PDF for a portable document.
    """
    alert = db.get(MatchAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    try:
        report = generate_evidence_report(alert_id)
        html = report_to_html(report)
        return HTMLResponse(content=html)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{alert_id}/tamper")
def get_tamper_detail(alert_id: str, db: Session = Depends(get_db)) -> dict:
    """Get raw tamper analysis details for an alert."""
    alert = db.get(MatchAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    import json, ast
    details = {}
    if alert.tamper_details:
        try:
            details = json.loads(alert.tamper_details)
        except Exception:
            try:
                details = ast.literal_eval(alert.tamper_details)
            except Exception:
                details = {"raw": alert.tamper_details}

    return {
        "alert_id": alert_id,
        "tamper_score": alert.tamper_score,
        "details": details,
    }
