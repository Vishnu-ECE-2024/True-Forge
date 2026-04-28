"""
Sports Media Protection System — FastAPI application entry point.

Architecture:
- FAISS indices (pHash + DL) loaded once at startup, shared via app.state
- DL embedding model pre-warmed in a background thread at startup
- PostgreSQL tables created/upgraded at startup
- Static frontend served from /ui
- Background tasks via FastAPI BackgroundTasks (no Redis needed for 1 operator)
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.analyze import router as analyze_router
from src.api.assets import router as assets_router
from src.api.health import router as health_router
from src.api.ingest import router as ingest_router
from src.api.monitor import router as monitor_router
from src.api.reports import router as reports_router
from src.api.search import router as search_router
from src.api.stats import router as stats_router
from src.api.system import router as system_router
from src.api.watermark import router as watermark_router
from src.core.config import settings
from src.db.database import init_db
from src.search.faiss_index import FaissIndex

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def _warmup_dl_model() -> None:
    """Pre-load DL embedding model in a daemon thread (avoids first-request latency)."""
    try:
        from src.services.embedding import get_embedding_model
        model = get_embedding_model()
        model.warmup()
        if model.available:
            logger.info(
                f"DL model '{model.model_name}' ready on {model.device} "
                f"({model.dim}-dim embeddings)"
            )
        else:
            logger.info("DL embeddings unavailable — running pHash-only mode")
    except Exception as e:
        logger.warning(f"DL model warmup failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    settings.ensure_dirs()
    logger.info(f"Data directory: {settings.data_dir}")

    # Database tables + schema upgrades
    init_db()

    # pHash FAISS index (primary, backward-compatible)
    app.state.faiss_index = FaissIndex(
        index_path=settings.faiss_index_path,
        dimension=settings.phash_dim,
        normalized_vectors=False,
    )
    logger.info(
        f"pHash index: {app.state.faiss_index.total_vectors} vectors "
        f"({settings.phash_dim}-dim)"
    )

    # DL embedding FAISS index (secondary, optional)
    app.state.dl_index = FaissIndex(
        index_path=settings.dl_index_path,
        dimension=settings.dl_embedding_dim,
        normalized_vectors=True,   # MobileNetV3 embeddings are L2-normalised
    )
    logger.info(
        f"DL index: {app.state.dl_index.total_vectors} vectors "
        f"({settings.dl_embedding_dim}-dim)"
    )

    # Pre-warm DL model in background (non-blocking)
    threading.Thread(target=_warmup_dl_model, daemon=True, name="dl-warmup").start()

    logger.info("Sports Media Protection API v2 started")
    yield

    logger.info("Sports Media Protection API shutting down")


app = FastAPI(
    title="Sports Media Protection System",
    description=(
        "Production-grade copyright protection for sports video content. "
        "Multi-modal fingerprinting (pHash + DL embeddings + audio), "
        "fusion scoring, rule-based decision engine, tamper detection."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
_allowed_origins: list[str] = ["*"] if _raw_origins == "*" else [o.strip() for o in _raw_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_raw_origins != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Existing API routes (backward-compatible)
app.include_router(health_router,    prefix="/api")
app.include_router(assets_router,    prefix="/api")
app.include_router(search_router,    prefix="/api")
app.include_router(watermark_router, prefix="/api")
app.include_router(monitor_router,   prefix="/api")
app.include_router(reports_router,   prefix="/api")
app.include_router(stats_router,     prefix="/api")

# New v2 routes
app.include_router(analyze_router,   prefix="/api")
app.include_router(system_router,    prefix="/api")
app.include_router(ingest_router,    prefix="/api")

# Frontend
if FRONTEND_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {"message": "API running. Docs at /docs"}
