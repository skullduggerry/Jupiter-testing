"""What the shell shows from outside: as text, never as markup.

A Text's default format, AutoText, renders anything that looks like rich
text as such, and Qt fetches an <img> from wherever it points. Whoever names
a Wi-Fi network or a Bluetooth device nearby, sends a notification, a
calendar invitation or a file, or answers through PAM, chooses that text.
So on every surface that shows it (the dotfiles' convention in
their CLAUDE.md), each Text sets its format: PlainText, or the
notification body's StyledText without images (qml/NotificationBodyTest).
The only exceptions are the fixed messages listed here, which hold nothing
from outside.
"""

from __future__ import annotations

import unittest

from harness import DOTFILES, QUICKSHELL, source

SURFACES = [
    "lock/*.qml",
    "notifications/*.qml",
    "panels/Notification*.qml",
    "panels/Calendar*.qml",
    "panels/Bluetooth*.qml",
    "panels/Wifi*.qml",
    "panels/Clipboard*.qml",
    "panels/Shelf*.qml",
    "panels/Media*.qml",
    "panels/TrackSeek.qml",
    "panels/AudioPanel.qml",
    "panels/VolumeRow.qml",
    "panels/BatteryPanel.qml",
    "panels/DetailRow.qml",
    "bar/widgets/MediaWidget.qml",
    "bar/widgets/Tray*.qml",
    "quickmenu/QuickMenuApps.qml",
    "quickmenu/QuickMenuClipboard.qml",
    "settings/NetworkPage.qml",
    "settings/BluetoothPage.qml",
    "settings/SoundPage.qml",
    "settings/AudioDeviceRow.qml",
    "settings/AppVolumeRow.qml",
    "settings/StartupPage.qml",
    # A player's name (MediaPanel's picker), an app's reply placeholder, the
    # keyboard's and the monitors' names, the system's font families.
    "panels/PillButton.qml",
    "panels/InputField.qml",
    "bar/widgets/KeyboardWidget.qml",
    "panels/WorkspacePanel.qml",
    "settings/DisplaysPage.qml",
    "settings/ChoiceField.qml",
]
# Texts made of the shell's own words, numbers and dates alone, by file.
FIXED = {
    "bar/widgets/TrayMenu.qml": {
        '"Back"',
        '"No menu entries"',
    },
    "etc/greetd/quickshell/GreeterSurface.qml": {
        'Qt.formatDateTime(clock.date, "HH:mm")',
        'Qt.formatDateTime(clock.date, "ddd d MMM")',
    },
    "lock/LockSurface.qml": {
        "Time.time",
        "Time.date",
    },
    "panels/BatteryPanel.qml": {
        'Math.round(root.device.percentage * 100) + "%"',
    },
    "panels/BluetoothPanel.qml": {
        '"Searching…"',
        'row.modelData.pairing ? "Pairing…" : "…"',
        "{",  # its empty list: a state, in four fixed sentences
    },
    "panels/CalendarPanel.qml": {
        'Qt.formatDate(root.dayAt(index), "ddd")',
        "cell.day.getDate()",
        'root.showingUpcoming ? Qt.formatDate(root.selectedDay, "d MMM") + " · upcoming" : Qt.formatDate(root.selectedDay, "dddd d MMMM")',
        'CalendarService.loading ? "Syncing…" : CalendarService.status === "ok" ? Qt.formatDateTime(CalendarService.lastUpdated, "HH:mm") : ""',
        'root.showingUpcoming ? Qt.formatDateTime(agendaRow.modelData.start, agendaRow.modelData.allDay ? "ddd d" : "ddd d HH:mm") : agendaRow.modelData.allDay ? "all day" : Qt.formatDateTime(agendaRow.modelData.start, "HH:mm")',
        'CalendarService.status === "error" ? "Calendar unavailable" : CalendarService.loading && CalendarService.events.length === 0 ? "Loading…" : "Nothing scheduled"',
    },
    "panels/CalendarSetup.qml": {
        'CalendarService.signingIn ? "Waiting for the browser…" : "Sign in with your browser"',
    },
    "panels/CalendarTasks.qml": {
        '"Tasks"',
        'taskRow.dated ? Qt.formatDateTime(taskRow.modelData.due, taskRow.modelData.allDay ? "d MMM" : "d MMM HH:mm") : ""',
    },
    "panels/ClipboardPanel.qml": {
        "history.emptyText",
    },
    "panels/DetailRow.qml": {
        "root.label",  # the label; the value is the device's
    },
    "panels/NotificationPanel.qml": {
        'NotificationService.doNotDisturb ? "Do not disturb" : "No notifications"',
    },
    "panels/ShelfPanel.qml": {
        '"Nothing on the shelf yet"',
    },
    "panels/TrackSeek.qml": {
        "root.clock(root.shownPosition)",
        "root.clock(root.player?.length ?? 0)",
    },
    "panels/WifiPanel.qml": {
        'Networking.wifiEnabled ? "No networks found" : "Wi-Fi is off"',
    },
    "quickmenu/QuickMenuApps.qml": {
        '"Search apps"',
        '"No matching apps"',
    },
    "quickmenu/QuickMenuClipboard.qml": {
        "history.emptyText",
    },
    "settings/AudioDeviceRow.qml": {
        "Volume.kind(root.node)",
    },
    "settings/NetworkPage.qml": {
        '"Not connected"',
    },
    "settings/SoundPage.qml": {
        '"No app is playing sound"',
        "card.emptyText",
    },
    "settings/StartupPage.qml": {
        "root.stateText(app.modelData)",
        '"No app starts with the session"',
    },
}


class OutsideText(unittest.TestCase):
    def test_every_text_on_a_surface_sets_its_format(self) -> None:
        files = sorted({p for g in SURFACES for p in QUICKSHELL.glob(g)})
        files += sorted((DOTFILES / "etc/greetd/quickshell").glob("*.qml"))
        self.assertGreater(len(files), 30, "the surfaces were found")
        for path in files:
            text = path.read_text()
            for block in source.objects(text, "Text"):
                shown = source.binding(block.text, "text")
                name = str(path.relative_to(DOTFILES)).removeprefix(
                    ".config/quickshell/"
                )
                if shown is None or shown in FIXED.get(name, ()):
                    continue
                line = text.count("\n", 0, block.start) + 1
                with self.subTest(f"{path.relative_to(DOTFILES)}:{line}"):
                    self.assertIn(
                        source.binding(block.text, "textFormat"),
                        ("Text.PlainText", "Text.StyledText"),
                        f"shows {shown} in its default format",
                    )

    def test_styled_text_is_the_notification_body_alone(self) -> None:
        styled = []
        for path in source.qml_files():
            text = path.read_text()
            for block in source.objects(text, "Text"):
                if source.binding(block.text, "textFormat") in (
                    "Text.StyledText",
                    "Text.RichText",
                    "Text.MarkdownText",
                ):
                    styled.append(
                        (
                            str(path.relative_to(QUICKSHELL)),
                            source.binding(block.text, "text"),
                        )
                    )
        self.assertEqual(
            styled,
            [
                (
                    "panels/NotificationEntry.qml",
                    "NotificationService.withoutImages(root.modelData.body)",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
