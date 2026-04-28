"""
Full pipeline analysis endpoint.

POST /api/analyze  — Run complete detection on an uploaded video (not stored).

Returns fingerprint info, tamper analysis, all matches with fusion scores
and decision engine verdicts.
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

from src.core.config import settings
from src.db.database import get_db
from src.pipelines.analyze import run_analysis
from src.search.faiss_index import FaissIndex

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyze")

ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv"}


@router.post("")
async def analyze_video(
    request: Request,
    file: UploadFile,
    run_tamper: bool = Query(True, description="Run tamper detection (slower)"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Upload a video and run the full detection pipeline.

    The video is **not stored** in the library. Use this to:
    - Check whether a suspected copy matches any registered original
    - Get a complete multi-modal similarity breakdown
    - Get a tamper analysis of the submitted video

    Returns a structured report with:
    - Per-modality scores (pHash, DL embedding, audio)
    - Fusion score and decision (MATCH / POSSIBLE_MATCH / NO_MATCH)
    - Tamper flags (letterbox, overlay, frame differences, etc.)
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'")

    faiss_index: FaissIndex = request.app.state.faiss_index
    dl_index: Optional[FaissIndex] = getattr(request.app.state, "dl_index", None)

    if faiss_index.total_vectors == 0:
        return {
            "message": "No assets registered yet. Upload originals first.",
            "matches": [],
            "total_candidates_checked": 0,
            "top_verdict": "NO_MATCH",
        }

    max_bytes = settings.max_video_size_mb * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.max_video_size_mb}MB limit",
        )
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(content)

    try:
        report = run_analysis(
            video_path=tmp_path,
            faiss_index=faiss_index,
            dl_index=dl_index,
            run_tamper=run_tamper,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    result = report.to_dict()
    result["query_filename"] = file.filename
    logger.info(
        f"Analysis: {len(report.matches)} matches, verdict={report.top_verdict}, "
        f"time={report.processing_time_ms:.0f}ms"
    )
    return result
