"""
Tamper detection and integrity analysis.

Detects common redistribution tricks:
  1. Letterbox / pillarbox (black bars added)
  2. Scene cut insertion (hard cuts at start/end to confuse fingerprinting)
  3. Logo / overlay insertion (static corner logo burnt in)
  4. Excessive re-compression (quality degradation)
  5. Frame difference anomalies (frozen video, speed change, noise injection)

All CPU-only via FFmpeg + OpenCV. No ML model required.
"""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run_ffprobe(video_path: Path, show_entries: str, select_streams: str = "") -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_entries", show_entries,
    ]
    if select_streams:
        cmd += ["-select_streams", select_streams]
    cmd.append(str(video_path))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


# ── Detection functions ───────────────────────────────────────────────────────

def detect_letterbox(video_path: Path) -> dict:
    """
    Detect letterbox/pillarbox (black bars).
    Uses FFmpeg cropdetect filter on the first 60 frames.
    Returns {"has_letterbox": bool, "detected_crop": str}
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", "cropdetect=24:16:0",
        "-frames:v", "60",
        "-f", "null", "-",
        "-loglevel", "info",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    crop_values = []
    for line in result.stderr.splitlines():
        if "crop=" in line:
            try:
                crop_values.append(line.split("crop=")[-1].split()[0])
            except IndexError:
                pass

    if not crop_values:
        return {"has_letterbox": False, "detected_crop": ""}

    probe = _run_ffprobe(video_path, "stream=width,height", "v:0")
    streams = probe.get("streams", [{}])
    orig_w = streams[0].get("width", 0) if streams else 0
    orig_h = streams[0].get("height", 0) if streams else 0

    most_common = max(set(crop_values), key=crop_values.count)
    parts = most_common.split(":")
    if len(parts) >= 2:
        try:
            cw, ch = int(parts[0]), int(parts[1])
            has_lb = orig_w > 0 and orig_h > 0 and (
                cw < orig_w * 0.95 or ch < orig_h * 0.95
            )
            return {"has_letterbox": has_lb, "detected_crop": most_common}
        except ValueError:
            pass

    return {"has_letterbox": False, "detected_crop": most_common}


def detect_scene_cuts(video_path: Path, threshold: float = 0.4) -> dict:
    """
    Count abrupt scene cuts using FFmpeg scene detection.
    High cut rate at start/end suggests content was padded or spliced.
    Returns {"scene_count": int, "cuts_per_minute": float}
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-frames:v", "500",
        "-f", "null", "-",
        "-loglevel", "info",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    scene_count = result.stderr.count("pts_time:")

    probe = _run_ffprobe(video_path, "format=duration")
    duration = float(probe.get("format", {}).get("duration", 1) or 1)
    duration_min = max(duration / 60, 0.1)

    return {
        "scene_count": scene_count,
        "cuts_per_minute": round(scene_count / duration_min, 2),
    }


