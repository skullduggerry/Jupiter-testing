"""Phase 4's login keyring (jupiter/keyring.py): on an encrypted system, made
unencrypted where there is none, an encrypted one re-keyed by gnome-keyring's
own dialog with nothing of the password passing through the installer, and
never one written over or deleted; on an unencrypted one, nothing made and
nothing re-keyed.

The dialog needs a desktop, so here gdbus is a stand-in that answers as
gnome-keyring does: the prompt's path, then Completed once the "dialog" was
answered (the keyring rewritten unencrypted) or dismissed. The real
gnome-keyring-daemon, on a session bus of its own in a throwaway home, shows
that the call exists and hands out a prompt (its runtime folder short: the
control socket's path must stay under 108 bytes).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupiter import keyring, tpm

from harness import SECRET, environment, executable

NEEDED = ("gnome-keyring-daemon", "dbus-run-session", "gdbus")
MISSING = [name for name in NEEDED if not shutil.which(name)]
PROMPT_PATH = "/org/freedesktop/secrets/prompt/p1"
REAL_POPEN = subprocess.Popen
# gdbus as gnome-keyring answers it. Prompt "shows the dialog": with ANSWER
# empty it rewrites the keyring unencrypted, as an empty new password does;
# then the monitor sees Completed, dismissed or not.
GDBUS = f"""#!{sys.executable}
import json, os, sys, time
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps(args) + "\\n")
answered = os.path.join(os.environ["WORLD"], "answered")
if args[0] == "monitor":
    while not os.path.exists(answered):
        time.sleep(0.02)
    dismissed = "true" if os.environ["ANSWER"] == "cancel" else "false"
    print(f"{PROMPT_PATH}: org.freedesktop.Secret.Prompt.Completed ({{dismissed}}, <''>)", flush=True)
    time.sleep(30)
elif "ChangeWithPrompt" in " ".join(args):
    print("(objectpath '{PROMPT_PATH}',)")
elif "org.freedesktop.Secret.Prompt.Prompt" in args:
    if os.environ["ANSWER"] == "empty":
        open(os.environ["LOGIN"], "w").write("[keyring]\\ndisplay-name=Login\\n")
    open(answered, "w").close()
    print("()")
"""


class Keyrings(unittest.TestCase):
    """keyring.py in this process, its keyrings folder a temporary one."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.keyrings = tmp / "keyrings"
        self.enterContext(
            mock.patch.object(keyring, "folder", return_value=self.keyrings)
        )
        self.printed = self.enterContext(mock.patch("builtins.print"))
        # An encrypted root, unless a test says otherwise.
        self.root = self.enterContext(
            mock.patch.object(
                tpm, "root_volume", return_value=("root", "/dev/vda2")
            )
        )
        # It reaches nothing through another program.
        self.enterContext(
            mock.patch("subprocess.Popen", side_effect=AssertionError)
        )


class Folder(Keyrings):
    def test_makes_an_unencrypted_one_only_root_and_you_read(self) -> None:
        keyring.main()
        login = self.keyrings / "login.keyring"
        self.assertEqual(login.read_text(), keyring.PLAIN)
        self.assertEqual(login.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.keyrings.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.keyrings / "default").read_text(), "login")

    def test_leaves_an_unencrypted_one_as_it_is(self) -> None:
        self.keyrings.mkdir()
        login = self.keyrings / "login.keyring"
        login.write_text("[keyring]\ndisplay-name=Login\n\n[1]\nsecret=x\n")
        (self.keyrings / "default").write_text("other")
        keyring.main()
        self.assertEqual(
            login.read_text(),
            "[keyring]\ndisplay-name=Login\n\n[1]\nsecret=x\n",
        )
        self.assertEqual((self.keyrings / "default").read_text(), "other")

    def test_keeps_the_default_another_keyring_is(self) -> None:
        self.keyrings.mkdir()
        (self.keyrings / "default").write_text("other")
        keyring.main()
        self.assertEqual((self.keyrings / "default").read_text(), "other")
        self.assertEqual(
            (self.keyrings / "login.keyring").read_text(), keyring.PLAIN
        )

    def test_never_writes_over_one_that_appears(self) -> None:
        self.keyrings.mkdir()
        login = self.keyrings / "login.keyring"
        with mock.patch.object(Path, "exists", return_value=False):
            login.write_text("theirs")
            with self.assertRaises(FileExistsError):
                keyring.main()
        self.assertEqual(login.read_text(), "theirs")

    def test_without_a_session_bus_says_where_to_run_it(self) -> None:
        self.keyrings.mkdir()
        login = self.keyrings / "login.keyring"
        login.write_bytes(keyring.ENCRYPTED_MAGIC + b"secrets")
        with mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": ""}):
            keyring.main()
        self.assertEqual(
            login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )
        self.assertEqual(
            sorted(p.name for p in self.keyrings.iterdir()), ["login.keyring"]
        )


