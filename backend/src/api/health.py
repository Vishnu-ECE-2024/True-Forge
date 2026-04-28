"""Health check endpoint."""

import logging
from fastapi import APIRouter, Request

from src.core.models import HealthResponse
from src.db.database import check_db
from src.db.models import Asset
from src.db.database import get_db_session
from src.core.models import AssetStatus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check(request: Request) -> HealthResponse:
    """System health check — returns status of all subsystems."""

    db_ok = check_db()

    faiss_index = request.app.state.faiss_index
    faiss_ok = faiss_index is not None

    total_assets = 0
    indexed_assets = 0

    if db_ok:
        try:
            with get_db_session() as db:
                total_assets = db.query(Asset).count()
                indexed_assets = db.query(Asset).filter(
                    Asset.status == AssetStatus.READY
                ).count()
        except Exception as e:
            logger.warning(f"Could not count assets: {e}")

    return HealthResponse(
        status="ok" if db_ok and faiss_ok else "degraded",
        database="ok" if db_ok else "error",
        faiss_index=f"ok ({faiss_index.total_vectors} vectors)" if faiss_ok else "error",
        total_assets=total_assets,
        indexed_assets=indexed_assets,
    )
