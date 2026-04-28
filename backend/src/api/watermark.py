"""
Phase 2: Watermark embed and detection endpoints.

POST /api/watermark/{asset_id}/embed   — embed watermark into stored original
POST /api/watermark/detect             — detect watermark in uploaded video
GET  /api/watermark/{asset_id}         — check watermark status for an asset
"""

import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.models import AssetStatus
from src.db.database import get_db
from src.db.models import Asset, WatermarkRecord

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/watermark")


class WatermarkEmbedResponse(BaseModel):
    asset_id: str
    output_path: str
    method: str
    message: str


class WatermarkDetectResponse(BaseModel):
    detected: bool
    asset_id: str | None
    confidence: float
    frames_checked: int
    message: str


class WatermarkStatusResponse(BaseModel):
    asset_id: str
    watermark_embedded: bool
    records: list[dict]


def _do_embed(asset_id: str, video_path: Path, record_id: str) -> None:
    """Background task: embed watermark and update DB."""
    from src.watermark.dct import embed_watermark_video, embed_watermark_in_image
    from src.fingerprint.visual import IMAGE_EXTENSIONS
    from src.db.database import get_db_session

    is_image = video_path.suffix.lower() in IMAGE_EXTENSIONS
    if is_image:
        suffix = video_path.suffix.lower()
        output_path = settings.originals_dir / asset_id / f"watermarked{suffix}"
    else:
        output_path = settings.originals_dir / asset_id / "watermarked.mp4"

    try:
        if is_image:
            embed_watermark_in_image(video_path, output_path, asset_id)
        else:
            embed_watermark_video(video_path, output_path, asset_id)

        with get_db_session() as db:
            record = db.get(WatermarkRecord, record_id)
            if record:
                record.output_path = str(output_path)

            asset = db.get(Asset, asset_id)
            if asset:
                asset.watermark_embedded = True

        logger.info(f"Watermark embedded for {asset_id} → {output_path}")

    except Exception as e:
        logger.error(f"Watermark embed failed for {asset_id}: {e}", exc_info=True)
        with get_db_session() as db:
            record = db.get(WatermarkRecord, record_id)
            if record:
                db.delete(record)


@router.post("/{asset_id}/embed", response_model=WatermarkEmbedResponse)
def embed_watermark(
    asset_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> WatermarkEmbedResponse:
    """
    Embed an invisible DCT watermark into the stored original video.
    The watermark encodes the asset_id — detectable even after re-encoding.
    A new file is created (original is never modified).
    """
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    if asset.status != AssetStatus.READY:
        raise HTTPException(status_code=409, detail=f"Asset not ready (status={asset.status})")

    # Find the original video file
    asset_dir = settings.originals_dir / asset_id
    video_files = list(asset_dir.glob("original.*"))
    if not video_files:
        raise HTTPException(status_code=404, detail="Original video file not found on disk")
    video_path = video_files[0]

    output_path = settings.originals_dir / asset_id / "watermarked.mp4"
    record_id = str(uuid.uuid4())

    record = WatermarkRecord(
        record_id=record_id,
        asset_id=asset_id,
        output_path=str(output_path),
        method="dwtDct",
    )
    db.add(record)
    db.commit()

    background_tasks.add_task(_do_embed, asset_id, video_path, record_id)

    return WatermarkEmbedResponse(
        asset_id=asset_id,
        output_path=str(output_path),
        method="dwtDct",
        message="Watermark embedding queued. Check status in a few minutes.",
    )


@router.post("/detect", response_model=WatermarkDetectResponse)
async def detect_watermark(
    file: UploadFile,
    db: Session = Depends(get_db),
) -> WatermarkDetectResponse:
    """
    Upload a video to check if it contains one of our registered watermarks.
    Checks against all assets with watermark_embedded=True.
    """
    known_assets = db.query(Asset).filter(Asset.watermark_embedded == True).all()  # noqa: E712
    if not known_assets:
        return WatermarkDetectResponse(
            detected=False,
            asset_id=None,
            confidence=0.0,
            frames_checked=0,
            message="No watermarked assets registered yet.",
        )

    known_ids = [a.asset_id for a in known_assets]
    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"

    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(content)

    try:
        from src.fingerprint.visual import IMAGE_EXTENSIONS
        from src.watermark.dct import detect_watermark_in_video, detect_watermark_in_image
        if ext in IMAGE_EXTENSIONS:
            result = detect_watermark_in_image(tmp_path, known_ids)
        else:
            result = detect_watermark_in_video(tmp_path, known_ids)
    finally:
        tmp_path.unlink(missing_ok=True)

    msg = (
        f"Watermark detected: asset {result['asset_id']} "
        f"(confidence={result['confidence']:.1%})"
        if result["detected"]
        else "No registered watermark detected."
    )

    return WatermarkDetectResponse(
        detected=result["detected"],
        asset_id=result["asset_id"],
        confidence=result["confidence"],
        frames_checked=result["frames_checked"],
        message=msg,
    )


@router.get("/{asset_id}", response_model=WatermarkStatusResponse)
def watermark_status(asset_id: str, db: Session = Depends(get_db)) -> WatermarkStatusResponse:
    """Get watermark status for an asset."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    records = db.query(WatermarkRecord).filter(WatermarkRecord.asset_id == asset_id).all()

    return WatermarkStatusResponse(
        asset_id=asset_id,
        watermark_embedded=bool(asset.watermark_embedded),
        records=[
            {"record_id": r.record_id, "method": r.method, "created_at": r.created_at.isoformat()}
            for r in records
        ],
    )


@router.get("/{asset_id}/download")
def download_watermarked(asset_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """Download the watermarked copy of an asset."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    asset_dir = settings.originals_dir / asset_id
    wm_files = list(asset_dir.glob("watermarked.*"))
    if not wm_files:
        raise HTTPException(status_code=404, detail="No watermarked file found. Embed watermark first.")

    wm_path = wm_files[0]
    stem = Path(asset.original_filename).stem
    download_name = f"{stem}_watermarked{wm_path.suffix}"
    return FileResponse(
        path=str(wm_path),
        filename=download_name,
        media_type="application/octet-stream",
    )
