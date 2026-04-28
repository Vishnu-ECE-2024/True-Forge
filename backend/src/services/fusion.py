"""
Multi-modal fusion scoring engine.

Combines pHash visual similarity, deep-learning embedding similarity,
and audio fingerprint similarity into a single confidence score
with a per-modality breakdown for explainability.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ModalityScore:
    name: str
    score: float      # 0.0 – 1.0
    weight: float     # contribution weight applied
    available: bool   # was this modality actually computed?


@dataclass
class FusionScore:
    final_score: float               # weighted composite 0.0 – 1.0
    modalities: list[ModalityScore]  # per-modality breakdown
    method: str                      # "full" | "phash_dl" | "phash_audio" | "phash_only"

    @property
    def breakdown(self) -> dict:
        return {
            m.name: {
                "score": round(m.score, 4),
                "weight": m.weight,
                "available": m.available,
            }
            for m in self.modalities
        }


def compute_fusion_score(
    phash_sim: float,
    dl_sim: Optional[float] = None,
    audio_sim: Optional[float] = None,
) -> FusionScore:
    """
    Compute weighted fusion score from available modality scores.

    Weight allocation when all three signals available:
      pHash visual:      0.35
      DL embedding:      0.40   (semantic similarity — more robust than pHash)
      Audio fingerprint: 0.25

    Degrades gracefully when signals are absent:
      DL unavailable  → pHash 0.70,  Audio 0.30  (legacy behavior)
      Audio unavailable → pHash 0.50, DL 0.50
      Both absent     → pHash 1.00
    """
    has_dl = dl_sim is not None
    has_audio = audio_sim is not None

    if has_dl and has_audio:
        w = {"phash": 0.35, "dl": 0.40, "audio": 0.25}
        method = "full"
    elif has_dl:
        w = {"phash": 0.50, "dl": 0.50, "audio": 0.0}
        method = "phash_dl"
    elif has_audio:
        w = {"phash": 0.70, "dl": 0.0, "audio": 0.30}
        method = "phash_audio"
    else:
        w = {"phash": 1.0, "dl": 0.0, "audio": 0.0}
        method = "phash_only"

    final = (
        w["phash"] * phash_sim
        + w["dl"] * (dl_sim or 0.0)
        + w["audio"] * (audio_sim or 0.0)
    )

    modalities = [
        ModalityScore("phash",    phash_sim,          w["phash"],  True),
        ModalityScore("dl_embed", dl_sim or 0.0,      w["dl"],     has_dl),
        ModalityScore("audio",    audio_sim or 0.0,   w["audio"],  has_audio),
    ]

    return FusionScore(
        final_score=round(max(0.0, min(1.0, final)), 4),
        modalities=modalities,
        method=method,
    )
