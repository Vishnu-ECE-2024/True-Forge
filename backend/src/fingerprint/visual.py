"""
Visual fingerprinting using perceptual hashing (pHash).

pHash is the fast, lightweight baseline — 1ms/frame on CPU.
DL embeddings (MobileNetV3-Small) are computed separately in services/embedding.py
and stored in a parallel FAISS index for richer semantic matching.

Batch processing: pHash for multiple frames is parallelised with
ThreadPoolExecutor (I/O-bound PIL operations benefit from threading).
"""

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image

from src.core.config import settings

logger = logging.getLogger(__name__)

# 256 bits for hash_size=16; used as FAISS index dimension for pHash vectors
HASH_BITS = settings.hash_size * settings.hash_size

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def hash_image_directly(image_path: Path) -> np.ndarray:
    """
    Compute pHash for a single image file directly (no frame extraction needed).
    Returns float32 binary array of length HASH_BITS, same format as compute_visual_fingerprint.
    """
    img = Image.open(image_path).convert("RGB")
    h = imagehash.phash(img, hash_size=settings.hash_size)
    return np.array(h.hash.flatten(), dtype=np.float32)


def extract_frames(video_path: Path, asset_id: str) -> list[Path]:
    """
    Extract one frame per second from video using FFmpeg.
    Frames saved to data/frames/{asset_id}/ as JPEG.
    Returns sorted list of frame paths.
    """
    frames_dir = settings.frames_dir / asset_id
    frames_dir.mkdir(parents=True, exist_ok=True)

    output_pattern = str(frames_dir / "frame_%04d.jpg")
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"fps={settings.frame_sample_rate}",
        "-q:v", "3",
        "-an",
        output_pattern,
        "-y", "-loglevel", "error",
    ]

    logger.info(f"Extracting frames for {asset_id} at {settings.frame_sample_rate} fps")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg frame extraction failed: {result.stderr}")

    frames = sorted(frames_dir.glob("frame_*.jpg"))
    logger.info(f"Extracted {len(frames)} frames for {asset_id}")
    return frames


def get_video_duration(video_path: Path) -> float:
    """Get video duration in seconds using FFprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"ffprobe failed: {result.stderr}")
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def hash_frame(frame_path: Path) -> np.ndarray:
    """
    Compute pHash for a single frame.
    Returns float32 binary array of length HASH_BITS.
    """
    img = Image.open(frame_path).convert("RGB")
    h = imagehash.phash(img, hash_size=settings.hash_size)
    return np.array(h.hash.flatten(), dtype=np.float32)


def compute_visual_fingerprint(frame_paths: list[Path]) -> np.ndarray:
    """
    Compute mean visual fingerprint across all frames using parallel pHash.
    Returns float32 vector of length HASH_BITS.

    Strategy: average bit values across frames — creates a temporal centroid
    that is stable for the whole video. Near-duplicate videos have similar
    centroids. Thread-parallel for speed on multi-core CPUs.
    """
    if not frame_paths:
        raise ValueError("No frames provided for fingerprinting")

    hashes: list[np.ndarray] = []
    max_workers = min(settings.frame_worker_threads, len(frame_paths))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(hash_frame, fp): fp for fp in frame_paths}
        for fut in as_completed(futures):
            try:
                hashes.append(fut.result())
            except Exception as e:
                logger.warning(f"Failed to hash frame {futures[fut]}: {e}")

    if not hashes:
        raise RuntimeError("Could not hash any frames")

    fingerprint = np.mean(hashes, axis=0).astype(np.float32)
    logger.debug(
        f"Visual fingerprint: {len(hashes)} frames, shape={fingerprint.shape}"
    )
    return fingerprint


def cleanup_frames(asset_id: str) -> None:
    """Delete extracted frames after fingerprinting (save disk space)."""
    import shutil
    frames_dir = settings.frames_dir / asset_id
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
        logger.debug(f"Cleaned up frames for {asset_id}")
