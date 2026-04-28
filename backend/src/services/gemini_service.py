"""Google Gemini API service for video content analysis with local fallback."""

import base64
import json
import logging
from pathlib import Path
from typing import Optional

from src.core.config import settings

logger = logging.getLogger(__name__)

_gemini_client = None


def get_gemini_client():
    """Lazy-load Gemini client. Returns None if API key not set or disabled."""
    global _gemini_client

    if _gemini_client is not None:
        return _gemini_client

    if not settings.google_ai_enabled or not settings.google_api_key:
        logger.info("Gemini disabled or no API key — using local fallback")
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.google_api_key)
        _gemini_client = genai.GenerativeModel(settings.gemini_model)
        logger.info(f"Gemini client initialized: {settings.gemini_model}")
        return _gemini_client
    except Exception as e:
        logger.warning(f"Failed to initialize Gemini: {e} — using local fallback")
        return None


def analyze_frame_with_gemini(frame_path: Path) -> Optional[dict]:
    """
    Analyze a video frame with Gemini for content classification.

    Returns dict: {
        "classification": "sports|non-sports|unclear",
        "sport_type": "cricket|football|tennis|other|None",
        "confidence": 0.0-1.0,
        "scene_description": "string",
        "teams": ["team1", "team2"] or [],
        "error": None or error string
    }

    Returns None if Gemini unavailable (fallback to local fingerprinting).
    """
    client = get_gemini_client()
    if not client or not frame_path.exists():
        return None

    try:
        with open(frame_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        response = client.generate_content([
            {
                "mime_type": "image/jpeg",
                "data": image_data,
            },
            """Analyze this video frame and respond in JSON:
{
  "classification": "sports" or "non-sports" or "unclear",
  "sport_type": "cricket" or "football" or "tennis" or "other" or null,
  "confidence": 0.0-1.0,
  "scene_description": "brief description of the scene",
  "teams": ["team1", "team2"] or []
}

Be concise. Only return valid JSON."""
        ])

        text = response.text.strip()

        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        result = json.loads(text.strip())
        result["error"] = None
        return result

    except json.JSONDecodeError as e:
        logger.warning(f"Gemini response parsing failed: {e}")
        return {"error": f"JSON parse error: {e}"}
    except Exception as e:
        logger.warning(f"Gemini frame analysis failed: {e}")
        return {"error": str(e)}


def generate_dmca_narrative(report: dict) -> Optional[str]:
    """Generate a professional DMCA takedown notice narrative using Gemini."""
    client = get_gemini_client()
    if not client:
        return None

    s = report.get("summary", {})
    o = report.get("original_content", {})
    c = report.get("suspected_copy", {})
    t = report.get("technical_evidence", {})
    flags = t.get("tamper_details", {}).get("flags", [])

    prompt = f"""You are a legal assistant. Write a formal DMCA Section 512(c) takedown notice based on this evidence:

Original work: {o.get("filename", "Unknown")}
Registered: {o.get("registered_at", "Unknown")}
Suspected infringing URL: {c.get("source_url", "Unknown")}
Platform: {c.get("platform", "Unknown")}
Similarity score: {s.get("similarity_percent", "Unknown")}
Match type: {s.get("match_type", "Unknown")}
AI-detected tamper modifications: {", ".join(flags) if flags else "None detected"}
Tamper score: {t.get("tamper_score", 0):.0%}

Write a complete, professional DMCA takedown notice (300-400 words) including:
1. Identification of the copyrighted work and rights holder
2. Identification of the infringing material and its location
3. AI-assisted technical evidence summary (fingerprint similarity, tamper analysis)
4. Good faith belief statement
5. Accuracy and penalty of perjury statement

Be formal, precise, and legally appropriate. Do not use placeholder brackets."""

    try:
        response = client.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.warning(f"DMCA narrative generation failed: {e}")
        return None


def analyze_frames_batch(frame_paths: list[Path], sample_every_n: int = 1) -> dict:
    """
    Analyze multiple frames and return aggregate statistics.

    Returns dict: {
        "overall_classification": "sports|non-sports|mixed",
        "sport_type": most common sport or None,
        "confidence": average confidence,
        "scene_descriptions": [list of unique descriptions],
        "teams": [set of detected teams],
        "frame_count": total frames analyzed,
        "errors": count of failures
    }
    """
    client = get_gemini_client()
    if not client:
        return {
            "overall_classification": "unknown",
            "sport_type": None,
            "confidence": 0.0,
            "scene_descriptions": [],
            "teams": [],
            "frame_count": 0,
            "errors": len(frame_paths),
        }

    sampled = frame_paths[::sample_every_n][:10]

    sport_counts = {}
    confidence_scores = []
    descriptions = set()
    teams = set()
    errors = 0

    for frame_path in sampled:
        result = analyze_frame_with_gemini(frame_path)
        if not result or result.get("error"):
            errors += 1
            continue

        if result.get("classification") == "sports":
            sport = result.get("sport_type")
            if sport:
                sport_counts[sport] = sport_counts.get(sport, 0) + 1

        confidence_scores.append(result.get("confidence", 0))

        if result.get("scene_description"):
            descriptions.add(result["scene_description"][:100])

        if result.get("teams"):
            teams.update(result["teams"])

    classifications = [
        "sports" if sport_counts else "non-sports"
        for _ in range(len(sampled) - errors)
    ]
    overall = max(set(classifications), key=classifications.count) if classifications else "unknown"

    top_sport = max(sport_counts, key=sport_counts.get) if sport_counts else None
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0

    return {
        "overall_classification": overall,
        "sport_type": top_sport,
        "confidence": round(avg_confidence, 2),
        "scene_descriptions": list(descriptions)[:5],
        "teams": list(teams),
        "frame_count": len(sampled),
        "errors": errors,
    }
