from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


class SpecParser:
    """
    Loads and validates an OpenAPI 3.0.x or 3.1.x spec from a JSON or YAML file.

    Call `.load()` to parse and validate the spec. The result is cached so
    subsequent calls return the same dict.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._raw: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        if self._raw is not None:
            return self._raw

        text = self._path.read_text(encoding="utf-8")
        match self._path.suffix.lower():
            case ".json":
                data = json.loads(text)
            case ".yaml" | ".yml":
                data = yaml.safe_load(text)
            case _:
                raise ValueError(
                    f"Unsupported spec format: {self._path.suffix!r}. "
                    "Expected .json, .yaml, or .yml"
                )

        _validate_spec(data)
        self._raw = data
        return data

    @property
    def openapi_version(self) -> str:
        if self._raw is None:
            raise RuntimeError("Call .load() before accessing openapi_version")
        return self._raw.get("openapi", "")

    @property
    def is_v31(self) -> bool:
        return self.openapi_version.startswith("3.1")

    @property
    def is_v30(self) -> bool:
        return self.openapi_version.startswith("3.0")


def _validate_spec(spec: dict[str, Any]) -> None:
    from openapi_spec_validator import validate

    validate(spec)
