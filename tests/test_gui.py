from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from namecutter.gui import MODE_TO_LABEL, NameCutterApp
from namecutter.models import PreviewItem


def _preview_item(name: str, *, original_path_length: int = 87, original_name_length: int = 12) -> PreviewItem:
    return PreviewItem(
        source_path=Path(fr"C:\input\{name}"),
        target_path=Path(fr"C:\output\{name}"),
        action="copy",
        status="ready",
        reason="Ready.",
        original_path_length=original_path_length,
        original_name_length=original_name_length,
    )


class NameCutterGuiTests(unittest.TestCase):
    def test_preview_table_includes_original_path_length_column(self) -> None:
        app = NameCutterApp()
        try:
            app.preview_limit_mode = "path"
            app.preview_items = [_preview_item("very-long-name.txt", original_path_length=87)]

            app._refresh_tree()

            self.assertEqual(
                ("source", "target", "original_length", "action", "status", "reason"),
                app.tree["columns"],
            )
            self.assertEqual("Original Path Length", app.tree.heading("original_length")["text"])
            row_values = app.tree.item(app.tree.get_children()[0], "values")
            self.assertEqual("87", row_values[2])
        finally:
            app.root.destroy()

    def test_preview_table_switches_to_original_name_length_in_filename_mode(self) -> None:
        app = NameCutterApp()
        try:
            app.preview_limit_mode = "filename"
            app.preview_items = [_preview_item("very-long-name.txt", original_name_length=12)]

            app._refresh_tree()

            self.assertEqual("Original Name Length", app.tree.heading("original_length")["text"])
            row_values = app.tree.item(app.tree.get_children()[0], "values")
            self.assertEqual("12", row_values[2])
        finally:
            app.root.destroy()

    def test_limit_mode_switch_preserves_both_values_and_disables_inactive_entry(self) -> None:
        app = NameCutterApp()
        try:
            app.path_limit_var.set("66")
            app.filename_limit_var.set("12")

            app.limit_mode_var.set(MODE_TO_LABEL["filename"])
            app._on_limit_mode_selected()

            self.assertEqual("66", app.path_limit_var.get())
            self.assertEqual("12", app.filename_limit_var.get())
            self.assertIn("disabled", app.path_limit_entry.state())
            self.assertNotIn("disabled", app.filename_limit_entry.state())

            app.limit_mode_var.set(MODE_TO_LABEL["path"])
            app._on_limit_mode_selected()

            self.assertEqual("66", app.path_limit_var.get())
            self.assertEqual("12", app.filename_limit_var.get())
            self.assertNotIn("disabled", app.path_limit_entry.state())
            self.assertIn("disabled", app.filename_limit_entry.state())
        finally:
            app.root.destroy()

    def test_read_options_returns_filename_mode_values(self) -> None:
        app = NameCutterApp()
        try:
            with tempfile.TemporaryDirectory() as root_dir:
                root = Path(root_dir)
                source_dir = root / "src"
                output_dir = root / "out"
                source_dir.mkdir()
                output_dir.mkdir()

                app.source_var.set(str(source_dir))
                app.output_var.set(str(output_dir))
                app.path_limit_var.set("99")
                app.filename_limit_var.set("10")
                app.limit_mode_var.set(MODE_TO_LABEL["filename"])
                app._sync_limit_mode_controls()

                options = app._read_options()

                self.assertEqual("filename", options.limit_mode)
                self.assertEqual(99, options.max_path_length)
                self.assertEqual(10, options.max_filename_length)
                self.assertFalse(options.in_place)
        finally:
            app.root.destroy()

    def test_read_options_ignores_invalid_inactive_limit(self) -> None:
        app = NameCutterApp()
        try:
            with tempfile.TemporaryDirectory() as root_dir:
                root = Path(root_dir)
                source_dir = root / "src"
                output_dir = root / "out"
                source_dir.mkdir()
                output_dir.mkdir()

                app.source_var.set(str(source_dir))
                app.output_var.set(str(output_dir))
                app.path_limit_var.set("88")
                app.filename_limit_var.set("not-a-number")
                app.limit_mode_var.set(MODE_TO_LABEL["path"])
                app._sync_limit_mode_controls()

                options = app._read_options()

                self.assertEqual("path", options.limit_mode)
                self.assertEqual(88, options.max_path_length)
                self.assertEqual(66, options.max_filename_length)
        finally:
            app.root.destroy()

    def test_partial_preview_summary_mentions_sample_rows(self) -> None:
        app = NameCutterApp()
        try:
            app.preview_limit_mode = "path"
            sample_batch = [
                _preview_item(f"file-{index}.txt", original_path_length=80 + index)
                for index in range(4)
            ]

            with patch("namecutter.gui.FULL_PREVIEW_LIMIT", 3), patch(
                "namecutter.gui.SAMPLE_PREVIEW_LIMIT",
                2,
            ):
                app._consume_preview_batch(sample_batch)

            self.assertTrue(app.preview_is_partial)
            self.assertEqual(4, app.preview_total_scanned)
            self.assertEqual(2, len(app.preview_items))
            self.assertIn("sample rows only", app.summary_var.get().lower())
        finally:
            app.root.destroy()

    def test_clicking_column_heading_toggles_sort_direction(self) -> None:
        app = NameCutterApp()
        try:
            app.preview_limit_mode = "path"
            app.preview_items = [
                _preview_item("beta.txt", original_path_length=90),
                _preview_item("alpha.txt", original_path_length=80),
            ]

            app._sort_tree_by("source")

            sorted_sources = [
                app.tree.item(item_id, "values")[0]
                for item_id in app.tree.get_children()
            ]
            self.assertEqual(
                [r"C:\input\alpha.txt", r"C:\input\beta.txt"],
                sorted_sources,
            )
            self.assertEqual("Source Path (ASC)", app.tree.heading("source")["text"])

            app._sort_tree_by("source")

            reverse_sorted_sources = [
                app.tree.item(item_id, "values")[0]
                for item_id in app.tree.get_children()
            ]
            self.assertEqual(
                [r"C:\input\beta.txt", r"C:\input\alpha.txt"],
                reverse_sorted_sources,
            )
            self.assertEqual("Source Path (DESC)", app.tree.heading("source")["text"])
        finally:
            app.root.destroy()

    def test_sorting_original_length_uses_name_length_in_filename_mode(self) -> None:
        app = NameCutterApp()
        try:
            app.preview_limit_mode = "filename"
            app.preview_items = [
                _preview_item("beta.txt", original_name_length=9),
                _preview_item("alpha.txt", original_name_length=4),
            ]

            app._sort_tree_by("original_length")

            sorted_lengths = [
                app.tree.item(item_id, "values")[2]
                for item_id in app.tree.get_children()
            ]
            self.assertEqual(["4", "9"], sorted_lengths)
            self.assertEqual(
                "Original Name Length (ASC)",
                app.tree.heading("original_length")["text"],
            )
        finally:
            app.root.destroy()

    def test_inactive_limit_change_keeps_preview_valid(self) -> None:
        app = NameCutterApp()
        try:
            with tempfile.TemporaryDirectory() as root_dir:
                root = Path(root_dir)
                source_dir = root / "src"
                output_dir = root / "out"
                source_dir.mkdir()
                output_dir.mkdir()

                app.source_var.set(str(source_dir))
                app.output_var.set(str(output_dir))
                app.path_limit_var.set("88")
                app.filename_limit_var.set("10")
                app.limit_mode_var.set(MODE_TO_LABEL["path"])

                app.preview_signature = app._signature_for_options(app._read_options())

                app.filename_limit_var.set("12")

                self.assertIsNotNone(app.preview_signature)
                self.assertEqual(
                    app._signature_for_options(app._read_options()),
                    app.preview_signature,
                )
        finally:
            app.root.destroy()


if __name__ == "__main__":
    unittest.main()
