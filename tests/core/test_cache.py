"""Tests for pyoas.core.cache — GenerationCache and hash helpers."""

from __future__ import annotations

import json
from pathlib import Path

from pyoas.core.cache import GenerationCache, compute_config_hash, compute_tag_hash
from pyoas.core.config import Config

# ---------------------------------------------------------------------------
# compute_config_hash
# ---------------------------------------------------------------------------


def test_compute_config_hash_is_stable() -> None:
    cfg = Config(spec="openapi.yaml")
    assert compute_config_hash(cfg) == compute_config_hash(cfg)


def test_compute_config_hash_returns_16_char_hex() -> None:
    result = compute_config_hash(Config(spec="openapi.yaml"))
    assert len(result) == 16
    assert all(c in "0123456789abcdef" for c in result)


def test_compute_config_hash_changes_on_config_change() -> None:
    cfg1 = Config(spec="openapi.yaml")
    cfg2 = Config(spec="other.yaml")
    assert compute_config_hash(cfg1) != compute_config_hash(cfg2)


# ---------------------------------------------------------------------------
# compute_tag_hash
# ---------------------------------------------------------------------------


def test_compute_tag_hash_is_stable() -> None:
    h = compute_tag_hash("pets", '{"schemas":{}}', "abc123")
    assert compute_tag_hash("pets", '{"schemas":{}}', "abc123") == h


def test_compute_tag_hash_returns_16_char_hex() -> None:
    result = compute_tag_hash("pets", "{}", "conf")
    assert len(result) == 16
    assert all(c in "0123456789abcdef" for c in result)


def test_compute_tag_hash_sensitive_to_tag_name() -> None:
    base = compute_tag_hash("pets", "{}", "conf")
    assert compute_tag_hash("orders", "{}", "conf") != base


def test_compute_tag_hash_sensitive_to_content() -> None:
    base = compute_tag_hash("pets", '{"a":1}', "conf")
    assert compute_tag_hash("pets", '{"a":2}', "conf") != base


def test_compute_tag_hash_sensitive_to_config_hash() -> None:
    base = compute_tag_hash("pets", "{}", "conf1")
    assert compute_tag_hash("pets", "{}", "conf2") != base


# ---------------------------------------------------------------------------
# GenerationCache — load
# ---------------------------------------------------------------------------


def test_load_nonexistent_path_returns_empty_cache(tmp_path: Path) -> None:
    cache = GenerationCache.load(tmp_path / "nonexistent.json")
    assert not cache.is_current("pets", "abc")


def test_load_restores_stored_values(tmp_path: Path) -> None:
    path = tmp_path / ".pyoas_cache.json"
    path.write_text(json.dumps({"pets": "deadbeef12345678"}), encoding="utf-8")
    cache = GenerationCache.load(path)
    assert cache.is_current("pets", "deadbeef12345678")


def test_load_handles_corrupt_json_silently(tmp_path: Path) -> None:
    path = tmp_path / ".pyoas_cache.json"
    path.write_text("not json!!!", encoding="utf-8")
    cache = GenerationCache.load(path)  # must not raise
    assert not cache.is_current("pets", "anything")


# ---------------------------------------------------------------------------
# GenerationCache — is_current
# ---------------------------------------------------------------------------


def test_is_current_true_when_matching(tmp_path: Path) -> None:
    path = tmp_path / ".pyoas_cache.json"
    path.write_text(json.dumps({"pets": "aabbccdd11223344"}), encoding="utf-8")
    cache = GenerationCache.load(path)
    assert cache.is_current("pets", "aabbccdd11223344")


def test_is_current_false_for_wrong_hash(tmp_path: Path) -> None:
    path = tmp_path / ".pyoas_cache.json"
    path.write_text(json.dumps({"pets": "aabbccdd11223344"}), encoding="utf-8")
    cache = GenerationCache.load(path)
    assert not cache.is_current("pets", "wronghash12345678")


def test_is_current_false_for_missing_key(tmp_path: Path) -> None:
    cache = GenerationCache.load(tmp_path / "missing.json")
    assert not cache.is_current("pets", "anything")


# ---------------------------------------------------------------------------
# GenerationCache — update + save
# ---------------------------------------------------------------------------


def test_save_writes_json_to_disk(tmp_path: Path) -> None:
    path = tmp_path / ".pyoas_cache.json"
    cache = GenerationCache.load(path)
    cache.update("pets", "aabbccdd11223344")
    cache.save()
    data = json.loads(path.read_text())
    assert data["pets"] == "aabbccdd11223344"


def test_save_noop_when_nothing_changed(tmp_path: Path) -> None:
    path = tmp_path / ".pyoas_cache.json"
    cache = GenerationCache.load(path)
    cache.save()
    assert not path.exists()


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / ".pyoas_cache.json"

    cache = GenerationCache.load(path)
    cache.update("pets", "aabbccdd11223344")
    cache.update("orders", "11223344aabbccdd")
    cache.save()

    reloaded = GenerationCache.load(path)
    assert reloaded.is_current("pets", "aabbccdd11223344")
    assert reloaded.is_current("orders", "11223344aabbccdd")
    assert not reloaded.is_current("unknown", "anything")
