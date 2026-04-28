"""
Asset management endpoints.

POST /api/assets/upload  — Upload a video, trigger fingerprinting
GET  /api/assets/        — List all assets
GET  /api/assets/{id}    — Get asset details
DELETE /api/assets/{id}  — Delete asset
"""

import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.models import AssetDetail, AssetListItem, AssetStatus, AssetUploadResponse
from src.db.database import get_db
from src.db.models import Asset
from src.fingerprint.pipeline import process_asset, process_image_asset
from src.fingerprint.visual import IMAGE_EXTENSIONS
from src.storage.local import compute_sha256, delete_asset, save_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/assets")

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv"}
ALLOWED_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS


@router.post("/upload", response_model=AssetUploadResponse)
async def upload_asset(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    db: Session = Depends(get_db),
) -> AssetUploadResponse:
    """
    Upload a video file and queue fingerprinting.

    - Validates file extension and size
    - Computes SHA256 to detect exact duplicates before processing
    - Saves to data/originals/{asset_id}/
    - Queues fingerprinting as background task
    - Returns immediately with asset_id and status=pending
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Stream to temp file (avoids loading entire video into memory)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        total_bytes = 0
        max_bytes = settings.max_video_size_mb * 1024 * 1024

        while True:
            chunk = await file.read(1024 * 1024)  # 1MB chunks
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds {settings.max_video_size_mb}MB limit"
                )
            tmp.write(chunk)

    # Check for exact duplicates via SHA256
    sha256 = compute_sha256(tmp_path)
    existing = db.query(Asset).filter(Asset.sha256 == sha256).first()
    if existing:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail=f"Exact duplicate: asset {existing.asset_id} already exists with this content"
        )

    # Create asset record
    asset_id = str(uuid.uuid4())
    video_path = save_upload(tmp_path, asset_id, file.filename)

    asset = Asset(
        asset_id=asset_id,
        filename=video_path.name,
        original_filename=file.filename,
        status=AssetStatus.PENDING,
        file_size_bytes=total_bytes,
        sha256=sha256,
    )
    db.add(asset)
    db.commit()

    # Queue fingerprinting (runs after response is sent)
    faiss_index = request.app.state.faiss_index
    dl_index    = getattr(request.app.state, "dl_index", None)
    if ext in IMAGE_EXTENSIONS:
        background_tasks.add_task(process_image_asset, asset_id, video_path, faiss_index, dl_index)
    else:
        background_tasks.add_task(process_asset, asset_id, video_path, faiss_index, dl_index)

    logger.info(f"Uploaded asset {asset_id} ({file.filename}, {total_bytes} bytes)")

    return AssetUploadResponse(
        asset_id=asset_id,
        filename=file.filename,
        status=AssetStatus.PENDING,
        message="Upload successful. Fingerprinting queued.",
    )


@router.get("/", response_model=list[AssetListItem])
def list_assets(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[AssetListItem]:
    """List all assets, newest first."""
    assets = (
        db.query(Asset)
        .order_by(Asset.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    import json as _json
    result = []
    for a in assets:
        gm = None
        if a.gemini_metadata:
            try:
                gm = _json.loads(a.gemini_metadata)
            except Exception:
                pass
        result.append(AssetListItem(
            asset_id=a.asset_id,
            filename=a.original_filename,
            status=a.status,
            duration_seconds=a.duration_seconds,
            created_at=a.created_at,
            gemini_metadata=gm,
        ))
    return result


@router.get("/{asset_id}", response_model=AssetDetail)
def get_asset(asset_id: str, db: Session = Depends(get_db)) -> AssetDetail:
    """Get full details for one asset."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    import json as _json
    gm = None
    if asset.gemini_metadata:
        try:
            gm = _json.loads(asset.gemini_metadata)
        except Exception:
            pass

    return AssetDetail(
        asset_id=asset.asset_id,
        filename=asset.original_filename,
        original_filename=asset.original_filename,
        status=asset.status,
        file_size_bytes=asset.file_size_bytes,
        duration_seconds=asset.duration_seconds,
        frame_count=asset.frame_count,
        sha256=asset.sha256,
        created_at=asset.created_at,
        processed_at=asset.processed_at,
        gemini_metadata=gm,
    )


@router.delete("/{asset_id}", status_code=204)
def delete_asset_endpoint(
    asset_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """Delete an asset and all associated files."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    if asset.faiss_row_id is not None:
        request.app.state.faiss_index.remove(asset.faiss_row_id)

    delete_asset(asset_id)
    db.delete(asset)
    db.commit()
    logger.info(f"Deleted asset {asset_id}")
