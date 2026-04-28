"""
Rule-based + weighted decision engine.

Converts raw similarity scores into a human-readable verdict
(MATCH / POSSIBLE_MATCH / NO_MATCH) with confidence and explanation.

Rules are applied in priority order; first match wins.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Verdict(str, Enum):
    MATCH          = "MATCH"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    NO_MATCH       = "NO_MATCH"


@dataclass
class DecisionResult:
    verdict: Verdict
    confidence: float        # 0.0 – 1.0
    explanation: str
    rules_fired: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "explanation": self.explanation,
            "rules_fired": self.rules_fired,
        }


def make_decision(
    fusion_score: float,
    phash_sim: float,
    dl_sim: Optional[float],
    audio_sim: Optional[float],
    match_threshold: float = 0.85,
    tamper_score: float = 0.0,
) -> DecisionResult:
    """
    Apply rule-based decision logic over fusion and per-modality scores.

    Rule priority (first match wins):
      R1: Strong multi-modal                → MATCH  (highest confidence)
      R2: Exact pHash + strong audio        → MATCH
      R3: DL embedding + pHash both high    → MATCH
      R4: Fusion clearly above threshold    → MATCH
      R5: Fusion at threshold               → POSSIBLE_MATCH
      R6: pHash alone at threshold          → POSSIBLE_MATCH (weak signal)
      R7: Nothing qualifies                 → NO_MATCH

    Post-processing:
      TM: High tamper score downgrades MATCH → POSSIBLE_MATCH
    """
    rules_fired: list[str] = []

    audio_high   = audio_sim is not None and audio_sim >= 0.85
    audio_medium = audio_sim is not None and audio_sim >= 0.65
    dl_high      = dl_sim is not None and dl_sim >= 0.80
    dl_medium    = dl_sim is not None and dl_sim >= 0.65
    phash_exact  = phash_sim >= 0.97
    phash_high   = phash_sim >= 0.92
    phash_medium = phash_sim >= match_threshold

    # R1: Strong across all available modalities
    if fusion_score >= 0.92 and phash_high:
        rules_fired.append("R1:strong_multi_modal")
        verdict = Verdict.MATCH
        confidence = min(0.99, fusion_score)
        explanation = "Strong match across multiple fingerprint modalities."

    # R2: Exact pHash match + strong audio (reliable even without DL)
    elif phash_exact and audio_high:
        rules_fired.append("R2:exact_phash_audio")
        verdict = Verdict.MATCH
        confidence = min(0.98, (phash_sim + (audio_sim or 0.0)) / 2)
        explanation = "Visual pHash and audio fingerprint both match with high confidence."

    # R3: High DL embedding + medium pHash (semantic match)
    elif dl_high and phash_medium:
        rules_fired.append("R3:dl_phash_match")
        verdict = Verdict.MATCH
        confidence = fusion_score
        explanation = "Deep visual embedding and perceptual hash both indicate a match."

    # R4: Fusion clearly above threshold (good margin)
    elif fusion_score >= match_threshold + 0.05:
        rules_fired.append("R4:fusion_above_threshold")
        verdict = Verdict.MATCH
        confidence = fusion_score
        explanation = "Combined similarity score exceeds match threshold with clear margin."

    # R5: Fusion at threshold (borderline — recommend review)
    elif fusion_score >= match_threshold:
        rules_fired.append("R5:fusion_at_threshold")
        verdict = Verdict.POSSIBLE_MATCH
        confidence = fusion_score * 0.90
        explanation = (
            "Combined similarity is at the match threshold. "
            "Manual review recommended."
        )

    # R6: Only pHash at threshold, no other signal (weak)
    elif phash_medium:
        rules_fired.append("R6:phash_only_threshold")
        verdict = Verdict.POSSIBLE_MATCH
        confidence = phash_sim * 0.65
        explanation = (
            "Visual pHash similarity at threshold but audio/DL signals absent. "
            "Weak match — could be coincidental visual similarity."
        )

    # R7: Nothing qualifies
    else:
        rules_fired.append("R7:below_threshold")
        verdict = Verdict.NO_MATCH
        confidence = 1.0 - fusion_score
        explanation = "All similarity scores are below detection threshold."

    # Post-rule: tamper downgrade
    if tamper_score >= 0.6 and verdict == Verdict.MATCH:
        rules_fired.append("TM:tamper_downgrade")
        verdict = Verdict.POSSIBLE_MATCH
        confidence = round(confidence * 0.80, 4)
        explanation += (
            f" NOTE: High tamper score ({tamper_score:.2f}) detected — "
            "content appears significantly modified. Verification recommended."
        )

    return DecisionResult(
        verdict=verdict,
        confidence=round(confidence, 4),
        explanation=explanation,
        rules_fired=rules_fired,
    )
