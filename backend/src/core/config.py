"""Application configuration loaded from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql://smp_user:changeme@localhost:5432/smp_db"

    # Storage
    data_dir: Path = Path("/app/data")
    faiss_index_path: Path = Path("/app/data/indices/visual.index")

    # Logging
    log_level: str = "INFO"

    # Upload constraints
    max_video_size_mb: int = 500

    # Fingerprinting
    frame_sample_rate: int = 1      # frames per second to sample
    hash_size: int = 16             # pHash grid size (16 = 256-bit)
    match_threshold: float = 0.85   # 0.0–1.0 similarity to call a match

    # Deep learning embeddings
    dl_index_path: Path = Path("/app/data/indices/dl.index")
    dl_embedding_dim: int = 576     # MobileNetV3-Small feature dim (fixed)
    dl_max_frames: int = 30         # max frames sampled for DL embedding
    embedding_cache_size: int = 500 # LRU cache entries for DL embeddings

    # Batch processing
    frame_worker_threads: int = 4   # threads for parallel pHash computation
    batch_ingest_max_items: int = 20

    # Google AI (Gemini)
    google_api_key: str = ""        # Google AI Studio API key (optional)
    google_ai_enabled: bool = True  # enable Gemini when API key present
    gemini_model: str = "gemini-2.0-flash"

    @property
    def phash_dim(self) -> int:
        return self.hash_size * self.hash_size  # 256 for hash_size=16

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def frames_dir(self) -> Path:
        return self.data_dir / "frames"

    @property
    def indices_dir(self) -> Path:
        return self.data_dir / "indices"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def ensure_dirs(self) -> None:
        for d in [self.originals_dir, self.frames_dir, self.indices_dir, self.reports_dir]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
