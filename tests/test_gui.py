from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from namecutter.gui import NameCutterApp
from namecutter.models import PreviewItem


class NameCutterGuiTests(unittest.TestCase):
    def test_preview_table_includes_original_path_length_column(self) -> None:
        app = NameCutterApp()
        try:
            app.preview_items = [
                PreviewItem(
                    source_path=Path(r"C:\input\very-long-name.txt"),
                    target_path=Path(r"C:\output\very.txt"),
                    action="copy",
                    status="ready",
                    reason="Trimmed to fit the path limit.",
                    original_path_length=87,
                )
            ]

            app._refresh_tree()

            self.assertEqual(
                ("source", "target", "original_length", "action", "status", "reason"),
                app.tree["columns"],
            )
            row_values = app.tree.item(app.tree.get_children()[0], "values")
            self.assertEqual("87", row_values[2])
        finally:
            app.root.destroy()


if __name__ == "__main__":
    unittest.main()
