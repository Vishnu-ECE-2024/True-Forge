"""
Monitoring simulation / batch ingest layer.

POST /api/ingest/batch  — Submit a list of URLs or local file paths for
                          detection pipeline simulation. Treats each item
                          as "external content" and runs full fingerprint +
                          search + fusion + decision without storing anything.

Use this to:
  - Test the detection pipeline with known copies before going live
  - Simulate how external ingestion would look at scale
  - Batch-check a list of URLs quickly
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import settings
from src.db.database import get_db
from src.pipelines.analyze import AnalysisReport, run_analysis
from src.search.faiss_index import FaissIndex

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest")


class IngestItem(BaseModel):
    source: str   # URL (https://...) or local path (file:///path/to/video.mp4)
    label: str = ""


class BatchIngestRequest(BaseModel):
    items: list[IngestItem]
    run_tamper: bool = False   # skip tamper for speed in batch mode


class ItemResult(BaseModel):
    source: str
    label: str
    status: str              # "matched" | "no_match" | "error"
    top_verdict: str
    top_match_asset_id: Optional[str] = None
    top_match_filename: Optional[str] = None
    top_match_score: Optional[float] = None
    matches_found: int
    processing_time_ms: float
    error: Optional[str] = None


class BatchIngestResponse(BaseModel):
    total_items: int
    processed: int
    matched: int
    no_match: int
    errors: int
    results: list[ItemResult]


def _process_one(
    source: str,
    label: str,
    faiss_index: FaissIndex,
    dl_index: Optional[FaissIndex],
    run_tamper: bool,
) -> ItemResult:
    """Download (if URL) or read local file, run analysis, return result."""
    video_path: Optional[Path] = None
    tmp_created = False

    try:
        if source.startswith("file://"):
            local_path = source[7:]
            video_path = Path(local_path)
            if not video_path.exists():
                return ItemResult(
                    source=source, label=label,
                    status="error", top_verdict="NO_MATCH",
                    matches_found=0, processing_time_ms=0.0,
                    error=f"File not found: {local_path}",
                )
        elif source.startswith(("http://", "https://")):
            from src.monitor.downloader import download_video
            with tempfile.TemporaryDirectory() as tmp_dir:
                result = download_video(source, Path(tmp_dir))
                if not result.success or result.video_path is None:
                    return ItemResult(
                        source=source, label=label,
                        status="error", top_verdict="NO_MATCH",
                        matches_found=0, processing_time_ms=0.0,
                        error=result.error or "Download failed",
                    )
                # Copy out of temp dir before it's cleaned up
                import shutil
                ext = result.video_path.suffix
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                    video_path = Path(f.name)
                shutil.copy2(str(result.video_path), str(video_path))
                tmp_created = True
        else:
            return ItemResult(
                source=source, label=label,
                status="error", top_verdict="NO_MATCH",
                matches_found=0, processing_time_ms=0.0,
                error="Source must start with http://, https://, or file://",
            )

        report: AnalysisReport = run_analysis(
            video_path=video_path,
            faiss_index=faiss_index,
            dl_index=dl_index,
            run_tamper=run_tamper,
        )

        top_match = report.matches[0] if report.matches else None
        status = "matched" if report.top_verdict in ("MATCH", "POSSIBLE_MATCH") else "no_match"

        return ItemResult(
            source=source,
            label=label,
            status=status,
            top_verdict=report.top_verdict,
            top_match_asset_id=top_match.asset_id if top_match else None,
            top_match_filename=top_match.filename if top_match else None,
            top_match_score=top_match.fusion.final_score if top_match else None,
            matches_found=len(report.matches),
            processing_time_ms=round(report.processing_time_ms, 1),
        )

    except Exception as e:
        logger.error(f"Ingest item failed [{source}]: {e}", exc_info=True)
        return ItemResult(
            source=source, label=label,
            status="error", top_verdict="NO_MATCH",
            matches_found=0, processing_time_ms=0.0,
            error=str(e),
        )
    finally:
        if tmp_created and video_path and video_path.exists():
            video_path.unlink(missing_ok=True)


@router.post("/batch", response_model=BatchIngestResponse)
def batch_ingest(
    body: BatchIngestRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BatchIngestResponse:
    """
    Submit a batch of URLs or local file paths for detection simulation.

    Each item is treated as external content — downloaded/read, fingerprinted,
    and searched against the registered library. Nothing is stored.

    Max items per call: controlled by `batch_ingest_max_items` config (default 20).
    """
    max_items = settings.batch_ingest_max_items
    if len(body.items) > max_items:
        raise HTTPException(
            status_code=400,
            detail=f"Batch too large: {len(body.items)} items, max {max_items}",
        )

    faiss_index: FaissIndex = request.app.state.faiss_index
    dl_index: Optional[FaissIndex] = getattr(request.app.state, "dl_index", None)

    if faiss_index.total_vectors == 0:
        raise HTTPException(
            status_code=409,
            detail="No assets registered yet. Upload originals before running batch ingest.",
        )

    results: list[ItemResult] = []
    for item in body.items:
        r = _process_one(
            source=item.source,
            label=item.label,
            faiss_index=faiss_index,
            dl_index=dl_index,
            run_tamper=body.run_tamper,
        )
        results.append(r)
        logger.info(
            f"Ingest [{item.source[:60]}]: {r.status}, "
            f"verdict={r.top_verdict}, score={r.top_match_score}"
        )

    matched  = sum(1 for r in results if r.status == "matched")
    no_match = sum(1 for r in results if r.status == "no_match")
    errors   = sum(1 for r in results if r.status == "error")

    return BatchIngestResponse(
        total_items=len(body.items),
        processed=len(results),
        matched=matched,
        no_match=no_match,
        errors=errors,
        results=results,
    )
