from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Callable, Iterator
import os
import shutil
import uuid

from .models import ExecutionSummary, LimitMode, PreviewItem, ScanOptions

_PROGRESS_BATCH_SIZE = 250
ProgressCallback = Callable[[str, int, int, int], None]


@dataclass(frozen=True, slots=True)
class _CandidatePlan:
    name: str
    was_shortened: bool
    used_counter: bool


def build_preview(options: ScanOptions) -> list[PreviewItem]:
    return list(iter_preview(options))


def iter_preview(options: ScanOptions) -> Iterator[PreviewItem]:
    source_dir, output_dir = _resolve_scan_roots(options)

    used_names: dict[Path, set[str]] = defaultdict(set)
    seeded_parents: set[Path] = set()

    for source_path in _iter_source_files(source_dir):
        relative_parent = source_path.parent.relative_to(source_dir)
        target_parent = output_dir / relative_parent

        if target_parent not in seeded_parents:
            seeded_parents.add(target_parent)
            if not options.in_place and target_parent.exists():
                used_names[target_parent].update(
                    child.name.casefold()
                    for child in target_parent.iterdir()
                    if child.is_file()
                )

        candidate = _plan_target_name(
            target_parent=target_parent,
            original_name=source_path.name,
            limit_mode=options.limit_mode,
            max_path_length=options.max_path_length,
            max_filename_length=options.max_filename_length,
            reserved_names=used_names[target_parent],
        )

        stem, _ = _split_name(source_path.name)
        original_name_length = len(stem)

        if candidate is None:
            yield PreviewItem(
                source_path=source_path,
                target_path=target_parent / source_path.name,
                action="skip",
                status="skip",
                reason=_build_skip_reason(options.limit_mode),
                original_path_length=len(str(source_path)),
                original_name_length=original_name_length,
            )
            continue

        target_path = target_parent / candidate.name
        used_names[target_parent].add(candidate.name.casefold())
        yield PreviewItem(
            source_path=source_path,
            target_path=target_path,
            action=_determine_action(source_path, target_path, options.in_place),
            status="ready",
            reason=_build_reason(candidate, source_path.name, options.limit_mode),
            original_path_length=len(str(source_path)),
            original_name_length=original_name_length,
        )


def apply_preview(preview: list[PreviewItem]) -> ExecutionSummary:
    processed = len(preview)
    skipped = sum(1 for item in preview if item.status == "skip")
    changed = 0

    rename_items = [item for item in preview if item.action == "rename"]
    copy_items = [item for item in preview if item.action == "copy"]

    staged_renames: list[tuple[Path, Path]] = []

    for item in rename_items:
        temp_path = _make_temp_path(item.source_path)
        item.source_path.rename(temp_path)
        staged_renames.append((temp_path, item.target_path))

    for temp_path, target_path in staged_renames:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.rename(target_path)
        changed += 1

    for item in copy_items:
        item.target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.source_path, item.target_path)
        changed += 1

    return ExecutionSummary(
        processed=processed,
        changed=changed,
        skipped=skipped,
        failed=0,
    )


def apply_options(
    options: ScanOptions,
    progress_callback: ProgressCallback | None = None,
) -> ExecutionSummary:
    if options.in_place:
        return _apply_in_place_options(options, progress_callback)
    return _apply_copy_options(options, progress_callback)


def _apply_copy_options(
    options: ScanOptions,
    progress_callback: ProgressCallback | None,
) -> ExecutionSummary:
    processed = 0
    changed = 0
    skipped = 0

    for item in iter_preview(options):
        processed += 1
        if item.status == "skip":
            skipped += 1
            _report_progress(
                progress_callback,
                "apply",
                processed,
                changed,
                skipped,
                progress_counter=processed,
            )
            continue

        item.target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.source_path, item.target_path)
        changed += 1
        _report_progress(
            progress_callback,
            "apply",
            processed,
            changed,
            skipped,
            progress_counter=processed,
        )

    _report_progress(progress_callback, "apply", processed, changed, skipped, force=True)
    return ExecutionSummary(
        processed=processed,
        changed=changed,
        skipped=skipped,
        failed=0,
    )


def _apply_in_place_options(
    options: ScanOptions,
    progress_callback: ProgressCallback | None,
) -> ExecutionSummary:
    processed = 0
    skipped = 0
    changed = 0
    rename_items: list[PreviewItem] = []

    for item in iter_preview(options):
        processed += 1
        if item.status == "skip":
            skipped += 1
        elif item.action == "rename":
            rename_items.append(item)

        _report_progress(
            progress_callback,
            "scan",
            processed,
            changed,
            skipped,
            progress_counter=processed,
        )

    staged_renames: list[tuple[Path, Path]] = []

    for item in rename_items:
        temp_path = _make_temp_path(item.source_path)
        item.source_path.rename(temp_path)
        staged_renames.append((temp_path, item.target_path))

    for temp_path, target_path in staged_renames:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.rename(target_path)
        changed += 1
        _report_progress(
            progress_callback,
            "apply",
            processed,
            changed,
            skipped,
            progress_counter=changed,
        )

    _report_progress(progress_callback, "apply", processed, changed, skipped, force=True)
    return ExecutionSummary(
        processed=processed,
        changed=changed,
        skipped=skipped,
        failed=0,
    )


