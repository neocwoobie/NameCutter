from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from namecutter.engine import apply_options, apply_preview, build_preview, iter_preview
from namecutter.models import ScanOptions


def _resolved_length(path: Path) -> int:
    return len(str(path.resolve(strict=False)))


class BuildPreviewTests(unittest.TestCase):
    def test_keeps_name_when_output_path_is_within_limit(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            source_file = source_dir / "notes.txt"
            source_file.write_text("ok", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=200,
                    limit_mode="path",
                )
            )

            self.assertEqual(1, len(preview))
            self.assertEqual("copy", preview[0].action)
            self.assertEqual("ready", preview[0].status)
            self.assertEqual(
                (output_dir / "notes.txt").resolve(strict=False),
                preview[0].target_path.resolve(strict=False),
            )
            self.assertEqual(_resolved_length(source_file), preview[0].original_path_length)
            self.assertEqual(len("notes"), preview[0].original_name_length)

    def test_truncates_filename_when_output_path_exceeds_limit(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            source_file = source_dir / "very-long-file-name-for-sync-problem.xlsx"
            source_file.write_text("ok", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=66,
                    limit_mode="path",
                )
            )

            self.assertEqual("copy", preview[0].action)
            self.assertEqual("ready", preview[0].status)
            self.assertEqual(".xlsx", "".join(preview[0].target_path.suffixes))
            self.assertLessEqual(_resolved_length(preview[0].target_path), 66)

    def test_adds_numeric_suffix_when_truncated_names_collide_in_path_mode(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            first = source_dir / "collision-example-aaaa.txt"
            second = source_dir / "collision-example-bbbb.txt"
            first.write_text("1", encoding="utf-8")
            second.write_text("2", encoding="utf-8")

            preview = []
            for max_length in range(
                _resolved_length(output_dir / "a.txt"),
                _resolved_length(output_dir / "collision-example-aaaa.txt"),
            ):
                candidate_preview = build_preview(
                    ScanOptions(
                        source_dir=source_dir,
                        output_dir=output_dir,
                        max_path_length=max_length,
                        limit_mode="path",
                    )
                )
                target_names = sorted(item.target_path.name for item in candidate_preview)
                if (
                    all(item.status == "ready" for item in candidate_preview)
                    and any(name.endswith("_1.txt") for name in target_names)
                ):
                    preview = candidate_preview
                    break

            self.assertTrue(preview, "Expected a collision suffix in path mode.")
            target_names = sorted(item.target_path.name for item in preview)
            self.assertEqual(2, len(set(target_names)))
            self.assertTrue(any(name.endswith("_1.txt") for name in target_names))

    def test_marks_item_as_skip_when_parent_path_is_too_long_in_path_mode(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = (
                root
                / "very"
                / "deep"
                / "folder"
                / "path"
                / "that"
                / "already"
                / "uses"
                / "most"
                / "of"
                / "the"
                / "limit"
            )
            source_dir.mkdir()
            output_dir.mkdir(parents=True)
            source_file = source_dir / "abc.txt"
            source_file.write_text("ok", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=40,
                    limit_mode="path",
                )
            )

            self.assertEqual("skip", preview[0].action)
            self.assertEqual("skip", preview[0].status)
            self.assertIn("cannot fit", preview[0].reason.lower())

    def test_preserves_subdirectories_for_copy_mode(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            nested_dir = source_dir / "nested"
            output_dir = root / "out"
            nested_dir.mkdir(parents=True)
            output_dir.mkdir()
            source_file = nested_dir / "project plan draft.txt"
            source_file.write_text("ok", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=120,
                    limit_mode="path",
                )
            )

            self.assertEqual(
                (output_dir / "nested" / "project plan draft.txt").resolve(strict=False),
                preview[0].target_path.resolve(strict=False),
            )

    def test_filename_mode_truncates_stem_only_and_keeps_extension(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out" / "nested" / "folder" / "structure"
            source_dir.mkdir()
            output_dir.mkdir(parents=True)
            source_file = source_dir / "very-long-file-name-for-sync-problem.xlsx"
            source_file.write_text("ok", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=20,
                    max_filename_length=8,
                    limit_mode="filename",
                )
            )

            self.assertEqual("ready", preview[0].status)
            self.assertEqual("very-lon.xlsx", preview[0].target_path.name)
            self.assertEqual(
                len("very-long-file-name-for-sync-problem"),
                preview[0].original_name_length,
            )
            self.assertGreater(_resolved_length(preview[0].target_path), 20)

    def test_filename_mode_preserves_multiple_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            source_file = source_dir / "package.tar.gz"
            source_file.write_text("ok", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_filename_length=4,
                    limit_mode="filename",
                )
            )

            self.assertEqual("pack.tar.gz", preview[0].target_path.name)
            self.assertEqual(".tar.gz", "".join(preview[0].target_path.suffixes))

    def test_filename_mode_adds_collision_suffix_within_name_budget(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            first = source_dir / "collision-alpha.txt"
            second = source_dir / "collision-beta.txt"
            first.write_text("1", encoding="utf-8")
            second.write_text("2", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_filename_length=9,
                    limit_mode="filename",
                )
            )

            target_names = sorted(item.target_path.name for item in preview)
            self.assertEqual(["collisi_1.txt", "collision.txt"], target_names)
            for item in preview:
                stem = item.target_path.name[: -len(".txt")]
                self.assertLessEqual(len(stem), 9)

    def test_filename_mode_skips_when_unique_suffix_cannot_fit(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            first = source_dir / "alpha.txt"
            second = source_dir / "amber.txt"
            first.write_text("1", encoding="utf-8")
            second.write_text("2", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_filename_length=1,
                    limit_mode="filename",
                )
            )

            statuses = sorted(item.status for item in preview)
            self.assertEqual(["ready", "skip"], statuses)
            skipped = next(item for item in preview if item.status == "skip")
            self.assertIn("file name limit", skipped.reason.lower())

    def test_filename_mode_does_not_skip_when_parent_path_is_long(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = (
                root
                / "very"
                / "deep"
                / "folder"
                / "path"
                / "that"
                / "would"
                / "normally"
                / "break"
                / "the"
                / "path"
                / "limit"
            )
            source_dir.mkdir()
            output_dir.mkdir(parents=True)
            source_file = source_dir / "quarterly report.txt"
            source_file.write_text("ok", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=30,
                    max_filename_length=10,
                    limit_mode="filename",
                )
            )

            self.assertEqual("ready", preview[0].status)
            self.assertEqual("quarterly .txt", preview[0].target_path.name)

    def test_iter_preview_matches_build_preview_for_small_input(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "alpha-long-name.txt").write_text("a", encoding="utf-8")
            (source_dir / "beta-long-name.txt").write_text("b", encoding="utf-8")

            options = ScanOptions(
                source_dir=source_dir,
                output_dir=output_dir,
                max_filename_length=6,
                limit_mode="filename",
            )

            self.assertEqual(build_preview(options), list(iter_preview(options)))


