"""
Unit tests for visual and audio fingerprinting.
These tests do NOT require FFmpeg or a video file — they test the hash/compare logic.
"""

import numpy as np
import pytest
from PIL import Image
from pathlib import Path
import tempfile

from src.fingerprint.visual import hash_frame, compute_visual_fingerprint, HASH_BITS
from src.fingerprint.audio import compare_audio_fingerprints


def make_test_frame(color: tuple[int,int,int] = (128, 64, 32)) -> Path:
    """Create a solid-color test image as a temporary file."""
    img = Image.new("RGB", (320, 240), color=color)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    img.save(tmp.name)
    return Path(tmp.name)


def test_hash_frame_returns_correct_shape():
    frame = make_test_frame()
    try:
        bits = hash_frame(frame)
        assert bits.shape == (HASH_BITS,), f"Expected ({HASH_BITS},), got {bits.shape}"
        assert bits.dtype == np.float32
    finally:
        frame.unlink(missing_ok=True)


def test_identical_frames_have_same_hash():
    frame1 = make_test_frame((100, 150, 200))
    frame2 = make_test_frame((100, 150, 200))
    try:
        h1 = hash_frame(frame1)
        h2 = hash_frame(frame2)
        assert np.allclose(h1, h2), "Identical frames should have identical hashes"
    finally:
        frame1.unlink(missing_ok=True)
        frame2.unlink(missing_ok=True)


def test_different_frames_have_different_hashes():
    frame1 = make_test_frame((0, 0, 0))       # black
    frame2 = make_test_frame((255, 255, 255))  # white
    try:
        h1 = hash_frame(frame1)
        h2 = hash_frame(frame2)
        # Should differ significantly
        diff = np.sum(np.abs(h1 - h2))
        assert diff > 0, "Black and white frames should have different hashes"
    finally:
        frame1.unlink(missing_ok=True)
        frame2.unlink(missing_ok=True)


def test_visual_fingerprint_from_multiple_frames():
    frames = [make_test_frame((i*30, 100, 200)) for i in range(5)]
    try:
        fp = compute_visual_fingerprint(frames)
        assert fp.shape == (HASH_BITS,)
        assert fp.dtype == np.float32
    finally:
        for f in frames:
            f.unlink(missing_ok=True)


def test_visual_fingerprint_empty_raises():
    with pytest.raises(ValueError, match="No frames"):
        compute_visual_fingerprint([])


def test_audio_compare_identical():
    fp = ",".join(str(x) for x in [123456789, 987654321, 111222333])
    similarity = compare_audio_fingerprints(fp, fp)
    assert similarity == 1.0, f"Identical fingerprints should be 1.0, got {similarity}"


def test_audio_compare_empty():
    similarity = compare_audio_fingerprints("", "123,456")
    assert similarity == 0.0


def test_audio_compare_different():
    fp1 = ",".join(str(x) for x in [0xFFFFFFFF] * 10)     # all 1s
    fp2 = ",".join(str(x) for x in [0x00000000] * 10)     # all 0s
    similarity = compare_audio_fingerprints(fp1, fp2)
    assert similarity < 0.1, f"Completely different fingerprints should be near 0, got {similarity}"
