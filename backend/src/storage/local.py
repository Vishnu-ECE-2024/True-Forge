"""Local filesystem storage for uploaded videos."""

import hashlib
import logging
import shutil
from pathlib import Path

from src.core.config import settings

logger = logging.getLogger(__name__)


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file efficiently (streaming, handles large files)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def save_upload(tmp_path: Path, asset_id: str, original_filename: str) -> Path:
    """
    Move uploaded file from temp location to permanent storage.
    Returns the final storage path.
    """
    ext = Path(original_filename).suffix.lower()
    dest_dir = settings.originals_dir / asset_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"original{ext}"

    shutil.move(str(tmp_path), str(dest_path))
    logger.info(f"Saved asset {asset_id} to {dest_path}")
    return dest_path


def get_asset_path(asset_id: str, original_filename: str) -> Path:
    """Get the expected storage path for an asset."""
    ext = Path(original_filename).suffix.lower()
    return settings.originals_dir / asset_id / f"original{ext}"


def delete_asset(asset_id: str) -> None:
    """Remove all files for an asset."""
    asset_dir = settings.originals_dir / asset_id
    if asset_dir.exists():
        shutil.rmtree(asset_dir)
        logger.info(f"Deleted asset files for {asset_id}")

    frames_dir = settings.frames_dir / asset_id
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
        logger.info(f"Deleted frames for {asset_id}")
