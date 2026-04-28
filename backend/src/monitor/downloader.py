"""
Phase 3: URL-based video monitoring using yt-dlp.

Why yt-dlp over scraping:
- Legal: downloads via public video streams (not bypassing paywalls)
- Reliable: maintained by large open-source community
- Supports 1000+ platforms: YouTube, TikTok, Facebook, Twitter/X, Telegram, etc.
- CPU-only, no special hardware
- Respects robots.txt / platform rate limits

Legal note: Downloading for the purpose of copyright comparison/evidence
is generally permissible under fair use / fair dealing in most jurisdictions.
Do NOT redistribute downloaded content. Store only temporarily for analysis.

Install: pip install yt-dlp (already in requirements.txt)
"""

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    success: bool
    video_path: Path | None
    platform: str
    title: str
    duration_seconds: float
    error: str | None = None


def detect_platform(url: str) -> str:
    """Guess platform from URL for logging/reporting."""
    url_lower = url.lower()
    for platform in ["youtube", "tiktok", "instagram", "facebook", "twitter", "telegram", "twitch"]:
        if platform in url_lower:
            return platform
    return "unknown"


def download_video(url: str, output_dir: Path, max_duration_seconds: int = 600) -> DownloadResult:
    """
    Download a video from a URL using yt-dlp.

    Uses lowest quality (worst) to save bandwidth and disk space —
    we only need enough quality for fingerprint comparison.
    Downloads to a temp file inside output_dir.

    Returns DownloadResult with path to downloaded file.
    """
    try:
        import yt_dlp
    except ImportError:
        return DownloadResult(
            success=False,
            video_path=None,
            platform=detect_platform(url),
            title="",
            duration_seconds=0,
            error="yt-dlp not installed. Run: pip install yt-dlp",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    platform = detect_platform(url)

    # Use a temp filename; yt-dlp will add the extension
    tmp_output = str(output_dir / "download_%(id)s.%(ext)s")

    ydl_opts = {
        # Prefer worst quality (small file, sufficient for fingerprinting)
        "format": "worst[ext=mp4]/worst[ext=webm]/worst",
        "outtmpl": tmp_output,
        "noplaylist": True,          # single video only
        "no_warnings": False,
        "quiet": True,
        "noprogress": True,
        "socket_timeout": 30,
        # Respect duration limit (don't download 3-hour streams)
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration < {max_duration_seconds}"
        ),
        # Limit download speed to avoid overwhelming network
        "ratelimit": 2 * 1024 * 1024,  # 2 MB/s
    }

    downloaded_path: Path | None = None
    title = ""
    duration = 0.0

    class PathHook:
        def __init__(self):
            self.path = None

        def __call__(self, d):
            if d["status"] == "finished":
                self.path = Path(d["filename"])

    hook = PathHook()
    ydl_opts["progress_hooks"] = [hook]

    try:
        logger.info(f"Downloading from {platform}: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                title = info.get("title", "")
                duration = float(info.get("duration", 0))

        downloaded_path = hook.path

        # Fallback: find the downloaded file if hook didn't fire
        if downloaded_path is None:
            candidates = sorted(output_dir.glob("download_*"))
            if candidates:
                downloaded_path = candidates[-1]

        if downloaded_path and downloaded_path.exists():
            logger.info(f"Downloaded: {downloaded_path.name} ({duration:.0f}s)")
            return DownloadResult(
                success=True,
                video_path=downloaded_path,
                platform=platform,
                title=title,
                duration_seconds=duration,
            )
        else:
            return DownloadResult(
                success=False,
                video_path=None,
                platform=platform,
                title=title,
                duration_seconds=duration,
                error="Download completed but file not found",
            )

    except Exception as e:
        error_msg = str(e)
        logger.warning(f"Download failed for {url}: {error_msg}")
        return DownloadResult(
            success=False,
            video_path=None,
            platform=platform,
            title=title,
            duration_seconds=duration,
            error=error_msg,
        )
    finally:
        # Clean up any partial downloads
        for f in output_dir.glob("download_*.part"):
            f.unlink(missing_ok=True)
