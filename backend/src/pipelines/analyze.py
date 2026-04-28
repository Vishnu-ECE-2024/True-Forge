"""
Full analysis pipeline: pHash + DL embedding + audio + FAISS search
+ multi-modal fusion + decision engine + tamper detection.

Used by POST /api/analyze (transient video — not stored in library).
"""

import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from src.core.config import settings
from src.core.models import AssetStatus
from src.db.database import get_db_session
from src.db.models import Asset
from src.fingerprint.audio import compare_audio_fingerprints, compute_audio_fingerprint
from src.fingerprint.visual import (
    cleanup_frames,
    compute_visual_fingerprint,
    extract_frames,
    get_video_duration,
)
from src.integrity.tamper import analyze_tamper
from src.search.faiss_index import FaissIndex
from src.services.decision import DecisionResult, make_decision
from src.services.fusion import FusionScore, compute_fusion_score

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    asset_id: str
    filename: str
    duration_seconds: Optional[float]
    fusion: FusionScore
    decision: DecisionResult
    phash_sim: float
    dl_sim: Optional[float]
    audio_sim: Optional[float]

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "filename": self.filename,
            "duration_seconds": self.duration_seconds,
            "fusion_score": {
                "final_score": self.fusion.final_score,
                "method": self.fusion.method,
                "breakdown": self.fusion.breakdown,
            },
            "decision": self.decision.to_dict(),
            "raw_scores": {
                "phash": round(self.phash_sim, 4),
                "dl_embedding": round(self.dl_sim, 4) if self.dl_sim is not None else None,
                "audio": round(self.audio_sim, 4) if self.audio_sim is not None else None,
            },
        }


@dataclass
class AnalysisReport:
    processing_time_ms: float
    duration_seconds: float
    frame_count: int
    fingerprints: dict
    tamper: dict
    matches: list[MatchResult] = field(default_factory=list)
    total_candidates: int = 0
    top_verdict: str = "NO_MATCH"

    def to_dict(self) -> dict:
        return {
            "processing_time_ms": round(self.processing_time_ms, 1),
            "video_info": {
                "duration_seconds": self.duration_seconds,
                "frame_count": self.frame_count,
            },
            "fingerprints": self.fingerprints,
            "tamper_analysis": self.tamper,
            "matches": [m.to_dict() for m in self.matches],
            "total_candidates_checked": self.total_candidates,
            "top_verdict": self.top_verdict,
        }


def run_analysis(
    video_path: Path,
    faiss_index: FaissIndex,
    dl_index: Optional[FaissIndex] = None,
    run_tamper: bool = True,
) -> AnalysisReport:
    """
    Run the complete detection pipeline on a video file (not stored in library).

    Args:
        video_path:   Path to the video to analyse.
        faiss_index:  pHash FAISS index.
        dl_index:     DL embedding FAISS index (optional).
        run_tamper:   Whether to run tamper analysis (slower; skip for speed tests).

    Returns:
        AnalysisReport with matches, fusion scores, decisions, and tamper info.
    """
    t0 = time.perf_counter()
    asset_tmp_id = f"analyze_{hash(str(video_path)) % 1_000_000}"

    duration      = get_video_duration(video_path)
    frame_paths   = extract_frames(video_path, asset_tmp_id)
    frame_count   = len(frame_paths)

    visual_fp: Optional[np.ndarray] = None
    dl_emb:    Optional[np.ndarray] = None

    try:
        visual_fp = compute_visual_fingerprint(frame_paths) if frame_paths else None

        if dl_index is not None:
            try:
                from src.services.embedding import get_embedding_model
                model = get_embedding_model()
                if model.available and frame_paths:
                    dl_emb = model.embed_frames(
                        frame_paths, max_frames=settings.dl_max_frames
                    )
            except Exception as e:
                logger.debug(f"DL embedding failed: {e}")
    finally:
        cleanup_frames(asset_tmp_id)

    audio_fp = compute_audio_fingerprint(video_path, asset_tmp_id)

    fingerprints_meta = {
        "phash_computed": visual_fp is not None,
        "dl_embedding_computed": dl_emb is not None,
        "audio_computed": audio_fp is not None,
    }

    # Tamper analysis
    tamper_result: dict = {}
    if run_tamper:
        try:
            tamper_result = analyze_tamper(video_path)
        except Exception as e:
            logger.warning(f"Tamper analysis failed: {e}")
            tamper_result = {"tamper_score": 0.0, "flags": [], "error": str(e)}
    else:
        tamper_result = {"tamper_score": 0.0, "flags": [], "skipped": True}

    tamper_score = tamper_result.get("tamper_score", 0.0)

    # FAISS search
    phash_by_id: dict = {}
    dl_by_id:    dict = {}

    if visual_fp is not None and faiss_index.total_vectors > 0:
        hits = faiss_index.search(visual_fp, top_k=20)
        phash_by_id = {h.asset_id: h.similarity for h in hits if h.asset_id}

    if dl_emb is not None and dl_index is not None and dl_index.total_vectors > 0:
        dl_hits = dl_index.search(dl_emb, top_k=20)
        dl_by_id = {h.asset_id: h.similarity for h in dl_hits if h.asset_id}

    all_ids = set(phash_by_id.keys()) | set(dl_by_id.keys())
    total_candidates = len(all_ids)

    matches: list[MatchResult] = []

    with get_db_session() as db:
        for candidate_id in all_ids:
            asset = db.get(Asset, candidate_id)
            if asset is None or asset.status != AssetStatus.READY:
                continue

            phash_sim = phash_by_id.get(candidate_id, 0.0)
            dl_sim    = dl_by_id.get(candidate_id)

            audio_sim: Optional[float] = None
            if audio_fp and asset.audio_fingerprint:
                audio_sim = compare_audio_fingerprints(audio_fp, asset.audio_fingerprint)

            fusion = compute_fusion_score(phash_sim, dl_sim, audio_sim)

            if fusion.final_score < settings.match_threshold * 0.4:
                continue

            decision = make_decision(
                fusion_score=fusion.final_score,
                phash_sim=phash_sim,
                dl_sim=dl_sim,
                audio_sim=audio_sim,
                match_threshold=settings.match_threshold,
                tamper_score=tamper_score,
            )

            matches.append(MatchResult(
                asset_id=asset.asset_id,
                filename=asset.original_filename,
                duration_seconds=asset.duration_seconds,
                fusion=fusion,
                decision=decision,
                phash_sim=phash_sim,
                dl_sim=dl_sim,
                audio_sim=audio_sim,
            ))

    matches.sort(key=lambda m: m.fusion.final_score, reverse=True)

    # Determine top verdict
    top_verdict = "NO_MATCH"
    if matches:
        top_verdict = matches[0].decision.verdict.value

    elapsed_ms = (time.perf_counter() - t0) * 1000

    return AnalysisReport(
        processing_time_ms=elapsed_ms,
        duration_seconds=duration,
        frame_count=frame_count,
        fingerprints=fingerprints_meta,
        tamper=tamper_result,
        matches=matches,
        total_candidates=total_candidates,
        top_verdict=top_verdict,
    )
