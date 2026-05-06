from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


LimitMode = Literal["path", "filename"]


@dataclass(frozen=True, slots=True)
class ScanOptions:
    source_dir: Path
    output_dir: Path
    max_path_length: int = 66
    max_filename_length: int = 66
    limit_mode: LimitMode = "path"
    in_place: bool = False


@dataclass(frozen=True, slots=True)
class PreviewItem:
    source_path: Path
    target_path: Path
    action: str
    status: str
    reason: str
    original_path_length: int
    original_name_length: int


@dataclass(frozen=True, slots=True)
class ExecutionSummary:
    processed: int
    changed: int
    skipped: int
    failed: int
