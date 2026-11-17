"""services/Pointer.qml's settings, saved while they change.

An async writeAdapter(), once done, puts what it wrote back into the
adapter, undoing a touchpad found or a speed set while it was writing:
qml/PointerTest.qml's touchpad kept while away failed so, once in about
twenty runs on a busy machine, which no run can show every time. The
sources can: the settings' FileView writes blocking.
"""

from __future__ import annotations

import unittest

from harness import QUICKSHELL, source

POINTER = QUICKSHELL / "services/Pointer.qml"


class Writes(unittest.TestCase):
    def test_the_settings_are_written_before_they_change_again(self) -> None:
        text = POINTER.read_text()
        [settings] = [
            block
            for block in source.objects(text, "FileView")
            if source.binding(block.text, "id") == "settingsFile"
        ]
        self.assertIn("JsonAdapter", settings.text, "the settings' adapter")
        self.assertIn("settingsFile.writeAdapter()", text)
        self.assertEqual(
            source.binding(settings.text, "blockWrites"),
            "true",
            "an async write would put the settings it wrote back over a "
            "change made meanwhile",
        )


if __name__ == "__main__":
    unittest.main()
