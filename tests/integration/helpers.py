"""Shared helpers for integration tests."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from pyoas.core.cli import app

runner = CliRunner()


def write_integration_config(tmp_path: Path, spec_path: Path) -> Path:
    """Write a minimal pyoas.yaml pointing at *spec_path* and return its path."""
    data: dict = {
        "spec": str(spec_path),
        "output": {
            "models": str(tmp_path / "models"),
            "routers": str(tmp_path / "routers"),
        },
        "format": {"enabled": False},
    }
    cfg = tmp_path / "pyoas.yaml"
    cfg.write_text(yaml.dump(data), encoding="utf-8")
    return cfg


def assert_generate_succeeds(cfg_path: Path) -> tuple[Path, Path]:
    """Invoke ``generate`` against *cfg_path* and return ``(models_dir, routers_dir)``.

    Raises ``AssertionError`` if the command exits non-zero.
    """
    result = runner.invoke(app, ["generate", "--config", str(cfg_path)])
    assert result.exit_code == 0, (
        f"generate failed (exit_code={result.exit_code})\n"
        f"--- output ---\n{result.output}"
    )
    models_dir = cfg_path.parent / "models"
    routers_dir = cfg_path.parent / "routers"
    return models_dir, routers_dir