def detect_overlay(video_path: Path) -> dict:
    """
    Detect static corner overlays (burnt-in logos) using temporal variance.
    Low temporal variance in a corner region = static logo present.
    Returns {"overlay_detected": bool, "corner_entropy_score": float}
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {"overlay_detected": False, "corner_entropy_score": 1.0}

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"overlay_detected": False, "corner_entropy_score": 1.0}

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total < 10:
        cap.release()
        return {"overlay_detected": False, "corner_entropy_score": 1.0}

    patches = []
    sample_count = min(30, total)
    step = max(1, total // sample_count)

    for i in range(0, total, step):
        if len(patches) >= sample_count:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if not ret:
            continue
        h, w = frame.shape[:2]
        patch = frame[0: h // 8, w * 7 // 8:]   # top-right corner
        patches.append(patch.astype(np.float32))

    cap.release()

    if not patches:
        return {"overlay_detected": False, "corner_entropy_score": 1.0}

    stacked = np.stack(patches, axis=0)
    temporal_variance = float(np.var(stacked, axis=0).mean())
    normalized = min(1.0, temporal_variance / 200.0)

    return {
        "overlay_detected": normalized < 0.1,
        "corner_entropy_score": round(normalized, 4),
    }


def detect_frame_differences(video_path: Path) -> dict:
    """
    Analyse inter-frame pixel differences to detect:
      - Frozen video (near-zero diffs) → likely static re-broadcast or error
      - Speed change (spike in mean diff at a point) → possible tempo manipulation
      - Noise injection (uniformly elevated diffs) → adversarial perturbation

    Samples up to 50 consecutive frame pairs using OpenCV.

    Returns:
      {
        "mean_diff":      float,   # avg pixel change per frame pair (0-255)
        "std_diff":       float,   # variability of diffs
        "frozen_frames":  int,     # pairs with diff < 2.0 (near-identical)
        "spike_frames":   int,     # pairs with diff > mean + 3*std
        "frozen":         bool,    # > 30% frames frozen
        "speed_changed":  bool,    # spike_frames > 5% of samples
        "noise_injected": bool,    # mean_diff > 40 with low std (uniform noise)
      }
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {
            "mean_diff": 0.0, "std_diff": 0.0,
            "frozen_frames": 0, "spike_frames": 0,
            "frozen": False, "speed_changed": False, "noise_injected": False,
        }

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {
            "mean_diff": 0.0, "std_diff": 0.0,
            "frozen_frames": 0, "spike_frames": 0,
            "frozen": False, "speed_changed": False, "noise_injected": False,
        }

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_count = min(50, max(1, total - 1))
    step = max(1, total // sample_count)

    diffs: list[float] = []
    prev_gray = None

    for i in range(0, total, step):
        if len(diffs) >= sample_count:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev_gray is not None:
            diff = float(np.mean(np.abs(gray - prev_gray)))
            diffs.append(diff)
        prev_gray = gray

    cap.release()

    if not diffs:
        return {
            "mean_diff": 0.0, "std_diff": 0.0,
            "frozen_frames": 0, "spike_frames": 0,
            "frozen": False, "speed_changed": False, "noise_injected": False,
        }

    arr = np.array(diffs)
    mean_d = float(arr.mean())
    std_d  = float(arr.std())

    frozen_frames = int(np.sum(arr < 2.0))
    spike_thresh  = mean_d + 3 * std_d if std_d > 0 else mean_d * 3
    spike_frames  = int(np.sum(arr > spike_thresh))

    frozen_ratio = frozen_frames / len(diffs)
    spike_ratio  = spike_frames  / len(diffs)

    return {
        "mean_diff":     round(mean_d, 3),
        "std_diff":      round(std_d, 3),
        "frozen_frames": frozen_frames,
        "spike_frames":  spike_frames,
        "frozen":        frozen_ratio > 0.30,
        "speed_changed": spike_ratio  > 0.05,
        "noise_injected": mean_d > 40.0 and std_d < 5.0,
    }


def compute_compression_score(video_path: Path) -> float:
    """
    Estimate compression quality. Low bitrate relative to resolution = heavy re-compression.
    Returns score 0.0 (very compressed) to 1.0 (high quality).
    """
    probe = _run_ffprobe(video_path, "format=bit_rate,duration")
    fmt = probe.get("format", {})
    bitrate = int(fmt.get("bit_rate", 0) or 0)

    streams_probe = _run_ffprobe(video_path, "stream=width,height,codec_name", "v:0")
    streams = streams_probe.get("streams", [{}])
    w = streams[0].get("width", 1280) if streams else 1280
    h = streams[0].get("height", 720) if streams else 720
    pixels = w * h

    if bitrate == 0 or pixels == 0:
        return 0.5

    bpps = bitrate / pixels
    return round(min(1.0, bpps / 0.3), 4)


def analyze_tamper(video_path: Path) -> dict:
    """
    Run all tamper detection checks and return a combined report.

    Returns:
    {
      "tamper_score":      float,   # 0.0 = clean, 1.0 = heavily tampered
      "flags":             [str],   # human-readable flags
      "letterbox":         {...},
      "scene_cuts":        {...},
      "overlay":           {...},
      "frame_differences": {...},
      "compression_score": float,
    }
    """
    flags: list[str] = []

    letterbox  = detect_letterbox(video_path)
    scene_cuts = detect_scene_cuts(video_path)
    overlay    = detect_overlay(video_path)
    frame_diff = detect_frame_differences(video_path)
    compression = compute_compression_score(video_path)

    if letterbox["has_letterbox"]:
        flags.append(f"letterbox_detected:{letterbox['detected_crop']}")

    if scene_cuts["cuts_per_minute"] > 10:
        flags.append(f"high_scene_cuts:{scene_cuts['cuts_per_minute']}/min")

    if overlay["overlay_detected"]:
        flags.append("static_corner_overlay_detected")

    if frame_diff.get("frozen"):
        flags.append("frozen_video_detected")
    if frame_diff.get("speed_changed"):
        flags.append("speed_change_detected")
    if frame_diff.get("noise_injected"):
        flags.append("noise_injection_detected")

    if compression < 0.2:
        flags.append(f"heavy_compression:score={compression:.2f}")

    # Weighted tamper score
    tamper_score = 0.0
    if letterbox["has_letterbox"]:
        tamper_score += 0.15
    if scene_cuts["cuts_per_minute"] > 10:
        tamper_score += min(0.25, scene_cuts["cuts_per_minute"] / 100)
    if overlay["overlay_detected"]:
        tamper_score += 0.25
    if frame_diff.get("frozen"):
        tamper_score += 0.15
    if frame_diff.get("speed_changed"):
        tamper_score += 0.10
    if frame_diff.get("noise_injected"):
        tamper_score += 0.20
    tamper_score += (1.0 - compression) * 0.15

    return {
        "tamper_score":      round(min(1.0, tamper_score), 4),
        "flags":             flags,
        "letterbox":         letterbox,
        "scene_cuts":        scene_cuts,
        "overlay":           overlay,
        "frame_differences": frame_diff,
        "compression_score": compression,
    }
