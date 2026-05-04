from __future__ import annotations

from .gui import NameCutterApp


def main() -> int:
    app = NameCutterApp()
    return app.run()