class ApplyPreviewTests(unittest.TestCase):
    def test_copy_mode_writes_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "very-long-file-name-for-copy.txt").write_text("copy me", encoding="utf-8")

            max_length = _resolved_length(output_dir / "copy.txt")
            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=max_length,
                    limit_mode="path",
                )
            )

            summary = apply_preview(preview)

            self.assertEqual(1, summary.changed)
            self.assertTrue(preview[0].target_path.exists())
            self.assertEqual("copy me", preview[0].target_path.read_text(encoding="utf-8"))

    def test_in_place_mode_renames_files(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            source_dir.mkdir()
            source_path = source_dir / "very-long-file-name-for-in-place-mode.txt"
            source_path.write_text("rename me", encoding="utf-8")

            max_length = _resolved_length(source_dir / "rename.txt")
            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=source_dir,
                    max_path_length=max_length,
                    limit_mode="path",
                    in_place=True,
                )
            )

            summary = apply_preview(preview)

            self.assertEqual(1, summary.changed)
            self.assertFalse(source_path.exists())
            self.assertTrue(preview[0].target_path.exists())
            self.assertEqual("rename me", preview[0].target_path.read_text(encoding="utf-8"))

    def test_apply_options_copy_mode_streams_from_options(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "presentation-draft-final.txt").write_text("copy me", encoding="utf-8")

            summary = apply_options(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_filename_length=8,
                    limit_mode="filename",
                )
            )

            self.assertEqual(1, summary.changed)
            self.assertTrue((output_dir / "presenta.txt").exists())

    def test_apply_options_in_place_renames_files(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            source_dir.mkdir()
            source_path = source_dir / "spreadsheet-for-quarterly-board-review.xlsx"
            source_path.write_text("rename me", encoding="utf-8")

            summary = apply_options(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=source_dir,
                    max_filename_length=10,
                    limit_mode="filename",
                    in_place=True,
                )
            )

            self.assertEqual(1, summary.changed)
            self.assertFalse(source_path.exists())
            self.assertTrue((source_dir / "spreadshee.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
