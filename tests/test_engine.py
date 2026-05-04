from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from namecutter.engine import apply_preview, build_preview
from namecutter.models import ScanOptions


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
                    in_place=False,
                )
            )

            self.assertEqual(1, len(preview))
            self.assertEqual("copy", preview[0].action)
            self.assertEqual("ready", preview[0].status)
            self.assertEqual(output_dir / "notes.txt", preview[0].target_path)
            self.assertEqual(
                len(str(source_file.resolve(strict=False))),
                preview[0].original_path_length,
            )

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
                    in_place=False,
                )
            )

            self.assertEqual("copy", preview[0].action)
            self.assertEqual("ready", preview[0].status)
            self.assertEqual(".xlsx", "".join(preview[0].target_path.suffixes))
            self.assertTrue(
                preview[0].target_path.name.startswith("very"),
                preview[0].target_path.name,
            )
            self.assertLessEqual(
                len(str(preview[0].target_path.resolve(strict=False))),
                66,
            )

    def test_adds_numeric_suffix_when_truncated_names_collide(self) -> None:
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

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=56,
                    in_place=False,
                )
            )

            target_names = sorted(item.target_path.name for item in preview)
            self.assertEqual(2, len(set(target_names)))
            self.assertTrue(any(name.endswith("_1.txt") for name in target_names))

    def test_marks_item_as_skip_when_parent_path_is_too_long(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "very" / "deep" / "folder" / "path" / "that" / "already" / "uses" / "most" / "of" / "the" / "limit"
            source_dir.mkdir()
            output_dir.mkdir(parents=True)
            source_file = source_dir / "abc.txt"
            source_file.write_text("ok", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=40,
                    in_place=False,
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
                    in_place=False,
                )
            )

            self.assertEqual(output_dir / "nested" / "project plan draft.txt", preview[0].target_path)

    def test_preserves_subdirectories_for_in_place_mode(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            nested_dir = source_dir / "中文 資料夾"
            nested_dir.mkdir(parents=True)
            source_file = nested_dir / "非常非常非常長的檔案名稱.txt"
            source_file.write_text("ok", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=source_dir,
                    max_path_length=80,
                    in_place=True,
                )
            )

            self.assertEqual(source_dir / "中文 資料夾", preview[0].target_path.parent)
            self.assertIn(preview[0].action, {"keep", "rename"})


class ApplyPreviewTests(unittest.TestCase):
    def test_copy_mode_writes_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            source_dir = root / "src"
            output_dir = root / "out"
            source_dir.mkdir()
            output_dir.mkdir()
            (source_dir / "very-long-file-name-for-copy.txt").write_text("copy me", encoding="utf-8")

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=output_dir,
                    max_path_length=55,
                    in_place=False,
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

            preview = build_preview(
                ScanOptions(
                    source_dir=source_dir,
                    output_dir=source_dir,
                    max_path_length=55,
                    in_place=True,
                )
            )

            summary = apply_preview(preview)

            self.assertEqual(1, summary.changed)
            self.assertFalse(source_path.exists())
            self.assertTrue(preview[0].target_path.exists())
            self.assertEqual("rename me", preview[0].target_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
