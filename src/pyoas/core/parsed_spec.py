"""ParsedSpec — a frozen value object holding both the raw and resolved OpenAPI dicts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .parser import SpecParser
from .resolver import resolve_refs

if TYPE_CHECKING:
    from .config import Config


@dataclass(frozen=True, slots=True)
class ParsedSpec:
    """Holds both the raw (unresolved) and fully-resolved OpenAPI spec dicts.

    Use ``ParsedSpec.from_config(cfg)`` to load and resolve the spec once, then
    pass the instance to ``ModelGenerator`` and ``RouterGenerator`` so the file
    is not read or resolved twice during a ``generate`` command.

    Attributes:
        raw:      The spec dict as read from disk, with ``$ref`` strings intact.
        resolved: The spec dict with all ``$ref`` pointers fully expanded.
        path:     Absolute path to the spec file (string, as Config stores it).
    """

    raw: dict[str, Any]
    resolved: dict[str, Any]
    path: str

    @classmethod
    def from_config(cls, cfg: Config) -> ParsedSpec:
        """Load and resolve the spec referenced by *cfg*."""
        raw = SpecParser(cfg.spec).load()
        return cls(raw=raw, resolved=resolve_refs(raw, cfg.spec), path=cfg.spec)

    @classmethod
    def from_path(cls, spec_path: str) -> ParsedSpec:
        """Load and resolve the spec at *spec_path* directly."""
        raw = SpecParser(spec_path).load()
        return cls(raw=raw, resolved=resolve_refs(raw, spec_path), path=spec_path)
