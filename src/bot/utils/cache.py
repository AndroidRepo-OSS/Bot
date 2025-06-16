# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class MemoryCache:
    def __init__(self, default_ttl: int = 3600, max_size: int = 1000) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._default_ttl = default_ttl
        self._max_size = max_size

    @staticmethod
    def _generate_key(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def get(self, url: str) -> Any | None:
        key = self._generate_key(url)
        if key not in self._cache:
            return None

        data = self._cache[key]
        if time.time() > data["expires_at"]:
            del self._cache[key]
            return None

        data["access_time"] = time.time()
        logger.info("Cache hit for URL: %s", url)
        return data["value"]

    def set(self, url: str, value: Any, ttl: int | None = None) -> None:
        if len(self._cache) >= self._max_size:
            self._evict_lru()

        key = self._generate_key(url)
        expires_at = time.time() + (ttl or self._default_ttl)

        self._cache[key] = {
            "value": value,
            "expires_at": expires_at,
            "access_time": time.time(),
        }

        logger.info("Cached data for URL: %s", url)

    def _evict_lru(self) -> None:
        if not self._cache:
            return

        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].get("access_time", 0))
        del self._cache[oldest_key]

    def delete(self, url: str) -> None:
        key = self._generate_key(url)
        if key in self._cache:
            del self._cache[key]
            logger.info("Deleted cache for URL: %s", url)

    def clear(self) -> None:
        self._cache.clear()
        logger.info("Cache cleared")

    def cleanup_expired(self) -> None:
        current_time = time.time()
        expired_keys = [
            key for key, data in self._cache.items() if current_time > data["expires_at"]
        ]

        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            logger.info("Cleaned up %d expired cache entries", len(expired_keys))


repository_cache = MemoryCache()
