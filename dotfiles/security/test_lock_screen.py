"""The lock screen: services/LockService.qml, lock/, and what around them
keeps a locked session locked.

The QML tests (qml/Lock*Test.qml, qml/TabletLockTest.qml) run the real
LockService in Quickshell, the password through a stand-in login stack in a
PAM sandbox (harness/pam.py): a wrong password, what PAM says, the lock
while PAM checks, a second question, a finger, a shell restarted while
locked. What they cannot show,
the sources do: nothing but PAM's success unlocks, nothing unlocks over IPC
or a shortcut, the password goes through the system's own stack, and while
locked Hyprland runs no bind but the media keys'.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from harness import DOTFILES, QUICKSHELL, qml, source

QML = Path(__file__).resolve().parent / "qml"
SERVICE = QUICKSHELL / "services/LockService.qml"
SURFACE = QUICKSHELL / "lock/LockSurface.qml"
# What a key may still do while the session is locked.
MEDIA = {
    "brightnessUp",
    "brightnessDown",
    "volumeUp",
    "volumeDown",
    "volumeMute",
    "mediaPlayPause",
    "mediaNext",
    "mediaPrevious",
}


@qml.files(QML, "Lock*Test.qml")
@qml.files(QML, "TabletLockTest.qml")
class Running(unittest.TestCase):
    pass


class Sources(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SERVICE.read_text()

    def test_only_pam_success_unlocks(self) -> None:
        unlocks = [
            match.start()
            for match in re.finditer(r"root\.locked = false", self.service)
        ]
        # The password's PamContext and the finger's.
        self.assertEqual(len(unlocks), 2, "where LockService unlocks")
        for index in unlocks:
            line = self.service.count("\n", 0, index) + 1
            self.assertTrue(
                any(
                    "result === PamResult.Success" in condition
                    for condition in source.conditions(self.service, index)
                ),
                f"LockService.qml:{line} unlocks without PAM's success",
            )

    def test_nothing_else_unlocks(self) -> None:
        for path in source.qml_files():
            if path == SERVICE:
                continue
            text = path.read_text()
            name = path.relative_to(QUICKSHELL)
            self.assertIsNone(
                re.search(r"LockService\.locked\s*=[^=]", text),
                f"{name} sets LockService.locked",
            )
            self.assertNotIn("lockState", text, f"{name} reaches its state")
            if path != SURFACE:
                self.assertIsNone(
                    re.search(r"LockService\.(password|submit)\b", text),
                    f"{name} types into the lock",
                )

    def test_no_unlock_over_ipc_or_a_shortcut(self) -> None:
        for path in source.qml_files():
            text = path.read_text()
            for kind in ("IpcHandler", "GlobalShortcut"):
                for block in source.objects(text, kind):
                    used = set(
                        re.findall(r"LockService\.(\w+\(?)", block.text)
                    )
                    self.assertLessEqual(
                        used,
                        {"lock(", "locked"},
                        f"{path.relative_to(QUICKSHELL)}: a {kind} that does more than lock",
                    )
        [ipc] = source.objects(
            (QUICKSHELL / "lock/Lock.qml").read_text(), "IpcHandler"
        )
        self.assertEqual(
            re.findall(r"function (\w+)\(", ipc.text), ["lock", "locked"]
        )

    def test_the_password_goes_through_the_systems_stack(self) -> None:
        contexts = list(source.objects(self.service, "PamContext"))
        self.assertEqual(len(contexts), 2)
        password, finger = contexts
        self.assertEqual(
            source.binding(password.text, "config"), "root.pamConfig"
        )
        self.assertIn('pamConfig: "login"', self.service)
        # /etc/pam.d's, which only root writes: a stack of the user's own
        # would let anything that writes their files in.
        self.assertIsNone(source.binding(password.text, "configDirectory"))
        self.assertIsNone(source.binding(password.text, "user"))
        # The reader's: the shell's own pam/fingerprint.conf, or where the
        # system declares one (NixOS, whose PAM finds pam_fprintd by its
        # store path alone) /etc/pam.d's, read from there and nowhere else.
        self.assertEqual(
            source.binding(finger.text, "config"),
            'root.systemFingerprint ? "jupiter-fingerprint" : "fingerprint.conf"',
        )
        self.assertEqual(
            source.binding(finger.text, "configDirectory"),
            'root.systemFingerprint ? "/etc/pam.d" : Quickshell.shellPath("pam")',
        )
        self.assertIn(
            'readonly property bool systemFingerprint: systemFingerprintFile.text() !== ""',
            self.service,
        )
        [stack] = [
            view
            for view in source.objects(self.service, "FileView")
            if "systemFingerprintFile" in view.text
        ]
        self.assertEqual(
            source.binding(stack.text, "path"),
            '"/etc/pam.d/jupiter-fingerprint"',
        )

    def test_the_fingerprint_stack(self) -> None:
        stack = (QUICKSHELL / "pam/fingerprint.conf").read_text()
        rules = [
            line.split()
            for line in stack.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertEqual(
            rules, [["auth", "required", "pam_fprintd.so", "max-tries=1"]]
        )

    def test_the_field_hides_the_password(self) -> None:
        text = SURFACE.read_text()
        [field] = source.objects(text, "TextInput")
        self.assertEqual(
            source.binding(field.text, "echoMode"),
            "LockService.promptVisible ? TextInput.Normal : TextInput.Password",
        )
        self.assertEqual(
            source.binding(field.text, "readOnly"),
            "LockService.authenticating",
        )

    def test_locked_hyprland_runs_only_the_media_keys(self) -> None:
        found = 0
        for path in sorted((DOTFILES / ".config/hypr").rglob("*.lua")):
            for line in path.read_text().splitlines():
                if not re.search(r"locked\s*=\s*true", line):
                    continue
                found += 1
                name = re.search(
                    r'hl\.dsp\.global\("quickshell:(\w+)"\)', line
                )
                self.assertIsNotNone(
                    name,
                    f"{path.name}: a locked bind that is no shortcut: {line}",
                )
                assert name is not None
                self.assertIn(name.group(1), MEDIA, line)
        self.assertGreater(found, 0, "the media keys' binds")

    def test_the_lock_is_up_before_sleep(self) -> None:
        idle = (DOTFILES / ".config/hypr/hypridle.conf").read_text()
        settings = dict(re.findall(r"^\s*(\w+)\s*=\s*(.+?)\s*$", idle, re.M))
        self.assertEqual(settings["lock_cmd"], "qs ipc call lock lock")
        self.assertEqual(settings["before_sleep_cmd"], "loginctl lock-session")
        # 3: suspend waits for the session lock, whoever draws it.
        self.assertEqual(settings["inhibit_sleep"], "3")

    def test_a_lock_that_crashed_is_restored(self) -> None:
        session = (DOTFILES / ".config/hypr/modules/session.lua").read_text()
        self.assertRegex(session, r"allow_session_lock_restore\s*=\s*true")


if __name__ == "__main__":
    unittest.main()
