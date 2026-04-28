"""SQLAlchemy ORM models — all phases."""

from datetime import datetime
from sqlalchemy import (
    Boolean, Column, Float, DateTime, ForeignKey,
    Integer, String, Text, Enum as SAEnum
)
from sqlalchemy.orm import DeclarativeBase, relationship

from src.core.models import AssetStatus, MonitorJobStatus  # single source of truth


class Base(DeclarativeBase):
    pass


class Asset(Base):
    __tablename__ = "assets"

    asset_id          = Column(String(64),  primary_key=True)
    filename          = Column(String(512), nullable=False)
    original_filename = Column(String(512), nullable=False)
    status            = Column(SAEnum(AssetStatus), nullable=False, default=AssetStatus.PENDING)
    file_size_bytes   = Column(Integer, nullable=False)
    duration_seconds  = Column(Float,   nullable=True)
    frame_count       = Column(Integer, nullable=True)
    sha256            = Column(String(64), nullable=False, unique=True, index=True)
    created_at        = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at      = Column(DateTime, nullable=True)
    error_message     = Column(Text,    nullable=True)

    # FAISS row id maps the asset to its vector in the pHash index
    faiss_row_id      = Column(Integer, nullable=True, index=True)

    # DL embedding FAISS row id (MobileNetV3-Small, 576-dim)
    dl_faiss_row_id   = Column(Integer, nullable=True, index=True)

    # Audio fingerprint (Chromaprint) stored as comma-separated ints
    audio_fingerprint = Column(Text, nullable=True)

    # Gemini AI metadata (JSON: classification, scenes, confidence)
    gemini_metadata = Column(Text, nullable=True)

    # Phase 2: watermark
    watermark_embedded = Column(Boolean, default=False)

    # Relationships
    watermarks = relationship("WatermarkRecord", back_populates="asset")
    alerts     = relationship("MatchAlert", back_populates="matched_asset")


# ── Phase 2: Watermarks ──────────────────────────────────────────────────────

class WatermarkRecord(Base):
    __tablename__ = "watermark_records"

    record_id    = Column(String(64), primary_key=True)
    asset_id     = Column(String(64), ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False, index=True)
    output_path  = Column(String(512), nullable=False)   # path to watermarked video
    method       = Column(String(32),  nullable=False, default="dwtDct")
    created_at   = Column(DateTime, nullable=False, default=datetime.utcnow)

    asset = relationship("Asset", back_populates="watermarks")


# ── Phase 3: Monitoring ──────────────────────────────────────────────────────

class MonitorJob(Base):
    __tablename__ = "monitor_jobs"

    job_id         = Column(String(64), primary_key=True)
    url            = Column(Text,       nullable=False)
    status         = Column(SAEnum(MonitorJobStatus), nullable=False, default=MonitorJobStatus.QUEUED)
    platform       = Column(String(64), nullable=True)
    video_title    = Column(Text,       nullable=True)
    video_duration = Column(Float,      nullable=True)
    created_at     = Column(DateTime,   nullable=False, default=datetime.utcnow)
    started_at     = Column(DateTime,   nullable=True)
    completed_at   = Column(DateTime,   nullable=True)
    alerts_created = Column(Integer,    nullable=True, default=0)
    error_message  = Column(Text,       nullable=True)

    alerts = relationship("MatchAlert", back_populates="job")


# ── Phase 4: Match Alerts ────────────────────────────────────────────────────

class MatchAlert(Base):
    __tablename__ = "match_alerts"

    alert_id          = Column(String(64), primary_key=True)
    job_id            = Column(String(64), ForeignKey("monitor_jobs.job_id", ondelete="SET NULL"), nullable=True, index=True)
    matched_asset_id  = Column(String(64), ForeignKey("assets.asset_id",    ondelete="CASCADE"), nullable=False, index=True)
    source_url        = Column(Text,   nullable=False)
    platform          = Column(String(64), nullable=True)
    video_title       = Column(Text,   nullable=True)
    similarity_score  = Column(Float,  nullable=False)
    match_type        = Column(String(32), nullable=False)  # exact / near_duplicate / partial
    tamper_score      = Column(Float,  nullable=True)
    tamper_details    = Column(Text,   nullable=True)       # JSON string
    watermark_detected = Column(Boolean, default=False)
    reviewed          = Column(Boolean, default=False)
    created_at        = Column(DateTime, nullable=False, default=datetime.utcnow)

    job           = relationship("MonitorJob", back_populates="alerts")
    matched_asset = relationship("Asset",      back_populates="alerts")
