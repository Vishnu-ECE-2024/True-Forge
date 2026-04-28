"""Pydantic models for API request/response validation."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class AssetStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    READY      = "ready"
    FAILED     = "failed"


class MonitorJobStatus(str, Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"


class AssetUploadResponse(BaseModel):
    asset_id: str
    filename: str
    status: AssetStatus
    message: str


class AssetDetail(BaseModel):
    asset_id: str
    filename: str
    original_filename: str
    status: AssetStatus
    file_size_bytes: int
    duration_seconds: Optional[float]
    frame_count: Optional[int]
    sha256: str
    created_at: datetime
    processed_at: Optional[datetime]
    gemini_metadata: Optional[dict] = None  # AI analysis: classification, confidence, etc


class AssetListItem(BaseModel):
    asset_id: str
    filename: str
    status: AssetStatus
    duration_seconds: Optional[float]
    created_at: datetime
    gemini_metadata: Optional[dict] = None


class SearchResult(BaseModel):
    asset_id: str
    filename: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    match_type: str   # "exact", "near_duplicate", "partial"
    duration_seconds: Optional[float]
    created_at: datetime
    # Added in v2: fusion engine output (optional for backward compat)
    verdict: Optional[str] = None          # MATCH / POSSIBLE_MATCH / NO_MATCH
    confidence: Optional[float] = None
    score_breakdown: Optional[dict] = None
    # Added: Google Gemini AI classification
    gemini_metadata: Optional[dict] = None  # AI: classification, sport_type, confidence


class SearchResponse(BaseModel):
    query_asset_id: Optional[str]  # set if query was uploaded as asset
    results: list[SearchResult]
    total_candidates: int
    processing_time_ms: float
    query_gemini_analysis: Optional[dict] = None  # Gemini AI analysis of the uploaded query video


class HealthResponse(BaseModel):
    status: str
    database: str
    faiss_index: str
    total_assets: int
    indexed_assets: int
