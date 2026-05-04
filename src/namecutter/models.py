from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ScanOptions:
    source_dir: Path
    output_dir: Path
    max_path_length: int = 66
    in_place: bool = False


@dataclass(frozen=True, slots=True)
class PreviewItem:
    source_path: Path
    target_path: Path
    action: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExecutionSummary:
    processed: int
    changed: int
    skipped: int
    failed: int

