"""The QML tests in qml/, each in a Quickshell of its own (harness/qml.py)."""

from __future__ import annotations

import unittest
from pathlib import Path

from harness import qml


@qml.files(Path(__file__).resolve().parent / "qml")
class Qml(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main()