class Unencrypted(Keyrings):
    """A root not on LUKS: an unencrypted keyring would lie on the disk in
    the clear, so none is made and none re-keyed."""

    def test_makes_none(self) -> None:
        self.root.return_value = None
        keyring.main()
        self.assertFalse(self.keyrings.exists())
        said = " ".join(
            str(a) for c in self.printed.call_args_list for a in c.args
        )
        self.assertIn("The disk is not encrypted", said)

    def test_leaves_an_encrypted_one_encrypted(self) -> None:
        self.root.return_value = None
        self.keyrings.mkdir()
        login = self.keyrings / "login.keyring"
        login.write_bytes(keyring.ENCRYPTED_MAGIC + b"secrets")
        with mock.patch("builtins.input", side_effect=AssertionError):
            keyring.main()
        self.assertEqual(
            login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )
        self.assertEqual(
            [p.name for p in self.keyrings.iterdir()], ["login.keyring"]
        )


class ReKeying(Keyrings):
    """An encrypted login keyring, as a password login leaves it, on an
    encrypted disk, phase 4 run from the desktop."""

    def setUp(self) -> None:
        super().setUp()
        self.world = self.keyrings.parent
        self.keyrings.mkdir()
        self.login = self.keyrings / "login.keyring"
        self.login.write_bytes(keyring.ENCRYPTED_MAGIC + b"secrets")
        self.calls = self.world / "calls"
        executable(self.world / "bin/gdbus", GDBUS)
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "PATH": f"{self.world / 'bin'}:{os.environ['PATH']}",
                    "CALLS": str(self.calls),
                    "WORLD": str(self.world),
                    "LOGIN": str(self.login),
                    "WAYLAND_DISPLAY": "wayland-1",
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
                },
            )
        )

    def rekey(self, answer: str, consent: str = "") -> list[list[str]]:
        os.environ["ANSWER"] = answer
        with (
            mock.patch("subprocess.Popen", REAL_POPEN),
            mock.patch("builtins.input", return_value=consent),
            mock.patch("getpass.getpass", side_effect=AssertionError),
        ):
            keyring.main()
        if not self.calls.exists():
            return []
        return [
            json.loads(line) for line in self.calls.read_text().splitlines()
        ]

    def copies(self) -> list[str]:
        return sorted(
            p.name
            for p in self.keyrings.iterdir()
            if p.name != "login.keyring"
        )

    def test_the_dialog_with_an_empty_password_leaves_it_unencrypted(
        self,
    ) -> None:
        calls = self.rekey("empty")
        self.assertTrue(self.login.read_text().startswith("[keyring]"))
        [copy] = self.copies()
        self.assertTrue(
            (self.keyrings / copy)
            .read_bytes()
            .startswith(keyring.ENCRYPTED_MAGIC)
        )
        self.assertIn(
            [
                "call", "--session", "--dest", "org.freedesktop.secrets",
                "--object-path", "/org/freedesktop/secrets",
                "--method", f"{keyring.INTERNAL}.ChangeWithPrompt",
                "/org/freedesktop/secrets/collection/login",
            ],
            calls,
        )  # fmt: skip
        self.assertIn(
            [
                "call", "--session", "--dest", "org.freedesktop.secrets",
                "--object-path", PROMPT_PATH,
                "--method", "org.freedesktop.Secret.Prompt.Prompt", "",
            ],
            calls,
        )  # fmt: skip

    def test_a_dismissed_dialog_changes_nothing(self) -> None:
        self.rekey("cancel")
        self.assertEqual(
            self.login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )
        self.assertEqual(self.copies(), [])

    def test_asks_first(self) -> None:
        calls = self.rekey("empty", consent="n")
        self.assertEqual(calls, [])
        self.assertEqual(
            self.login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )

    def test_only_from_the_desktop(self) -> None:
        del os.environ["WAYLAND_DISPLAY"]
        calls = self.rekey("empty")
        self.assertEqual(calls, [])
        self.assertEqual(
            self.login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )


@unittest.skipIf(MISSING, f"needs {', '.join(MISSING)}")
class GnomeKeyring(unittest.TestCase):
    """The real daemon: the call keyring.py makes exists, and hands out a
    prompt object (whose dialog a desktop would show)."""

    def test_offers_a_prompt_to_change_the_password(self) -> None:
        home = Path(self.enterContext(tempfile.TemporaryDirectory(dir="/tmp")))
        session = f"""
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
printf %s "$KEYRING_PASSWORD" | gnome-keyring-daemon --unlock --components=secrets >/dev/null
gdbus call --session --dest org.freedesktop.secrets \\
    --object-path /org/freedesktop/secrets \\
    --method {keyring.INTERNAL}.ChangeWithPrompt {keyring.LOGIN}
"""
        done = subprocess.run(
            ["dbus-run-session", "--", "sh", "-c", session],
            env=environment(
                HOME=str(home),
                XDG_DATA_HOME=str(home / "data"),
                XDG_RUNTIME_DIR=str(home / "r"),
                KEYRING_PASSWORD=SECRET,
            ),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        self.assertRegex(
            done.stdout, r"objectpath '/org/freedesktop/secrets/prompt/\w+'"
        )


if __name__ == "__main__":
    unittest.main()