def _resolve_scan_roots(options: ScanOptions) -> tuple[Path, Path]:
    source_dir = options.source_dir.expanduser().resolve(strict=False)
    output_dir = (
        source_dir if options.in_place else options.output_dir.expanduser().resolve(strict=False)
    )

    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source directory is not a directory: {source_dir}")

    return source_dir, output_dir


def _iter_source_files(source_dir: Path) -> Iterator[Path]:
    for root_text, dirnames, filenames in os.walk(source_dir):
        dirnames.sort()
        filenames.sort()
        root_path = Path(root_text)
        for filename in filenames:
            yield root_path / filename


def _determine_action(source_path: Path, target_path: Path, in_place: bool) -> str:
    if in_place:
        return "keep" if source_path == target_path else "rename"
    return "copy"


def _build_reason(candidate: _CandidatePlan, original_name: str, limit_mode: LimitMode) -> str:
    subject = "path limit" if limit_mode == "path" else "file name limit"
    ready_text = "Path is within limit." if limit_mode == "path" else "File name is within limit."

    if not candidate.was_shortened and not candidate.used_counter:
        return ready_text
    if candidate.used_counter and candidate.was_shortened:
        return f"Trimmed '{original_name}' and added a numeric suffix to fit the {subject}."
    if candidate.used_counter:
        return f"Added a numeric suffix to fit the {subject}."
    return f"Trimmed '{original_name}' to fit the {subject}."


def _build_skip_reason(limit_mode: LimitMode) -> str:
    if limit_mode == "filename":
        return "Cannot fit within the file name limit while keeping the name unique."
    return "Cannot fit within the path limit while keeping folders."


def _plan_target_name(
    *,
    target_parent: Path,
    original_name: str,
    limit_mode: LimitMode,
    max_path_length: int,
    max_filename_length: int,
    reserved_names: set[str],
) -> _CandidatePlan | None:
    stem, suffix = _split_name(original_name)
    target_parent_text = str(target_parent)

    base_stem_length = _best_stem_length(
        stem=stem,
        suffix=suffix,
        counter_text="",
        target_parent_text=target_parent_text,
        limit_mode=limit_mode,
        max_path_length=max_path_length,
        max_filename_length=max_filename_length,
    )
    if base_stem_length is None:
        return None

    base_name = f"{stem[:base_stem_length]}{suffix}"
    if base_name.casefold() not in reserved_names:
        return _CandidatePlan(
            name=base_name,
            was_shortened=base_stem_length < len(stem),
            used_counter=False,
        )

    for counter_index in count(1):
        counter_text = f"_{counter_index}"
        stem_length = _best_stem_length(
            stem=stem,
            suffix=suffix,
            counter_text=counter_text,
            target_parent_text=target_parent_text,
            limit_mode=limit_mode,
            max_path_length=max_path_length,
            max_filename_length=max_filename_length,
        )
        if stem_length is None:
            return None

        candidate_name = f"{stem[:stem_length]}{counter_text}{suffix}"
        if candidate_name.casefold() not in reserved_names:
            return _CandidatePlan(
                name=candidate_name,
                was_shortened=stem_length < len(stem),
                used_counter=True,
            )

    return None


def _best_stem_length(
    *,
    stem: str,
    suffix: str,
    counter_text: str,
    target_parent_text: str,
    limit_mode: LimitMode,
    max_path_length: int,
    max_filename_length: int,
) -> int | None:
    for stem_length in range(len(stem), 0, -1):
        if _fits_candidate_name(
            stem=stem,
            stem_length=stem_length,
            suffix=suffix,
            counter_text=counter_text,
            target_parent_text=target_parent_text,
            limit_mode=limit_mode,
            max_path_length=max_path_length,
            max_filename_length=max_filename_length,
        ):
            return stem_length
    return None


def _fits_candidate_name(
    *,
    stem: str,
    stem_length: int,
    suffix: str,
    counter_text: str,
    target_parent_text: str,
    limit_mode: LimitMode,
    max_path_length: int,
    max_filename_length: int,
) -> bool:
    if limit_mode == "filename":
        return stem_length + len(counter_text) <= max_filename_length

    candidate_name = f"{stem[:stem_length]}{counter_text}{suffix}"
    return _candidate_path_length(target_parent_text, candidate_name) <= max_path_length


def _candidate_path_length(target_parent_text: str, candidate_name: str) -> int:
    separator = "" if target_parent_text.endswith(("\\", "/")) else os.sep
    return len(target_parent_text) + len(separator) + len(candidate_name)


def _split_name(filename: str) -> tuple[str, str]:
    suffixes = Path(filename).suffixes
    suffix = "".join(suffixes)
    if not suffix:
        return filename, ""

    stem = filename[: -len(suffix)]
    return (stem or filename, suffix)


def _report_progress(
    progress_callback: ProgressCallback | None,
    phase: str,
    processed: int,
    changed: int,
    skipped: int,
    *,
    progress_counter: int | None = None,
    force: bool = False,
) -> None:
    if progress_callback is None:
        return
    counter = processed if progress_counter is None else progress_counter
    if not force and counter % _PROGRESS_BATCH_SIZE != 0:
        return
    progress_callback(phase, processed, changed, skipped)


def _make_temp_path(source_path: Path) -> Path:
    while True:
        temp_name = f".namecutter-{uuid.uuid4().hex}.tmp"
        temp_path = source_path.with_name(temp_name)
        if not temp_path.exists():
            return temp_path
