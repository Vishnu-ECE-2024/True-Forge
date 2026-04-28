"""
Fingerprinting pipeline: orchestrates visual pHash + DL embedding + audio
extraction for an asset. Called as a FastAPI BackgroundTask after upload.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np

from src.core.config import settings
from src.core.models import AssetStatus
from src.db.database import get_db_session
from src.db.models import Asset
from src.fingerprint.audio import compute_audio_fingerprint
from src.fingerprint.visual import (
    cleanup_frames,
    compute_visual_fingerprint,
    extract_frames,
    get_video_duration,
    hash_image_directly,
)
from src.search.faiss_index import FaissIndex
from src.services.gemini_service import analyze_frames_batch

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def process_asset(
    asset_id: str,
    video_path: Path,
    faiss_index: FaissIndex,
    dl_index: Optional[FaissIndex] = None,
) -> None:
    """
    Full fingerprinting pipeline for one asset.
    Updates database status at each stage.
    Runs in a background thread (called via FastAPI BackgroundTasks).

    Steps:
      1. Duration probe
      2. Frame extraction
      3. pHash fingerprint → pHash FAISS index
      4. Gemini AI analysis (optional, if API key set)
      5. DL embedding (MobileNetV3-Small) → DL FAISS index (if available)
      6. Audio fingerprint (Chromaprint)
      7. Frame cleanup
      8. DB update
    """
    logger.info(f"Starting fingerprinting pipeline for asset {asset_id}")

    with get_db_session() as db:
        asset = db.get(Asset, asset_id)
        if asset is None:
            logger.error(f"Asset {asset_id} not found in DB")
            return
        asset.status = AssetStatus.PROCESSING
        db.commit()

    frame_paths: list[Path] = []

    try:
        # Step 1: Duration
        duration = get_video_duration(video_path)
        logger.info(f"Asset {asset_id}: duration={duration:.1f}s")

        # Step 2: Extract frames
        frame_paths = extract_frames(video_path, asset_id)
        if not frame_paths:
            raise RuntimeError(
                "No frames extracted — video may be corrupt or unsupported"
            )

        # Step 3: pHash visual fingerprint → FAISS
        visual_fp: np.ndarray = compute_visual_fingerprint(frame_paths)
        faiss_row_id = faiss_index.add(visual_fp, asset_id)

        # Step 4: Gemini AI analysis (optional, graceful fallback)
        gemini_metadata: Optional[dict] = None
        try:
            gemini_result = analyze_frames_batch(frame_paths, sample_every_n=5)
            if gemini_result:
                gemini_metadata = gemini_result
                logger.info(
                    f"Asset {asset_id}: Gemini analysis: "
                    f"{gemini_result.get('overall_classification')} "
                    f"({gemini_result.get('sport_type', 'unknown')}), "
                    f"confidence={gemini_result.get('confidence')}"
                )
        except Exception as e:
            logger.warning(f"Gemini analysis failed for {asset_id}: {e}")

        # Step 5: DL embedding (MobileNetV3-Small, optional)
        dl_faiss_row_id: Optional[int] = None
        if dl_index is not None:
            try:
                from src.services.embedding import get_embedding_model
                model = get_embedding_model()
                if model.available:
                    dl_emb = model.embed_frames(
                        frame_paths, max_frames=settings.dl_max_frames
                    )
                    if dl_emb is not None:
                        dl_faiss_row_id = dl_index.add(dl_emb, asset_id)
                        logger.info(
                            f"Asset {asset_id}: DL embedding stored at row {dl_faiss_row_id}"
                        )
            except Exception as e:
                logger.warning(f"DL embedding failed for {asset_id}: {e}")

        # Step 5: Audio fingerprint
        audio_fp = compute_audio_fingerprint(video_path, asset_id)

        # Step 6: Clean up frames
        cleanup_frames(asset_id)

        # Step 8: Persist results
        with get_db_session() as db:
            asset = db.get(Asset, asset_id)
            asset.status = AssetStatus.READY
            asset.duration_seconds = duration
            asset.frame_count = len(frame_paths)
            asset.faiss_row_id = faiss_row_id
            asset.dl_faiss_row_id = dl_faiss_row_id
            asset.audio_fingerprint = audio_fp
            asset.gemini_metadata = json.dumps(gemini_metadata) if gemini_metadata else None
            asset.processed_at = datetime.utcnow()
            db.commit()

        logger.info(
            f"Asset {asset_id} processed: {len(frame_paths)} frames, "
            f"pHash row={faiss_row_id}, DL row={dl_faiss_row_id}, "
            f"audio={'yes' if audio_fp else 'no'}"
        )

    except Exception as e:
        logger.error(f"Fingerprinting failed for {asset_id}: {e}", exc_info=True)
        with get_db_session() as db:
            asset = db.get(Asset, asset_id)
            if asset:
                asset.status = AssetStatus.FAILED
                asset.error_message = str(e)
        cleanup_frames(asset_id)


def process_image_asset(
    asset_id: str,
    image_path: Path,
    faiss_index: FaissIndex,
    dl_index: Optional[FaissIndex] = None,
) -> None:
    """
    Fingerprinting pipeline for image assets.
    Computes pHash directly — no FFmpeg frame extraction, no audio step.
    """
    logger.info(f"Starting image fingerprinting for asset {asset_id}")

    with get_db_session() as db:
        asset = db.get(Asset, asset_id)
        if asset is None:
            logger.error(f"Asset {asset_id} not found in DB")
            return
        asset.status = AssetStatus.PROCESSING
        db.commit()

    try:
        visual_fp = hash_image_directly(image_path)
        faiss_row_id = faiss_index.add(visual_fp, asset_id)

        with get_db_session() as db:
            asset = db.get(Asset, asset_id)
            asset.status = AssetStatus.READY
            asset.duration_seconds = None
            asset.frame_count = 1
            asset.faiss_row_id = faiss_row_id
            asset.dl_faiss_row_id = None
            asset.audio_fingerprint = None
            asset.processed_at = datetime.utcnow()
            db.commit()

        logger.info(f"Image asset {asset_id} processed: pHash row={faiss_row_id}")

    except Exception as e:
        logger.error(f"Image fingerprinting failed for {asset_id}: {e}", exc_info=True)
        with get_db_session() as db:
            asset = db.get(Asset, asset_id)
            if asset:
                asset.status = AssetStatus.FAILED
                asset.error_message = str(e)
