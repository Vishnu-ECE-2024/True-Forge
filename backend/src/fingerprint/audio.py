"""
Audio fingerprinting using Chromaprint (via fpcalc).

Why Chromaprint over PANNs for v1:
- Zero model download, instant startup
- Industry standard (used by MusicBrainz, AcoustID)
- CPU only, < 1 second for a 30-min video
- Detects re-encoded audio, re-compressed audio, pitch shifts within ±10%
- PANNs upgrade path documented at bottom

Future upgrade: Add PANNs for scene/action audio classification (different use case)
"""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_audio(video_path: Path, output_path: Path) -> Path:
    """
    Extract audio from video as a mono WAV file for fingerprinting.
    Returns output_path (or raises if ffmpeg fails).
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-ac", "1",           # mono
        "-ar", "22050",       # 22kHz (enough for fingerprinting)
        "-vn",                # no video
        str(output_path),
        "-y", "-loglevel", "error"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed: {result.stderr}")

    logger.debug(f"Extracted audio to {output_path}")
    return output_path


def compute_chromaprint(audio_path: Path) -> str | None:
    """
    Compute Chromaprint fingerprint using fpcalc.
    Returns the fingerprint as a hex string, or None if fpcalc is unavailable.

    fpcalc is part of libchromaprint-tools package.
    Install: apt install libchromaprint-tools
    """
    cmd = ["fpcalc", "-raw", "-json", str(audio_path)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        logger.warning("fpcalc not found; skipping audio fingerprint. Install: apt install libchromaprint-tools")
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"fpcalc timed out for {audio_path}")
        return None

    if result.returncode != 0:
        logger.warning(f"fpcalc failed: {result.stderr}")
        return None

    try:
        data = json.loads(result.stdout)
        fingerprint_ints = data.get("fingerprint", [])
        # Store as comma-separated int string (compact, preserves full precision)
        return ",".join(str(x) for x in fingerprint_ints)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to parse fpcalc output: {e}")
        return None


def compute_audio_fingerprint(video_path: Path, asset_id: str) -> str | None:
    """
    Full pipeline: extract audio → compute Chromaprint fingerprint.
    Returns fingerprint string or None if audio extraction/fingerprinting fails.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = Path(tmp.name)

    try:
        extract_audio(video_path, audio_path)
        fingerprint = compute_chromaprint(audio_path)
        return fingerprint
    except RuntimeError as e:
        # Video may have no audio track — this is fine
        logger.info(f"Audio fingerprinting skipped for {asset_id}: {e}")
        return None
    finally:
        audio_path.unlink(missing_ok=True)


def compare_audio_fingerprints(fp1: str, fp2: str) -> float:
    """
    Compare two Chromaprint fingerprints using bit error rate on overlapping frames.
    Returns similarity in [0, 1]; 1.0 = identical.

    Chromaprint compresses to 32-bit integers where each bit encodes a subband.
    Hamming distance on these integers gives robust similarity.
    """
    try:
        ints1 = [int(x) for x in fp1.split(",") if x]
        ints2 = [int(x) for x in fp2.split(",") if x]
    except ValueError:
        return 0.0

    if not ints1 or not ints2:
        return 0.0

    # Compare on overlap
    min_len = min(len(ints1), len(ints2))
    max_len = max(len(ints1), len(ints2))

    if min_len == 0:
        return 0.0

    # Use sliding window to find best alignment (handles trimmed content)
    best_similarity = 0.0
    max_offset = min(30, max_len - min_len)  # search up to 30 frames offset

    for offset in range(max_offset + 1):
        matching_bits = 0
        total_bits = min_len * 32

        for i in range(min_len):
            j = i + offset if offset < len(ints2) - i else i
            if j >= len(ints2):
                break
            xor = ints1[i] ^ ints2[j]
            # Count matching bits (32 - popcount of xor)
            matching_bits += 32 - bin(xor & 0xFFFFFFFF).count("1")

        similarity = matching_bits / total_bits if total_bits > 0 else 0.0
        best_similarity = max(best_similarity, similarity)

    return best_similarity


# ---------------------------------------------------------------------------
# FUTURE UPGRADE PATH: PANNs audio classification
# ---------------------------------------------------------------------------
# PANNs (Pretrained Audio Neural Networks) classify audio scenes/events.
# This is DIFFERENT from fingerprinting — it identifies "what kind of content"
# rather than "is this the same audio".
#
# Use case: Classify if suspected copy is sports content before deep comparison.
# Example: "crowd noise + whistle = likely sports" → prioritize for comparison.
#
# Install when ready:
#   pip install panns-inference
#
# Usage:
#   from panns_inference import AudioTagging
#   at = AudioTagging(checkpoint_path=None, device='cpu')
#   audio, _ = librosa.load('video.wav', sr=32000, mono=True)
#   clipwise_output, _ = at.inference(audio[None, :])
#   # Returns 527-class AudioSet predictions
