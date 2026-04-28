"""
Phase 3: URL monitoring endpoints.

POST /api/monitor/submit       — submit a URL to check
GET  /api/monitor/jobs         — list all monitoring jobs
GET  /api/monitor/jobs/{id}    — get job status
GET  /api/monitor/alerts       — list all match alerts
GET  /api/monitor/alerts/{id}  — get alert detail
PATCH /api/monitor/alerts/{id}/review — mark alert as reviewed
DELETE /api/monitor/jobs/{id}  — cancel/delete a job
"""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import MatchAlert, MonitorJob, MonitorJobStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monitor")


class SubmitUrlRequest(BaseModel):
    url: str  # plain str to avoid HttpUrl strictness with non-standard platforms


class JobResponse(BaseModel):
    job_id: str
    url: str
    status: str
    platform: str | None
    video_title: str | None
    video_duration: float | None
    alerts_created: int | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    error_message: str | None


class AlertResponse(BaseModel):
    alert_id: str
    job_id: str | None
    matched_asset_id: str
    matched_filename: str
    source_url: str
    platform: str | None
    video_title: str | None
    similarity_score: float
    similarity_percent: str
    match_type: str
    tamper_score: float | None
    watermark_detected: bool
    reviewed: bool
    created_at: str


def _job_to_response(job: MonitorJob) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        url=job.url,
        status=job.status.value,
        platform=job.platform,
        video_title=job.video_title,
        video_duration=job.video_duration,
        alerts_created=job.alerts_created,
        created_at=job.created_at.isoformat() + "Z",
        started_at=job.started_at.isoformat() + "Z" if job.started_at else None,
        completed_at=job.completed_at.isoformat() + "Z" if job.completed_at else None,
        error_message=job.error_message,
    )


def _alert_to_response(alert: MatchAlert) -> AlertResponse:
    filename = ""
    if alert.matched_asset:
        filename = alert.matched_asset.original_filename
    return AlertResponse(
        alert_id=alert.alert_id,
        job_id=alert.job_id,
        matched_asset_id=alert.matched_asset_id,
        matched_filename=filename,
        source_url=alert.source_url,
        platform=alert.platform,
        video_title=alert.video_title,
        similarity_score=alert.similarity_score,
        similarity_percent=f"{alert.similarity_score * 100:.1f}%",
        match_type=alert.match_type,
        tamper_score=alert.tamper_score,
        watermark_detected=bool(alert.watermark_detected),
        reviewed=bool(alert.reviewed),
        created_at=alert.created_at.isoformat() + "Z",
    )


@router.post("/submit", response_model=JobResponse, status_code=201)
def submit_url(
    body: SubmitUrlRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobResponse:
    """
    Submit a URL (YouTube, TikTok, etc.) to check against registered originals.
    The system downloads it at lowest quality, fingerprints it, and searches.
    """
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    job_id = str(uuid.uuid4())
    job = MonitorJob(
        job_id=job_id,
        url=body.url,
        status=MonitorJobStatus.QUEUED,
    )
    db.add(job)
    db.commit()

    faiss_index = request.app.state.faiss_index
    from src.monitor.jobs import run_monitor_job
    background_tasks.add_task(run_monitor_job, job_id, faiss_index)

    logger.info(f"Monitor job {job_id} queued for {body.url}")
    return _job_to_response(job)


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[JobResponse]:
    """List all monitoring jobs, newest first."""
    jobs = (
        db.query(MonitorJob)
        .order_by(MonitorJob.created_at.desc())
        .offset(skip).limit(limit).all()
    )
    return [_job_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobResponse:
    job = db.get(MonitorJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _job_to_response(job)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)) -> None:
    job = db.get(MonitorJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status == MonitorJobStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Cannot delete a running job")
    db.delete(job)
    db.commit()


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(
    unreviewed_only: bool = False,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[AlertResponse]:
    """List match alerts, newest first. Filter to unreviewed only if needed."""
    q = db.query(MatchAlert)
    if unreviewed_only:
        q = q.filter(MatchAlert.reviewed == False)  # noqa: E712
    alerts = q.order_by(MatchAlert.created_at.desc()).offset(skip).limit(limit).all()
    return [_alert_to_response(a) for a in alerts]


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
def get_alert(alert_id: str, db: Session = Depends(get_db)) -> AlertResponse:
    alert = db.get(MatchAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return _alert_to_response(alert)


@router.patch("/alerts/{alert_id}/review", response_model=AlertResponse)
def mark_reviewed(alert_id: str, db: Session = Depends(get_db)) -> AlertResponse:
    """Mark an alert as reviewed (acknowledged by operator)."""
    alert = db.get(MatchAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    alert.reviewed = True
    db.commit()
    return _alert_to_response(alert)
