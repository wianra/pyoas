from pathlib import Path
from textwrap import dedent

import pytest

from pyoas.core.config import Config, ModelConfig, load_config


def test_load_minimal_config(tmp_path: Path) -> None:
    cfg_file = tmp_path / "pyoas.yaml"
    cfg_file.write_text(
        dedent("""\
        spec: openapi.yaml
        output:
          models: src/generated/models
          routers: src/generated/routers
    """)
    )
    cfg = load_config(str(cfg_file))
    assert isinstance(cfg, Config)
    assert cfg.spec == str(tmp_path / "openapi.yaml")
    assert cfg.output.models == str(tmp_path / "src/generated/models")
    assert cfg.output.routers == str(tmp_path / "src/generated/routers")
    assert cfg.default_tag == "default"
    assert cfg.format.enabled is True


def test_load_full_config(tmp_path: Path) -> None:
    cfg_file = tmp_path / "pyoas.yaml"
    cfg_file.write_text(
        dedent("""\
        spec: api/openapi.yaml
        default_tag: untagged
        output:
          models: out/models
          routers: out/routers
        model_config:
          extra: forbid
          frozen: true
          populate_by_name: false
        fields:
          snake_case: false
          enums_as_literals: false
        format:
          enabled: false
        templates:
          models: custom/model_templates
          routers: custom/router_templates
        services:
          generate: true
          output: src/services
          overwrite: true
          import_path: myapp.services
    """)
    )
    cfg = load_config(str(cfg_file))
    assert cfg.spec == str(tmp_path / "api/openapi.yaml")
    assert cfg.default_tag == "untagged"
    assert cfg.model_config.extra == "forbid"
    assert cfg.model_config.frozen is True
    assert cfg.fields.snake_case is False
    assert cfg.fields.enums_as_literals is False
    assert cfg.format.enabled is False
    assert cfg.templates.models == str(tmp_path / "custom/model_templates")
    assert cfg.services.overwrite is True
    assert cfg.services.import_path == "myapp.services"


def test_unsupported_format(tmp_path: Path) -> None:
    cfg_file = tmp_path / "pyoas.toml"
    cfg_file.write_text("[project]\nspec = 'openapi.yaml'\n")
    with pytest.raises(ValueError, match="Unsupported config format"):
        load_config(str(cfg_file))


def test_missing_spec_key(tmp_path: Path) -> None:
    cfg_file = tmp_path / "pyoas.yaml"
    cfg_file.write_text("output:\n  models: out/models\n")
    with pytest.raises((ValueError, KeyError)):
        load_config(str(cfg_file))


def test_webhooks_config_defaults() -> None:
    cfg = Config(spec="openapi.yaml")
    assert cfg.webhooks.generate is False


def test_webhooks_config_loaded_from_yaml(tmp_path: Path) -> None:
    cfg_file = tmp_path / "pyoas.yaml"
    cfg_file.write_text(
        dedent("""\
        spec: openapi.yaml
        webhooks:
          generate: true
    """)
    )
    cfg = load_config(str(cfg_file))
    assert cfg.webhooks.generate is True


def test_cli_diff_up_to_date(petstore_30: Path) -> None:
    """pyoas diff exits 0 when generated output is already up to date."""
    import tempfile

    from typer.testing import CliRunner

    from pyoas.core.cli import app

    with tempfile.TemporaryDirectory() as tmp:
        # Generate once so output is current
        from pyoas.core.config import Config, FieldsConfig, FormatConfig, OutputConfig

        cfg = Config(
            spec=str(petstore_30),
            output=OutputConfig(models=f"{tmp}/models", routers=f"{tmp}/routers"),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
        )
        from pyoas.fastapi import RouterGenerator
        from pyoas.models import ModelGenerator

        ModelGenerator(cfg).generate()
        RouterGenerator(cfg).generate()

        # Write a minimal config file for the CLI
        import yaml

        config_file = f"{tmp}/pyoas.yaml"
        with open(config_file, "w") as f:
            yaml.dump(
                {
                    "spec": str(petstore_30),
                    "output": {"models": f"{tmp}/models", "routers": f"{tmp}/routers"},
                    "format": {"enabled": False},
                },
                f,
            )

        runner = CliRunner()
        result = runner.invoke(app, ["diff", "--config", config_file])
        assert result.exit_code == 0, result.output
        assert "up to date" in result.output


