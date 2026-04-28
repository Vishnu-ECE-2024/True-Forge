"""
FAISS-based vector index for fingerprint search.

Supports two index types depending on the vector type:
  - pHash vectors (raw 0/1 floats): IndexFlatL2, similarity = 1 - dist/dim
  - DL embeddings (L2-normalized):  IndexFlatIP, similarity = inner product

Both types are thread-safe and persist to disk on every add().

Scale limits:
  - Exact search up to ~50k vectors without tuning.
  - At 100k+: upgrade to IndexIVFFlat (change one line below).
"""

import logging
import threading
from pathlib import Path
from typing import NamedTuple

import faiss
import numpy as np

logger = logging.getLogger(__name__)


class SearchHit(NamedTuple):
    asset_id: str
    distance: float
    similarity: float  # 0.0–1.0 (higher = more similar)


class FaissIndex:
    """
    Thread-safe FAISS index with asset_id ↔ row_id mapping.
    One instance per index type (pHash / DL embeddings).
    """

    def __init__(
        self,
        index_path: Path,
        dimension: int = 256,
        normalized_vectors: bool = False,
    ) -> None:
        """
        Args:
            index_path: Where to persist the index file.
            dimension: Vector dimensionality.
            normalized_vectors: If True, uses IndexFlatIP (inner product = cosine
                similarity for unit vectors). If False, uses IndexFlatL2.
        """
        self._index_path = index_path
        self._dim = dimension
        self._normalized = normalized_vectors
        self._lock = threading.Lock()
        self._row_to_asset: list[str] = []
        self._index: faiss.Index = self._make_index()
        self._load()

    def _make_index(self) -> faiss.Index:
        if self._normalized:
            return faiss.IndexFlatIP(self._dim)   # cosine sim for unit vectors
        return faiss.IndexFlatL2(self._dim)

    def _load(self) -> None:
        mapping_path = self._index_path.with_suffix(".map")
        if self._index_path.exists() and mapping_path.exists():
            try:
                self._index = faiss.read_index(str(self._index_path))
                with open(mapping_path, "r") as f:
                    self._row_to_asset = [line.strip() for line in f if line.strip()]
                logger.info(
                    f"Loaded FAISS index ({self._dim}-dim): "
                    f"{self._index.ntotal} vectors from {self._index_path}"
                )
            except Exception as e:
                logger.error(f"Failed to load FAISS index: {e}. Starting fresh.")
                self._index = self._make_index()
                self._row_to_asset = []
        else:
            logger.info(
                f"No FAISS index at {self._index_path}. "
                f"Starting fresh ({self._dim}-dim)."
            )

    def _save(self) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self._index_path))
        mapping_path = self._index_path.with_suffix(".map")
        with open(mapping_path, "w") as f:
            f.write("\n".join(self._row_to_asset))
        logger.debug(f"Saved FAISS index: {self._index.ntotal} vectors")

    def _dist_to_similarity(self, dist: float) -> float:
        if self._normalized:
            # IndexFlatIP returns inner product (= cosine for unit vectors): [−1, 1]
            return max(0.0, float(dist))
        else:
            # IndexFlatL2: max L2 distance for bit vectors ≈ dimension
            return max(0.0, 1.0 - dist / self._dim)

    def add(self, vector: np.ndarray, asset_id: str) -> int:
        """
        Add a fingerprint vector to the index.
        Returns the row_id assigned.
        """
        if vector.shape != (self._dim,):
            raise ValueError(
                f"Expected vector shape ({self._dim},), got {vector.shape}"
            )
        with self._lock:
            row_id = self._index.ntotal
            self._index.add(vector.reshape(1, -1).astype(np.float32))
            self._row_to_asset.append(asset_id)
            self._save()
        logger.debug(f"Added {asset_id} to FAISS at row {row_id}")
        return row_id

    def search(self, query_vector: np.ndarray, top_k: int = 10) -> list[SearchHit]:
        """
        Search for the top_k nearest vectors.
        Returns SearchHits ordered by similarity (highest first).
        """
        if self._index.ntotal == 0:
            return []
        if query_vector.shape != (self._dim,):
            raise ValueError(
                f"Expected query shape ({self._dim},), got {query_vector.shape}"
            )

        effective_k = min(top_k, self._index.ntotal)
        with self._lock:
            scores, indices = self._index.search(
                query_vector.reshape(1, -1).astype(np.float32),
                effective_k,
            )

        results = []
        for raw_score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            asset_id = self._row_to_asset[idx]
            if not asset_id:
                continue  # deleted slot
            sim = round(self._dist_to_similarity(raw_score), 4)
            results.append(SearchHit(
                asset_id=asset_id,
                distance=float(raw_score),
                similarity=sim,
            ))

        results.sort(key=lambda x: x.similarity, reverse=True)
        return results

    def get_vector(self, row_id: int) -> np.ndarray:
        """Retrieve the stored vector for a given row_id."""
        vector = np.zeros(self._dim, dtype=np.float32)
        with self._lock:
            self._index.reconstruct(row_id, vector)
        return vector

    def remove(self, row_id: int) -> None:
        """
        Mark a slot as empty. IndexFlatL2 does not support in-place removal —
        the mapping slot is zeroed so search results will skip it.
        Full rebuild is required for production cleanup.
        """
        with self._lock:
            if row_id < len(self._row_to_asset):
                self._row_to_asset[row_id] = ""
                self._save()

    @property
    def total_vectors(self) -> int:
        return self._index.ntotal

    @property
    def dimension(self) -> int:
        return self._dim
