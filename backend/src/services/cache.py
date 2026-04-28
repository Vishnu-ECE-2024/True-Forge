"""Thread-safe LRU cache for numpy embedding vectors."""

import threading
from collections import OrderedDict
from typing import Optional

import numpy as np


class EmbeddingCache:
    """Thread-safe LRU cache for numpy embedding vectors."""

    def __init__(self, max_size: int = 1000) -> None:
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._max_size = max_size
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[np.ndarray]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key].copy()
            self._misses += 1
            return None

    def put(self, key: str, vector: np.ndarray) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = vector.copy()
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def stats(self) -> dict:
        return {
            "size": self.size,
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 4),
        }


_phash_cache: Optional[EmbeddingCache] = None
_dl_cache: Optional[EmbeddingCache] = None


def get_phash_cache() -> EmbeddingCache:
    global _phash_cache
    if _phash_cache is None:
        _phash_cache = EmbeddingCache(max_size=2000)
    return _phash_cache


def get_dl_cache() -> EmbeddingCache:
    global _dl_cache
    if _dl_cache is None:
        _dl_cache = EmbeddingCache(max_size=500)
    return _dl_cache
