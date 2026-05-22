"""Behavioral smoke test for pyoas-generated output.

Closes the gap that allowed B-15..B-22 to ship: snapshots accept syntactically
valid output but never imported it, type-checked it, or pytest-ran it. This
suite generates a curated spec into a tmp directory once per session and runs
four checks against the result:

1. ``compileall`` — every ``.py`` file parses.
2. ``ruff --select=E,F --ignore=E501`` — zero lint violations in error classes.
3. ``importlib.import_module`` — every generated module imports cleanly.
4. Subprocess pytest with a ``AsyncMock`` service — generated tests pass.

Coverage matrix is the spec at ``tests/fixtures/smoke_spec.yaml``. When a new
scaffolder feature lands, extend that spec rather than adding more checks here.

Runs by default (``uv run pytest``); intentionally *not* marked
``@pytest.mark.integration`` because it must guard every merge, not only the
``--run-integration`` opt-in path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pyoas.core.cli import app

SMOKE_SPEC = Path(__file__).parents[1] / "fixtures" / "smoke_spec.yaml"


@pytest.fixture(scope="session")
def smoke_generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate the full smoke output once per session, return the workdir."""
    workdir = tmp_path_factory.mktemp("smoke")
    (workdir / "smoke.yaml").write_text(
        SMOKE_SPEC.read_text(encoding="utf-8"), encoding="utf-8"
    )
    config = {
        "spec": "smoke.yaml",
        "output": {
            "models": "src/generated/models",
            "routers": "src/generated/routers",
            # source_root="" gives src.X imports everywhere so a single
            # PYTHONPATH=tmp_path lets the subprocess pytest resolve all
            # generated modules.
            "source_root": "",
        },
        "model_config": {"extra": "ignore", "request_extra": "forbid"},
        "format": {"enabled": False},
        "services": {
            "generate": True,
            "output": "src/services",
            "import_path": "src.services",
            "overwrite": True,
        },
        "tests": {
            "generate": True,
            "output": "tests/generated",
            "overwrite": True,
            "not_found_exception": "HTTPException(status_code=404)",
        },
        "dependencies": {
            "generate": True,
            "output": "src/dependencies",
            "import_path": "src.dependencies",
            "overwrite": True,
        },
    }
    (workdir / "pyoas.yaml").write_text(yaml.dump(config), encoding="utf-8")

    runner = CliRunner()
    cwd = os.getcwd()
    try:
        os.chdir(workdir)
        result = runner.invoke(app, ["generate", "--config", "pyoas.yaml", "--quiet"])
    finally:
        os.chdir(cwd)
    if result.exit_code != 0:
        pytest.fail(
            f"pyoas generate failed (exit {result.exit_code})\n"
            f"output:\n{result.output}\n"
            f"exception: {result.exception!r}"
        )
    return workdir


def test_compileall(smoke_generated: Path) -> None:
    """Every generated .py file parses as valid Python."""
    targets = [str(smoke_generated / "src"), str(smoke_generated / "tests")]
    result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "-f", *targets],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"compileall failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_ruff_e_f_clean(smoke_generated: Path) -> None:
    """ruff finds no errors in the E or F class (skip E501 / I / UP / W)."""
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("ruff not on PATH")
    result = subprocess.run(
        [
            ruff,
            "check",
            "--select=E,F",
            "--ignore=E501",
            "--no-cache",
            "--isolated",
            str(smoke_generated / "src"),
            str(smoke_generated / "tests"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff found violations:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_every_module_imports(smoke_generated: Path) -> None:
    """Every generated module imports without error."""
    script = textwrap.dedent(
        """
        import importlib, json, sys
        from pathlib import Path

        root = Path(sys.argv[1])
        sys.path.insert(0, str(root))

        failures = []
        for f in sorted(root.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            rel = f.relative_to(root).with_suffix("")
            mod = ".".join(rel.parts)
            if mod.endswith(".__init__"):
                mod = mod.removesuffix(".__init__")
            try:
                importlib.import_module(mod)
            except Exception as exc:
                failures.append(f"{mod}: {type(exc).__name__}: {exc}")
        print(json.dumps(failures))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(smoke_generated)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"import smoke crashed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    failures: list[str] = json.loads(result.stdout.strip().splitlines()[-1])
    assert not failures, "Generated modules failed to import:\n  " + "\n  ".join(
        failures
    )


def test_generated_pytest_runs_clean(smoke_generated: Path) -> None:
    """The generated test tree passes when run with the scaffolded AsyncMock conftest."""
    env = {**os.environ, "PYTHONPATH": str(smoke_generated)}
    # --override-ini=addopts= clears the pyoas project's --cov flags so a stray
    # parent pyproject.toml lookup doesn't fail the subprocess. -p no:cacheprovider
    # avoids writing .pytest_cache into the smoke workdir.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(smoke_generated / "tests" / "generated"),
            "-p",
            "no:cacheprovider",
            "--override-ini=addopts=",
            "--rootdir",
            str(smoke_generated),
            "-q",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"generated tests failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
