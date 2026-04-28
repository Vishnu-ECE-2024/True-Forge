"""
System information endpoint.

GET /api/system-info  — Returns CPU/GPU status, model info, index statistics.
"""

import logging
import platform
from typing import Optional

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/system-info")
def system_info(request: Request) -> dict:
    """
    Return hardware, model, and index status for the running instance.

    Useful for:
    - Confirming GPU is being used (or why it is not)
    - Verifying DL embedding model loaded correctly
    - Checking index sizes before running searches
    """
    # Hardware
    cpu_info = platform.processor() or platform.machine()
    try:
        import psutil
        mem = psutil.virtual_memory()
        memory = {
            "total_gb": round(mem.total / 1024 ** 3, 1),
            "available_gb": round(mem.available / 1024 ** 3, 1),
            "used_percent": mem.percent,
        }
        cpu_count = psutil.cpu_count(logical=True)
    except ImportError:
        memory = {}
        cpu_count = None

    # Torch / GPU
    from src.services.embedding import get_device_info
    device_info = get_device_info()

    # FAISS indices
    faiss_index  = getattr(request.app.state, "faiss_index",  None)
    dl_index     = getattr(request.app.state, "dl_index",     None)

    indices = {}
    if faiss_index is not None:
        indices["phash"] = {
            "vectors": faiss_index.total_vectors,
            "dimension": faiss_index.dimension,
            "normalized": False,
        }
    if dl_index is not None:
        indices["dl_embedding"] = {
            "vectors": dl_index.total_vectors,
            "dimension": dl_index.dimension,
            "normalized": True,
        }

    # Embedding cache stats
    try:
        from src.services.cache import get_dl_cache, get_phash_cache
        cache_stats = {
            "phash_cache": get_phash_cache().stats(),
            "dl_cache":    get_dl_cache().stats(),
        }
    except Exception:
        cache_stats = {}

    return {
        "system": {
            "platform": platform.system(),
            "python_version": platform.python_version(),
            "cpu": cpu_info,
            "cpu_count": cpu_count,
            "memory": memory,
        },
        "compute": device_info,
        "indices": indices,
        "embedding_cache": cache_stats,
    }
