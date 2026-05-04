from pathlib import Path
import unittest


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_workflow_exists_with_expected_steps(self) -> None:
        workflow_path = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "release.yml"
        )

        self.assertTrue(workflow_path.exists(), workflow_path)

        content = workflow_path.read_text(encoding="utf-8")

        self.assertIn("tags:", content)
        self.assertIn("- 'v*'", content)
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("inputs:", content)
        self.assertIn("version:", content)
        self.assertIn("python -m unittest discover -s tests -v", content)
        self.assertIn("powershell -ExecutionPolicy Bypass -File .\\build.ps1", content)
        self.assertIn("Get-FileHash dist\\NameCutter.exe -Algorithm SHA256", content)
        self.assertIn("github.event_name == 'workflow_dispatch'", content)
        self.assertIn("git tag", content)
        self.assertIn("git push origin", content)
        self.assertIn("softprops/action-gh-release", content)


if __name__ == "__main__":
    unittest.main()
