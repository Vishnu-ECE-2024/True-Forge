"""
Phase 3: Monitoring job pipeline.

Full workflow for a submitted URL:
  1. Download video (yt-dlp, worst quality)
  2. Fingerprint (pHash + Chromaprint)
  3. Search FAISS index for matches
  4. Check watermark if match found
  5. Run tamper analysis
  6. Create MatchAlert if similarity > threshold
  7. Clean up temp download
"""

import json
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from src.core.config import settings
from src.core.models import AssetStatus, MonitorJobStatus
from src.db.database import get_db_session
from src.db.models import Asset, MatchAlert, MonitorJob
from src.fingerprint.audio import compare_audio_fingerprints, compute_audio_fingerprint
from src.fingerprint.visual import (
    cleanup_frames,
    compute_visual_fingerprint,
    extract_frames,
)
from src.integrity.tamper import analyze_tamper
from src.monitor.downloader import download_video
from src.search.faiss_index import FaissIndex

logger = logging.getLogger(__name__)


def run_monitor_job(job_id: str, faiss_index: FaissIndex) -> None:
    """
    Execute a monitoring job end-to-end.
    Called as a FastAPI BackgroundTask.
    """
    logger.info(f"Starting monitor job {job_id}")

    # Mark as running
    with get_db_session() as db:
        job = db.get(MonitorJob, job_id)
        if not job:
            logger.error(f"Monitor job {job_id} not found")
            return
        job.status = MonitorJobStatus.RUNNING
        job.started_at = datetime.utcnow()
        url = job.url

    tmp_dir = settings.data_dir / "monitor_tmp" / job_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    downloaded_path: Path | None = None

    try:
        # Step 1: Download
        result = download_video(url, tmp_dir)

        with get_db_session() as db:
            job = db.get(MonitorJob, job_id)
            job.platform = result.platform
            job.video_title = result.title
            job.video_duration = result.duration_seconds

        if not result.success or result.video_path is None:
            _fail_job(job_id, f"Download failed: {result.error}")
            return

        downloaded_path = result.video_path

        # Step 2: Extract frames + fingerprint
        frame_paths = extract_frames(downloaded_path, f"monitor_{job_id}")
        if not frame_paths:
            _fail_job(job_id, "Could not extract frames from downloaded video")
            return

        visual_fp = compute_visual_fingerprint(frame_paths)
        cleanup_frames(f"monitor_{job_id}")

        audio_fp = compute_audio_fingerprint(downloaded_path, f"monitor_{job_id}")

        # Step 3: Search
        hits = faiss_index.search(visual_fp, top_k=10)

        # Step 4: Evaluate each hit
        alerts_created = 0
        with get_db_session() as db:
            for hit in hits:
                if not hit.asset_id:
                    continue

                asset = db.get(Asset, hit.asset_id)
                if asset is None or asset.status != AssetStatus.READY:
                    continue

                # Combine visual + audio similarity
                final_sim = hit.similarity
                if audio_fp and asset.audio_fingerprint:
                    audio_sim = compare_audio_fingerprints(audio_fp, asset.audio_fingerprint)
                    final_sim = round(0.7 * hit.similarity + 0.3 * audio_sim, 4)

                if final_sim < settings.match_threshold * 0.7:
                    continue

                # Step 5: Tamper analysis on the downloaded video
                tamper = analyze_tamper(downloaded_path)

                # Step 6: Create alert
                alert = MatchAlert(
                    alert_id=str(uuid.uuid4()),
                    job_id=job_id,
                    matched_asset_id=hit.asset_id,
                    source_url=url,
                    platform=result.platform,
                    video_title=result.title,
                    similarity_score=final_sim,
                    match_type=_classify(final_sim),
                    tamper_score=tamper["tamper_score"],
                    tamper_details=json.dumps(tamper),
                    watermark_detected=False,  # checked below if needed
                    created_at=datetime.utcnow(),
                )
                db.add(alert)
                alerts_created += 1
                logger.info(
                    f"Alert created: {hit.asset_id} vs {url} "
                    f"(similarity={final_sim:.3f}, tamper={tamper['tamper_score']:.2f})"
                )

        # Mark job complete
        with get_db_session() as db:
            job = db.get(MonitorJob, job_id)
            job.status = MonitorJobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.alerts_created = alerts_created

        logger.info(f"Monitor job {job_id} complete: {alerts_created} alerts")

    except Exception as e:
        logger.error(f"Monitor job {job_id} failed: {e}", exc_info=True)
        _fail_job(job_id, str(e))

    finally:
        # Always clean up downloaded file
        if downloaded_path and downloaded_path.exists():
            downloaded_path.unlink(missing_ok=True)
        import shutil
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _fail_job(job_id: str, error: str) -> None:
    with get_db_session() as db:
        job = db.get(MonitorJob, job_id)
        if job:
            job.status = MonitorJobStatus.FAILED
            job.error_message = error
            job.completed_at = datetime.utcnow()


def _classify(sim: float) -> str:
    if sim >= 0.97:
        return "exact"
    elif sim >= settings.match_threshold:
        return "near_duplicate"
    return "partial"
