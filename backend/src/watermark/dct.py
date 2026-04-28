"""
Phase 2: Invisible DCT watermarking using DWT-DCT-SVD method.

Why this over VideoSeal (neural watermarking):
- CPU-only, no model download
- Works on any machine with OpenCV
- Survives mild re-encoding (JPEG compression, H.264 re-encode)
- VideoSeal upgrade documented at bottom (Phase 2.5)

Library: invisible-watermark (open source, used in stable diffusion)
  pip install invisible-watermark

Workflow:
  Embed: original video → watermarked video (saved alongside original)
  Extract: suspected video → decoded bytes → match against known asset IDs
"""

import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Max bytes we can embed with dwtDct method: 32 bytes = 256 bits
WATERMARK_BYTES = 32


def _load_encoder():
    """Lazy-load WatermarkEncoder (avoids startup cost if watermarking unused)."""
    try:
        from imwatermark import WatermarkEncoder
        return WatermarkEncoder()
    except ImportError:
        raise RuntimeError(
            "invisible-watermark not installed. "
            "Run: pip install invisible-watermark opencv-python-headless"
        )


def _load_decoder():
    try:
        from imwatermark import WatermarkDecoder
        return WatermarkDecoder("bytes", WATERMARK_BYTES * 8)
    except ImportError:
        raise RuntimeError("invisible-watermark not installed.")


def asset_id_to_bytes(asset_id: str) -> bytes:
    """Encode asset_id UUID (36 chars) into exactly WATERMARK_BYTES bytes."""
    # Strip dashes, take first 32 hex chars = 16 bytes, pad to WATERMARK_BYTES
    hex_str = asset_id.replace("-", "")[:WATERMARK_BYTES * 2]
    raw = bytes.fromhex(hex_str.ljust(WATERMARK_BYTES * 2, "0"))
    return raw


def bytes_to_asset_id_prefix(b: bytes) -> str:
    """Convert extracted bytes back to a comparable hex prefix."""
    return b.hex()


def embed_watermark_in_frame(
    bgr_frame: "np.ndarray",
    watermark_bytes: bytes,
) -> "np.ndarray":
    """
    Embed watermark_bytes into a single BGR frame using DWT-DCT method.
    Returns the watermarked frame (same shape, uint8).
    """
    encoder = _load_encoder()
    encoder.set_watermark("bytes", watermark_bytes)
    return encoder.encode(bgr_frame, "dwtDct")


def extract_watermark_from_frame(bgr_frame: "np.ndarray") -> bytes:
    """
    Extract watermark bytes from a single BGR frame.
    Returns raw bytes (may be garbage if no watermark was embedded).
    """
    decoder = _load_decoder()
    return decoder.decode(bgr_frame, "dwtDct")


def embed_watermark_video(
    input_path: Path,
    output_path: Path,
    asset_id: str,
    sample_every_n_frames: int = 3,
) -> Path:
    """
    Embed watermark into every Nth frame of a video.
    Writes a new video file at output_path.
    Returns output_path.

    Strategy: watermark every 3rd frame to balance robustness vs processing time.
    Non-watermarked frames are passed through unchanged (faster encoding).
    """
    import cv2

    watermark_bytes = asset_id_to_bytes(asset_id)
    cap = cv2.VideoCapture(str(input_path))

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    # Create encoder once — not per-frame
    encoder = _load_encoder()
    encoder.set_watermark("bytes", watermark_bytes)

    frame_idx = 0
    watermarked_count = 0

    logger.info(f"Embedding watermark in {total_frames} frames for {asset_id}")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_every_n_frames == 0:
            try:
                frame = encoder.encode(frame, "dwtDct")
                watermarked_count += 1
            except Exception as e:
                logger.warning(f"Frame {frame_idx} watermark failed: {e}")

        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()

    logger.info(
        f"Watermark embedded in {watermarked_count}/{frame_idx} frames → {output_path}"
    )
    return output_path


def embed_watermark_in_image(input_path: Path, output_path: Path, asset_id: str) -> Path:
    """Embed DWT-DCT watermark into a single image. Writes new file at output_path."""
    import cv2
    watermark_bytes = asset_id_to_bytes(asset_id)
    img = cv2.imread(str(input_path))
    if img is None:
        raise RuntimeError(f"Cannot open image: {input_path}")
    encoder = _load_encoder()
    encoder.set_watermark("bytes", watermark_bytes)
    watermarked = encoder.encode(img, "dwtDct")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), watermarked)
    logger.info(f"Watermark embedded in image for {asset_id} → {output_path}")
    return output_path