def test_cli_diff_detects_stale(petstore_30: Path) -> None:
    """pyoas diff exits 1 when a generated file is stale."""
    import tempfile

    import yaml
    from typer.testing import CliRunner

    from pyoas.core.cli import app

    with tempfile.TemporaryDirectory() as tmp:
        from pyoas.core.config import Config, FieldsConfig, FormatConfig, OutputConfig
        from pyoas.fastapi import RouterGenerator
        from pyoas.models import ModelGenerator

        cfg = Config(
            spec=str(petstore_30),
            output=OutputConfig(models=f"{tmp}/models", routers=f"{tmp}/routers"),
            fields=FieldsConfig(snake_case=True, enums_as_literals=True),
            format=FormatConfig(enabled=False),
        )
        ModelGenerator(cfg).generate()
        RouterGenerator(cfg).generate()

        # Corrupt a generated file to simulate staleness
        stale = Path(tmp) / "models" / "pets.py"
        stale.write_text(stale.read_text() + "\n# stale\n")

        config_file = f"{tmp}/pyoas.yaml"
        with open(config_file, "w") as f:
            yaml.dump(
                {
                    "spec": str(petstore_30),
                    "output": {"models": f"{tmp}/models", "routers": f"{tmp}/routers"},
                    "format": {"enabled": False},
                },
                f,
            )

        runner = CliRunner()
        result = runner.invoke(app, ["diff", "--config", config_file])
        assert result.exit_code == 1
        assert "modified" in result.output


def test_router_config_defaults() -> None:
    cfg = Config(spec="openapi.yaml")
    assert cfg.router.response_model_exclude_none is False
    assert cfg.router.response_model_exclude_unset is False


def test_router_config_loaded_from_yaml(tmp_path: Path) -> None:
    cfg_file = tmp_path / "pyoas.yaml"
    cfg_file.write_text(
        dedent("""\
        spec: openapi.yaml
        router:
          response_model_exclude_none: true
          response_model_exclude_unset: true
    """)
    )
    cfg = load_config(str(cfg_file))
    assert cfg.router.response_model_exclude_none is True
    assert cfg.router.response_model_exclude_unset is True


def test_model_config_include_unreferenced_defaults_false() -> None:
    cfg = Config(spec="openapi.yaml")
    assert cfg.model_config.include_unreferenced is False


def test_model_config_include_unreferenced_loaded_from_yaml(tmp_path: Path) -> None:
    cfg_file = tmp_path / "pyoas.yaml"
    cfg_file.write_text(
        dedent("""\
        spec: openapi.yaml
        model_config:
          include_unreferenced: true
    """)
    )
    cfg = load_config(str(cfg_file))
    assert cfg.model_config.include_unreferenced is True


# ---------------------------------------------------------------------------
# Config validation error tests (T-13 / A-09)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["ignore", "allow", "forbid"])
def test_valid_extra_values_accepted(value: str) -> None:
    cfg = Config(spec="openapi.yaml", model_config=ModelConfig(extra=value))
    assert cfg.model_config.extra == value


@pytest.mark.parametrize("value", ["FORBID", "Ignore", "strict", ""])
def test_invalid_extra_value_raises(tmp_path: Path, value: str) -> None:
    cfg_file = tmp_path / "pyoas.yaml"
    cfg_file.write_text(f"spec: openapi.yaml\nmodel_config:\n  extra: {value!r}\n")
    with pytest.raises(ValueError, match="model_config.extra"):
        load_config(str(cfg_file))


@pytest.mark.parametrize("value", ["FORBID", "Ignore", "strict", ""])
def test_invalid_request_extra_value_raises(tmp_path: Path, value: str) -> None:
    cfg_file = tmp_path / "pyoas.yaml"
    cfg_file.write_text(
        f"spec: openapi.yaml\nmodel_config:\n  request_extra: {value!r}\n"
    )
    with pytest.raises(ValueError, match="model_config.request_extra"):
        load_config(str(cfg_file))


def test_invalid_extra_value_raises_on_direct_instantiation() -> None:
    with pytest.raises(ValueError, match="model_config.extra"):
        ModelConfig(extra="invalid")
