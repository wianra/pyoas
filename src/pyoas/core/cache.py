"""
GenerationCache — load/save .pyoas_cache.json and compute per-tag content hashes.

Cache file schema (JSON object):
  {"pets": "<16-char hex>", "orders": "<16-char hex>", ...}

Each generator keeps its own cache file in its output directory, so no
namespace prefix is needed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path


def compute_config_hash(config: object) -> str:
    """Return a 16-char hex digest of the full config.

    Uses ``dataclasses.asdict`` for a deterministic dict representation,
    then JSON-serialises with sorted keys for cross-run stability.
    """
    raw = json.dumps(asdict(config), sort_keys=True, default=str)  # type: ignore[call-overload]
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def compute_tag_hash(tag_name: str, content_json: str, config_hash: str) -> str:
    """Return a 16-char hex digest of (tag_name + serialised spec content + config_hash).

    Args:
        tag_name:     The tag string (e.g. ``"pets"``).
        content_json: JSON-serialised representation of the spec data relevant to
                      this tag (schema dict for models; operations list for routers).
        config_hash:  Output of :func:`compute_config_hash`.
    """
    payload = tag_name + content_json + config_hash
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class GenerationCache:
    """Thin read/write wrapper around a ``.pyoas_cache.json`` file."""

    def __init__(self, cache_path: Path) -> None:
        self._path = cache_path
        self._data: dict[str, str] = {}
        self._dirty = False

    @classmethod
    def load(cls, cache_path: Path) -> GenerationCache:
        """Load from *cache_path* if it exists; otherwise return an empty cache.

        Corrupt or unreadable JSON is silently treated as an empty cache.
        """
        obj = cls(cache_path)
        if cache_path.exists():
            try:
                obj._data = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                obj._data = {}
        return obj

    def is_current(self, key: str, hash_value: str) -> bool:
        """Return ``True`` when *key* is stored and its value matches *hash_value*."""
        return self._data.get(key) == hash_value

    def update(self, key: str, hash_value: str) -> None:
        """Store *hash_value* for *key* and mark the cache dirty."""
        if self._data.get(key) != hash_value:
            self._data[key] = hash_value
            self._dirty = True

    def save(self) -> None:
        """Write the cache to disk.

        No-op when nothing has changed since load, so the file's mtime is
        not bumped on runs where no tag was regenerated.
        """
        if not self._dirty:
            return
        self._path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
