"""
Fingerprint search endpoints.

POST /api/search/upload  — Upload a video, search for matches (not stored)
POST /api/search/asset/{id} — Search using an already-stored asset

Uses multi-modal fusion scoring (pHash + DL embedding + audio) when signals
are available. Falls back to pHash-only if DL index is absent.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.models import AssetStatus, SearchResponse, SearchResult
from src.db.database import get_db
from src.db.models import Asset
from src.fingerprint.audio import compare_audio_fingerprints, compute_audio_fingerprint
from src.fingerprint.visual import (
    IMAGE_EXTENSIONS,
    cleanup_frames,
    compute_visual_fingerprint,
    extract_frames,
    hash_image_directly,
)
from src.search.faiss_index import FaissIndex
from src.services.decision import make_decision
from src.services.fusion import compute_fusion_score

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search")

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv"}
ALLOWED_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS


def _classify_match(similarity: float) -> str:
    if similarity >= 0.97:
        return "exact"
    elif similarity >= settings.match_threshold:
        return "near_duplicate"
    return "partial"


def _compute_dl_similarity(
    query_dl_emb: Optional[object],
    asset_dl_row: Optional[int],
    dl_index: Optional[FaissIndex],
) -> Optional[float]:
    """Look up DL similarity for one candidate asset."""
    if query_dl_emb is None or asset_dl_row is None or dl_index is None:
        return None
    try:
        asset_vec = dl_index.get_vector(asset_dl_row)
        import numpy as np
        # Cosine similarity for L2-normalised vectors = dot product
        sim = float(np.dot(query_dl_emb, asset_vec))
        return round(max(0.0, sim), 4)
    except Exception:
        return None


def _search_by_fingerprint(
    video_path: Path,
    faiss_index: FaissIndex,
    dl_index: Optional[FaissIndex],
    db: Session,
    tmp_asset_id: str = "query",
    run_gemini: bool = False,
) -> tuple[list[SearchResult], int, Optional[dict]]:
    """
    Core search logic: fingerprint a video and search both indices.
    Returns (results, total_candidates_checked, query_gemini_analysis).
    """
    # Extract frames
    frame_paths = extract_frames(video_path, tmp_asset_id)
    if not frame_paths:
        raise HTTPException(status_code=422, detail="Could not extract frames")

    query_dl_emb = None
    query_gemini: Optional[dict] = None
    try:
        visual_fp = compute_visual_fingerprint(frame_paths)

        # Compute DL embedding before cleanup (needs frame files)
        if dl_index is not None and dl_index.total_vectors > 0:
            try:
                from src.services.embedding import get_embedding_model
                model = get_embedding_model()
                if model.available:
                    query_dl_emb = model.embed_frames(
                        frame_paths, max_frames=settings.dl_max_frames
                    )
            except Exception as e:
                logger.debug(f"DL embedding for query failed: {e}")

        # Gemini AI analysis of the query video (what sport/content is this?)
        if run_gemini:
            try:
                from src.services.gemini_service import analyze_frames_batch
                query_gemini = analyze_frames_batch(frame_paths, sample_every_n=3)
            except Exception as e:
                logger.debug(f"Gemini query analysis failed: {e}")
    finally:
        cleanup_frames(tmp_asset_id)

    audio_fp = compute_audio_fingerprint(video_path, tmp_asset_id)

    # Search pHash FAISS (primary)
    phash_hits = faiss_index.search(visual_fp, top_k=20)
    phash_by_id = {h.asset_id: h for h in phash_hits}

    # Search DL FAISS (secondary — expands candidate set)
    dl_sim_by_id: dict[str, float] = {}
    if query_dl_emb is not None and dl_index is not None and dl_index.total_vectors > 0:
        dl_hits = dl_index.search(query_dl_emb, top_k=20)
        dl_sim_by_id = {h.asset_id: h.similarity for h in dl_hits}

    # Union of candidates
    all_candidate_ids = set(phash_by_id.keys()) | set(dl_sim_by_id.keys())
    total_candidates = len(all_candidate_ids)

    results: list[SearchResult] = []
    for candidate_id in all_candidate_ids:
        if not candidate_id:
            continue

        asset = db.get(Asset, candidate_id)
        if asset is None or asset.status != AssetStatus.READY:
            continue

        phash_sim  = phash_by_id.get(candidate_id, None)
        phash_score = phash_sim.similarity if phash_sim else 0.0
        dl_score    = dl_sim_by_id.get(candidate_id)

        audio_score: Optional[float] = None
        if audio_fp and asset.audio_fingerprint:
            audio_score = compare_audio_fingerprints(audio_fp, asset.audio_fingerprint)

        fusion = compute_fusion_score(phash_score, dl_score, audio_score)
        decision = make_decision(
            fusion_score=fusion.final_score,
            phash_sim=phash_score,
            dl_sim=dl_score,
            audio_sim=audio_score,
            match_threshold=settings.match_threshold,
        )

        # Only include meaningful candidates
        if fusion.final_score < settings.match_threshold * 0.45:
            continue

        gemini_meta = None
        if asset.gemini_metadata:
            import json as json_module
            try:
                gemini_meta = json_module.loads(asset.gemini_metadata)
            except Exception:
                pass

        results.append(SearchResult(
            asset_id=asset.asset_id,
            filename=asset.original_filename,
            similarity_score=fusion.final_score,
            match_type=_classify_match(fusion.final_score),
            duration_seconds=asset.duration_seconds,
            created_at=asset.created_at,
            verdict=decision.verdict.value,
            confidence=decision.confidence,
            score_breakdown=fusion.breakdown,
            gemini_metadata=gemini_meta,
        ))

    results.sort(key=lambda r: r.similarity_score, reverse=True)
    return results, total_candidates, query_gemini


def _search_by_image_fingerprint(
    image_path: Path,
    faiss_index: FaissIndex,
    dl_index: Optional[FaissIndex],
    db: Session,
) -> tuple[list[SearchResult], int]:
    """Search by computing pHash directly from an image (no frame extraction)."""
    visual_fp = hash_image_directly(image_path)
    phash_hits = faiss_index.search(visual_fp, top_k=20)

    results: list[SearchResult] = []
    for hit in phash_hits:
        if not hit.asset_id:
            continue
        asset = db.get(Asset, hit.asset_id)
        if asset is None or asset.status != AssetStatus.READY:
            continue
        fusion = compute_fusion_score(hit.similarity, None, None)
        decision = make_decision(
            fusion_score=fusion.final_score,
            phash_sim=hit.similarity,
            dl_sim=None,
            audio_sim=None,
            match_threshold=settings.match_threshold,
        )
        if fusion.final_score < settings.match_threshold * 0.45:
            continue
        results.append(SearchResult(
            asset_id=asset.asset_id,
            filename=asset.original_filename,
            similarity_score=fusion.final_score,
            match_type=_classify_match(fusion.final_score),
            duration_seconds=asset.duration_seconds,
            created_at=asset.created_at,
            verdict=decision.verdict.value,
            confidence=decision.confidence,
            score_breakdown=fusion.breakdown,
        ))

    results.sort(key=lambda r: r.similarity_score, reverse=True)
    return results, len(phash_hits)


@router.post("/upload", response_model=SearchResponse)
async def search_by_upload(
    request: Request,
    file: UploadFile,
    db: Session = Depends(get_db),
) -> SearchResponse:
    """
    Upload a video to search for matches. The video is NOT stored.
    Use this to check if a suspected infringing copy matches any original.
    """
    import tempfile

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'")

    faiss_index: FaissIndex = request.app.state.faiss_index
    dl_index: Optional[FaissIndex] = getattr(request.app.state, "dl_index", None)

    if faiss_index.total_vectors == 0:
        return SearchResponse(
            query_asset_id=None,
            results=[],
            total_candidates=0,
            processing_time_ms=0.0,
        )

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

    start_time = time.perf_counter()
    try:
        if ext in IMAGE_EXTENSIONS:
            results, total_candidates = _search_by_image_fingerprint(
                tmp_path, faiss_index, dl_index, db
            )
            query_gemini = None
        else:
            results, total_candidates, query_gemini = _search_by_fingerprint(
                tmp_path, faiss_index, dl_index, db, tmp_asset_id="query_tmp", run_gemini=True
            )
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        logger.exception(f"Search pipeline error: {exc}")
        raise HTTPException(status_code=500, detail=f"Search failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        f"Search: {len(results)} matches / {total_candidates} candidates "
        f"in {elapsed_ms:.0f}ms"
    )

    return SearchResponse(
        query_asset_id=None,
        results=results,
        total_candidates=total_candidates,
        processing_time_ms=round(elapsed_ms, 1),
        query_gemini_analysis=query_gemini,
    )


@router.post("/asset/{asset_id}", response_model=SearchResponse)
def search_by_asset(
    asset_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> SearchResponse:
    """
    Search for matches to an already-stored asset using its stored fingerprints.
    """
    faiss_index: FaissIndex = request.app.state.faiss_index
    dl_index: Optional[FaissIndex] = getattr(request.app.state, "dl_index", None)

    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    if asset.status != AssetStatus.READY:
        raise HTTPException(
            status_code=409, detail=f"Asset not ready (status={asset.status})"
        )
    if asset.faiss_row_id is None:
        raise HTTPException(status_code=422, detail="Asset has no FAISS entry")

    start_time = time.perf_counter()

    vector = faiss_index.get_vector(asset.faiss_row_id)
    phash_hits = faiss_index.search(vector, top_k=20)
    phash_by_id = {h.asset_id: h for h in phash_hits}

    # DL search for the stored asset
    dl_sim_by_id: dict[str, float] = {}
    if dl_index is not None and asset.dl_faiss_row_id is not None:
        try:
            dl_vec = dl_index.get_vector(asset.dl_faiss_row_id)
            dl_hits = dl_index.search(dl_vec, top_k=20)
            dl_sim_by_id = {h.asset_id: h.similarity for h in dl_hits}
        except Exception as e:
            logger.debug(f"DL search for asset {asset_id}: {e}")

    all_ids = (set(phash_by_id.keys()) | set(dl_sim_by_id.keys())) - {asset_id}

    results: list[SearchResult] = []
    for cid in all_ids:
        if not cid:
            continue
        matched = db.get(Asset, cid)
        if matched is None or matched.status != AssetStatus.READY:
            continue

        phash_score = phash_by_id.get(cid, None)
        phash_sim   = phash_score.similarity if phash_score else 0.0
        dl_score    = dl_sim_by_id.get(cid)

        audio_score: Optional[float] = None
        if asset.audio_fingerprint and matched.audio_fingerprint:
            audio_score = compare_audio_fingerprints(
                asset.audio_fingerprint, matched.audio_fingerprint
            )

        fusion   = compute_fusion_score(phash_sim, dl_score, audio_score)
        decision = make_decision(
            fusion_score=fusion.final_score,
            phash_sim=phash_sim,
            dl_sim=dl_score,
            audio_sim=audio_score,
            match_threshold=settings.match_threshold,
        )

        gemini_meta = None
        if matched.gemini_metadata:
            import json as json_module
            try:
                gemini_meta = json_module.loads(matched.gemini_metadata)
            except Exception:
                pass

        results.append(SearchResult(
            asset_id=matched.asset_id,
            filename=matched.original_filename,
            similarity_score=fusion.final_score,
            match_type=_classify_match(fusion.final_score),
            duration_seconds=matched.duration_seconds,
            created_at=matched.created_at,
            verdict=decision.verdict.value,
            confidence=decision.confidence,
            score_breakdown=fusion.breakdown,
            gemini_metadata=gemini_meta,
        ))

    results.sort(key=lambda r: r.similarity_score, reverse=True)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    return SearchResponse(
        query_asset_id=asset_id,
        results=results,
        total_candidates=len(phash_hits),
        processing_time_ms=round(elapsed_ms, 1),
    )
