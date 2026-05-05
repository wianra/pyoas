from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScaffoldResult:
    """Aggregated outcome of a scaffolder run."""

    wrote: int = 0
    skipped: int = 0
    appended_items: int = 0  # total methods/classes added across all appended files
    appended_files: list[str] = field(default_factory=list)  # tag dirnames
