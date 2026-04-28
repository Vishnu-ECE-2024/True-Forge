"""Phase 5: Statistics endpoint for dashboard charts."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.models import AssetStatus, MonitorJobStatus
from src.db.database import get_db
from src.db.models import Asset, MatchAlert, MonitorJob

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stats")


@router.get("/")
def get_stats(db: Session = Depends(get_db)) -> dict:
    """
    Return aggregated statistics for the dashboard.
    All counts, match rates, and time-series data for charts.
    """
    # Asset counts
    total_assets  = db.query(Asset).count()
    ready_assets  = db.query(Asset).filter(Asset.status == AssetStatus.READY).count()
    failed_assets = db.query(Asset).filter(Asset.status == AssetStatus.FAILED).count()
    watermarked   = db.query(Asset).filter(Asset.watermark_embedded == True).count()  # noqa

    # Monitor job counts
    total_jobs    = db.query(MonitorJob).count()
    pending_jobs  = db.query(MonitorJob).filter(
        MonitorJob.status.in_([MonitorJobStatus.QUEUED, MonitorJobStatus.RUNNING])
    ).count()

    # Alert counts
    total_alerts    = db.query(MatchAlert).count()
    unreviewed      = db.query(MatchAlert).filter(MatchAlert.reviewed == False).count()  # noqa
    exact_matches   = db.query(MatchAlert).filter(MatchAlert.match_type == "exact").count()
    near_dupe       = db.query(MatchAlert).filter(MatchAlert.match_type == "near_duplicate").count()

    # Platform breakdown
    platform_rows = (
        db.query(MatchAlert.platform, func.count(MatchAlert.alert_id))
        .group_by(MatchAlert.platform)
        .all()
    )
    platforms = {(p or "unknown"): c for p, c in platform_rows}

    # Alerts per day (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    daily_rows = (
        db.query(
            func.date(MatchAlert.created_at).label("day"),
            func.count(MatchAlert.alert_id).label("count"),
        )
        .filter(MatchAlert.created_at >= thirty_days_ago)
        .group_by(func.date(MatchAlert.created_at))
        .order_by(func.date(MatchAlert.created_at))
        .all()
    )
    daily_alerts = [{"date": str(r.day), "count": r.count} for r in daily_rows]

    # Assets registered per day (last 30 days)
    asset_daily_rows = (
        db.query(
            func.date(Asset.created_at).label("day"),
            func.count(Asset.asset_id).label("count"),
        )
        .filter(Asset.created_at >= thirty_days_ago)
        .group_by(func.date(Asset.created_at))
        .order_by(func.date(Asset.created_at))
        .all()
    )
    daily_registrations = [{"date": str(r.day), "count": r.count} for r in asset_daily_rows]

    return {
        "assets": {
            "total": total_assets,
            "ready": ready_assets,
            "failed": failed_assets,
            "watermarked": watermarked,
        },
        "monitoring": {
            "total_jobs": total_jobs,
            "pending_jobs": pending_jobs,
        },
        "alerts": {
            "total": total_alerts,
            "unreviewed": unreviewed,
            "exact_matches": exact_matches,
            "near_duplicates": near_dupe,
            "by_platform": platforms,
        },
        "charts": {
            "daily_alerts": daily_alerts,
            "daily_registrations": daily_registrations,
        },
    }