def detect_watermark_in_image(image_path: Path, known_asset_ids: list[str]) -> dict:
    """Detect DWT-DCT watermark in a single image. Returns same shape as detect_watermark_in_video."""
    import cv2
    expected_prefixes = {
        aid: bytes_to_asset_id_prefix(asset_id_to_bytes(aid))
        for aid in known_asset_ids
    }
    img = cv2.imread(str(image_path))
    if img is None:
        return {"detected": False, "asset_id": None, "confidence": 0.0, "frames_checked": 0}
    decoder = _load_decoder()
    try:
        extracted = decoder.decode(img, "dwtDct")
        extracted_hex = bytes_to_asset_id_prefix(extracted)
        votes: dict[str, int] = {}
        for aid, prefix in expected_prefixes.items():
            matching = sum(a == b for a, b in zip(extracted_hex, prefix))
            if matching >= len(prefix) * 0.8:
                votes[aid] = 1
        if not votes:
            return {"detected": False, "asset_id": None, "confidence": 0.0, "frames_checked": 1}
        winner = max(votes, key=lambda k: votes[k])
        return {"detected": True, "asset_id": winner, "confidence": 1.0, "frames_checked": 1}
    except Exception:
        return {"detected": False, "asset_id": None, "confidence": 0.0, "frames_checked": 1}


def detect_watermark_in_video(
    video_path: Path,
    known_asset_ids: list[str],
    sample_frames: int = 20,
    vote_threshold: float = 0.6,
) -> dict:
    """
    Sample frames from video and vote on which asset_id watermark is present.

    Returns:
      {
        "detected": bool,
        "asset_id": str | None,
        "confidence": float,      # fraction of frames that voted for winner
        "frames_checked": int,
      }
    """
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"detected": False, "asset_id": None, "confidence": 0.0, "frames_checked": 0}

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total == 0:
        cap.release()
        return {"detected": False, "asset_id": None, "confidence": 0.0, "frames_checked": 0}

    # Build expected prefixes for each known asset_id
    expected_prefixes = {
        aid: bytes_to_asset_id_prefix(asset_id_to_bytes(aid))
        for aid in known_asset_ids
    }

    # Create decoder once — not per-frame
    decoder = _load_decoder()

    # Sample evenly across video
    step = max(1, total // sample_frames)
    votes: dict[str, int] = {}
    frames_checked = 0

    for i in range(0, total, step):
        if frames_checked >= sample_frames:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if not ret:
            continue

        try:
            extracted = decoder.decode(frame, "dwtDct")
            extracted_hex = bytes_to_asset_id_prefix(extracted)

            # Vote for the closest matching asset_id
            for aid, prefix in expected_prefixes.items():
                # Count matching hex chars (prefix comparison)
                matching = sum(a == b for a, b in zip(extracted_hex, prefix))
                if matching >= len(prefix) * 0.8:  # 80% prefix match
                    votes[aid] = votes.get(aid, 0) + 1

            frames_checked += 1
        except Exception:
            continue

    cap.release()

    if not votes or frames_checked == 0:
        return {"detected": False, "asset_id": None, "confidence": 0.0, "frames_checked": frames_checked}

    winner = max(votes, key=lambda k: votes[k])
    confidence = votes[winner] / frames_checked

    return {
        "detected": confidence >= vote_threshold,
        "asset_id": winner if confidence >= vote_threshold else None,
        "confidence": round(confidence, 3),
        "frames_checked": frames_checked,
    }


# ---------------------------------------------------------------------------
# FUTURE UPGRADE: VideoSeal neural watermarking
# ---------------------------------------------------------------------------
# VideoSeal (Meta Research) embeds imperceptible watermarks that survive:
# - H.264/H.265 re-encoding
# - Screen recording
# - Moderate cropping and color grading
#
# Requires: GPU (RTX 4060 is fine), PyTorch, ~200MB model
#
# When ready:
#   pip install videoseal
#   from videoseal import VideoSeal
#   model = VideoSeal.from_pretrained("facebook/videoseal")
#   watermarked = model.embed(frames_tensor, message=asset_id_bits)
#
# The extract workflow is similarly simple. Detection accuracy is significantly
# better than DCT-based methods, especially after social media re-compression.
