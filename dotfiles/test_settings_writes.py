"""The shell's settings, saved while they change: every FileView whose
adapter the shell writes (writeAdapter()) writes blocking.

An async writeAdapter(), once done, puts what it wrote back into the
adapter, undoing a change made while it was writing: qml/PointerTest.qml's
touchpad kept while away failed so, once in about twenty runs on a busy
machine, which no run can show every time. The sources can.
"""

from __future__ import annotations

import re
import unittest

from harness import QUICKSHELL, source

# Those the race was found in and fixed: a reading of the sources that finds
# fewer has stopped understanding them.
KNOWN = {
    "services/BarLayout.qml": {"settingsFile"},
    "services/CalendarService.qml": {"settingsFile", "preferencesFile"},
    "services/LauncherHistory.qml": {"historyFile"},
    "services/Pointer.qml": {"settingsFile"},
    "services/QuickMenu.qml": {"settingsFile"},
    "services/QuickToggles.qml": {"settingsFile"},
    "services/Tablet.qml": {"settingsFile"},
    "services/WallpaperService.qml": {"settingsFile"},
    "style/LockLook.qml": {"settingsFile"},
    "style/Theme.qml": {"settingsFile"},
}


def written() -> dict[str, dict[str, str | None]]:
    """Each file's FileViews whose adapter it writes, by id, and what their
    blockWrites is bound to."""
    found: dict[str, dict[str, str | None]] = {}
    for path in source.qml_files():
        text = path.read_text()
        ids = set(re.findall(r"\b(\w+)\.writeAdapter\(\)", text))
        for block in source.objects(text, "FileView"):
            name = source.binding(block.text, "id")
            if name is not None and name in ids:
                relative = str(path.relative_to(QUICKSHELL))
                found.setdefault(relative, {})[name] = source.binding(
                    block.text, "blockWrites"
                )
    return found


class Writes(unittest.TestCase):
    def test_every_written_adapter_is_written_blocking(self) -> None:
        found = written()
        for path, known in KNOWN.items():
            with self.subTest(path=path):
                self.assertLessEqual(known, set(found.get(path, {})))
        for path, views in found.items():
            for name, blocking in views.items():
                with self.subTest(path=path, view=name):
                    self.assertEqual(
                        blocking,
                        "true",
                        f"{path}'s {name} writes async: once done, it puts "
                        "what it wrote back over a change made meanwhile",
                    )


if __name__ == "__main__":
    unittest.main()
