from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import count
from pathlib import Path
import shutil
import uuid

from .models import ExecutionSummary, PreviewItem, ScanOptions


@dataclass(frozen=True, slots=True)
class _CandidatePlan:
    name: str
    was_shortened: bool
    used_counter: bool


def build_preview(options: ScanOptions) -> list[PreviewItem]:
    source_dir = options.source_dir.resolve(strict=False)
    output_dir = (
        source_dir if options.in_place else options.output_dir.resolve(strict=False)
    )

    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source directory is not a directory: {source_dir}")

    used_names: dict[Path, set[str]] = defaultdict(set)
    seeded_parents: set[Path] = set()
    preview: list[PreviewItem] = []

    for source_path in sorted(path for path in source_dir.rglob("*") if path.is_file()):
        relative_path = source_path.relative_to(source_dir)
        target_parent = (output_dir / relative_path.parent).resolve(strict=False)

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
            max_path_length=options.max_path_length,
            reserved_names=used_names[target_parent],
        )

        if candidate is None:
            preview.append(
                PreviewItem(
                    source_path=source_path,
                    target_path=target_parent / source_path.name,
                    action="skip",
                    status="skip",
                    reason="Cannot fit within the path limit while keeping folders.",
                )
            )
            continue

        target_path = target_parent / candidate.name
        used_names[target_parent].add(candidate.name.casefold())
        preview.append(
            PreviewItem(
                source_path=source_path,
                target_path=target_path,
                action=_determine_action(source_path, target_path, options.in_place),
                status="ready",
                reason=_build_reason(candidate, source_path.name),
            )
        )

    return preview


def apply_preview(preview: list[PreviewItem]) -> ExecutionSummary:
    processed = len(preview)
    skipped = sum(1 for item in preview if item.status == "skip")
    changed = 0
    failed = 0

    rename_items = [item for item in preview if item.action == "rename"]
    copy_items = [item for item in preview if item.action == "copy"]

    staged_renames: list[tuple[Path, Path]] = []

    try:
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
    except OSError:
        failed = len(rename_items) + len(copy_items) - changed
        raise

    return ExecutionSummary(
        processed=processed,
        changed=changed,
        skipped=skipped,
        failed=failed,
    )


def _determine_action(source_path: Path, target_path: Path, in_place: bool) -> str:
    if in_place:
        return "keep" if source_path == target_path else "rename"
    return "copy"


def _build_reason(candidate: _CandidatePlan, original_name: str) -> str:
    if not candidate.was_shortened and not candidate.used_counter:
        return "Path is within limit."
    if candidate.used_counter and candidate.was_shortened:
        return f"Trimmed '{original_name}' and added a numeric suffix to avoid collisions."
    if candidate.used_counter:
        return "Added a numeric suffix to avoid collisions."
    return f"Trimmed '{original_name}' to fit the path limit."


def _plan_target_name(
    *,
    target_parent: Path,
    original_name: str,
    max_path_length: int,
    reserved_names: set[str],
) -> _CandidatePlan | None:
    stem, suffix = _split_name(original_name)

    base_stem_length = _best_stem_length(
        stem=stem,
        suffix=suffix,
        counter_text="",
        target_parent=target_parent,
        max_path_length=max_path_length,
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
            target_parent=target_parent,
            max_path_length=max_path_length,
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


def _path_length(path: Path) -> int:
    return len(str(path.resolve(strict=False)))


def _best_stem_length(
    *,
    stem: str,
    suffix: str,
    counter_text: str,
    target_parent: Path,
    max_path_length: int,
) -> int | None:
    for stem_length in range(len(stem), 0, -1):
        candidate_name = f"{stem[:stem_length]}{counter_text}{suffix}"
        if _path_length(target_parent / candidate_name) <= max_path_length:
            return stem_length
    return None


def _split_name(filename: str) -> tuple[str, str]:
    suffixes = Path(filename).suffixes
    suffix = "".join(suffixes)
    if not suffix:
        return filename, ""

    stem = filename[: -len(suffix)]
    return (stem or filename, suffix)


def _make_temp_path(source_path: Path) -> Path:
    while True:
        temp_name = f".namecutter-{uuid.uuid4().hex}.tmp"
        temp_path = source_path.with_name(temp_name)
        if not temp_path.exists():
            return temp_path
