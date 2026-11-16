"""The login screen: greetd, the greeter it runs, and how it is installed.

The QML tests (qml/Greeter*Test.qml) log in through the real GreeterService
against a stand-in greetd (harness/greetd.py). Here: who the greeter offers
and what it learns of them (greeter-env.py), what greetd and the greeter's
compositor run, the PAM stacks greetd authenticates with, and
scripts/install-greeter.sh, which runs as root through pkexec and copies
files out of the owner's home into a folder every user can read: it reads
them as the owner, so nothing the owner could not read gets out.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from typing import Any

from harness import (
    DOTFILES,
    SECRET,
    TESTING,
    environment,
    load,
    pam,
    qml,
    source,
    temporary,
)

QML = Path(__file__).resolve().parent / "qml"
GREETER_ENV = DOTFILES / "etc/greetd/quickshell/greeter-env.py"
INSTALL = DOTFILES / "scripts/install-greeter.sh"
greeter_env = load(GREETER_ENV)

# The smallest file `file` takes for a JPEG, and a marker for what only root
# may read.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
ROOT_ONLY = "ROOT-ONLY-CONTENT"
OWNER = 1000
# Who the stacks are run for: whoever runs the tests.
USER = os.environ.get("USER", "nobody")


@qml.files(QML, "Greeter*Test.qml")
class Running(unittest.TestCase):
    pass


class WhoIsOffered(unittest.TestCase):
    """greeter-env.py: the accounts one can log in to, and their names."""

    PASSWD = (
        "root:x:0:0::/root:/bin/bash",
        "bin:x:1:1::/:/usr/bin/nologin",
        "greeter:x:959:959:greetd greeter user:/:/bin/bash",
        "nobody:x:65534:65534:Kernel Overflow User:/:/usr/bin/nologin",
        "alice:$6$saltsalt$hashhashhash:1000:1000:Alice Example,,,:/home/alice:/bin/zsh",
        "bob:x:1001:1001::/home/bob:",
        # Service accounts above 1000 whose shell says no, wherever it is.
        "svc1:x:1002:1002::/var/lib/svc1:/bin/nologin",
        "svc2:x:1003:1003::/var/lib/svc2:/usr/local/sbin/nologin",
        "svc3:x:1004:1004::/var/lib/svc3:/bin/false",
        "svc4:x:1005:1005::/var/lib/svc4:/sbin/nologin",
        "high:x:70000:70000::/:/bin/bash",
        "notanumber:x:10o0:1000::/:/bin/bash",
        "+nis",
        "",
    )

    def users(self) -> list[dict[str, str]]:
        passwd = temporary(self) / "passwd"
        passwd.write_text("\n".join(self.PASSWD) + "\n")
        users: list[dict[str, str]] = greeter_env.list_users(str(passwd))
        return users

    def test_only_those_who_can_log_in(self) -> None:
        self.assertEqual(
            [user["name"] for user in self.users()], ["alice", "bob"]
        )

    def test_only_their_names(self) -> None:
        # What the greeter user's process gets: never a hash, a home or a
        # shell, should /etc/passwd hold more than it should.
        users = self.users()
        self.assertEqual(
            {key for user in users for key in user}, {"name", "display"}
        )
        self.assertNotIn("hash", json.dumps(users))
        self.assertEqual(users[0]["display"], "Alice Example")

    def test_only_the_systems_sessions(self) -> None:
        # Folders only root writes: a session there is a program the greeter
        # starts as whoever logs in.
        for directory in greeter_env.SESSION_DIRS:
            self.assertTrue(directory.startswith("/usr/share/"), directory)
        self.assertEqual(greeter_env.PASSWD, "/etc/passwd")
        self.assertNotIn("shadow", GREETER_ENV.read_text())


class Greetd(unittest.TestCase):
    """What greetd runs, and as whom."""

    def test_the_greeter_runs_as_its_own_user(self) -> None:
        config = tomllib.loads(
            (DOTFILES / "etc/greetd/config.toml").read_text()
        )
        session = config["default_session"]
        self.assertEqual(session["user"], "greeter")
        self.assertEqual(
            session["command"], "Hyprland -c /etc/greetd/hyprland.lua"
        )
        self.assertNotIn(
            "initial_session", config, "nobody is logged in unasked"
        )

    @unittest.skipUnless(shutil.which("lua"), "needs lua")
    def test_the_greeters_compositor_runs_the_greeter_only(self) -> None:
        # The staged config under plain lua and a stand-in hl that names
        # every bind and command: one command, the greeter, and no bind,
        # so the screen opens nothing but the login.
        tmp = temporary(self)
        dest = tmp / "greetd"
        state = tmp / "state"
        (state / "quickshell").mkdir(parents=True)
        (state / "quickshell/keyboard.lua").write_text(
            'return { kb_layout = "us,de" }\n'
        )
        (state / "quickshell/monitors.lua").write_text(
            'return { { output = "DP-1", mode = "1920x1080@60" } }\n'
        )
        install(dest, state, tmp / "cache")
        stub = (
            "hl = setmetatable({\n"
            "  config = function() end, monitor = function() end,\n"
            "  on = function(_, handler) handler() end,\n"
            '  exec_cmd = function(command) print("exec " .. command) end,\n'
            '  bind = function(keys) print("bind " .. keys) end,\n'
            '}, { __index = function(_, name) print("hl." .. name) return function() end end })\n'
            f'package.path = "{dest}/?.lua;" .. package.path\n'
            f'dofile("{dest / "hyprland.lua"}")\n'
        )
        ran = subprocess.run(
            ["lua", "-e", stub],
            capture_output=True,
            text=True,
            env=environment(HOME=None),
            check=False,
        )
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(
            ran.stdout.splitlines(),
            [
                f"exec LOCKSCREEN_STYLE={dest}/quickshell/lockscreen.json "
                f"LOCKSCREEN_THEME={dest}/quickshell/theme "
                f"qs -p {dest}/quickshell/shell.qml"
            ],
        )


# The fingers' own count of misses, apart from the password's, and what the
# stack says once the reader is no longer asked.
FINGERS = ["dir=/var/lib/faillock-finger", "deny=5"]
MISSED = ["pam_faillock.so", "authfail", *FINGERS]
MATCHED = ["pam_faillock.so", "authsucc", *FINGERS]
READER_RULE = ["pam_fprintd.so", "max-tries=1", "timeout=5"]
REFUSED = "Fingerprint not recognised: type the password"


class Stacks(unittest.TestCase):
    """The PAM stacks greetd logs in with, which install-greeter.sh puts in
    /etc/pam.d: the system's own, and gnome-keyring's optional lines."""

    @staticmethod
    def rules(name: str) -> list[list[str]]:
        text = (DOTFILES / "etc/pam.d" / name).read_text()
        return [
            line.split()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_logging_in(self) -> None:
        self.assertEqual(
            self.rules("greetd"),
            [
                ["auth", "required", "pam_securetty.so"],
                ["auth", "requisite", "pam_nologin.so"],
                [
                    "auth",
                    "[success=ok",
                    "default=10]",
                    "pam_exec.so",
                    "quiet",
                    "expose_authtok",
                    "/etc/greetd/finger-asked",
                ],
                [
                    "auth",
                    "[success=2",
                    "default=ignore]",
                    "pam_faillock.so",
                    "preauth",
                    "silent",
                    *FINGERS,
                ],
                ["auth", "[default=ignore]", "pam_echo.so", *REFUSED.split()],
                ["auth", "requisite", "pam_deny.so"],
                [
                    "auth",
                    "[success=5",
                    "maxtries=ignore",
                    "default=die]",
                    *READER_RULE,
                ],
                ["auth", "[ignore=ignore", "default=die]", *MISSED],
                [
                    "auth",
                    "[success=3",
                    "maxtries=ignore",
                    "default=die]",
                    *READER_RULE,
                ],
                ["auth", "[ignore=ignore", "default=die]", *MISSED],
                [
                    "auth",
                    "[success=1",
                    "maxtries=bad",
                    "default=die]",
                    *READER_RULE,
                ],
                ["auth", "[default=die]", *MISSED],
                ["auth", "[success=done", "default=die]", *MATCHED],
                ["auth", "include", "system-local-login"],
                ["-auth", "optional", *MATCHED],
                [
                    "auth",
                    "[success=1",
                    "default=ignore]",
                    "pam_exec.so",
                    "quiet",
                    "/etc/greetd/disk-encrypted",
                ],
                ["-auth", "optional", "pam_gnome_keyring.so"],
                ["account", "include", "system-local-login"],
                ["-account", "optional", "pam_faillock.so", *FINGERS],
                ["session", "include", "system-local-login"],
                ["-session", "optional", "pam_gnome_keyring.so", "auto_start"],
            ],
        )

    def test_the_greeters_own_session(self) -> None:
        self.assertEqual(
            self.rules("greetd-greeter"),
            [
                ["auth", "required", "pam_securetty.so"],
                ["auth", "requisite", "pam_nologin.so"],
                ["auth", "include", "system-local-login"],
                ["account", "include", "system-local-login"],
                ["session", "include", "system-local-login"],
            ],
        )

    def test_nothing_lets_anyone_in(self) -> None:
        for name in ("greetd", "greetd-greeter"):
            rules = self.rules(name)
            for index, rule in enumerate(rules):
                with self.subTest(stack=name, rule=" ".join(rule)):
                    self.assertNotIn(rule[1], ("sufficient",))
                    self.assertNotIn(
                        rule[-1], ("pam_permit.so", "pam_rootok.so")
                    )
                    if rule[1] == "optional":
                        self.assertTrue(rule[0].startswith("-"), "may fail")
                    # Only a finger that matched may end the stack early;
                    # the empty answer's check may only skip the reader's
                    # lines, all of them, or not, and the disk's only
                    # gnome-keyring's password line, last.
                    if "pam_exec.so" in rule and "expose_authtok" in rule:
                        self.assertEqual(
                            rule[1:3], ["[success=ok", "default=10]"]
                        )
                        self.assertEqual(rule[-1], "/etc/greetd/finger-asked")
                        self.assertEqual(
                            rules[index + 11],
                            ["auth", "include", "system-local-login"],
                            "a typed password goes to its check",
                        )
                        skipped = rules[index + 1 : index + 11]
                        self.assertEqual(
                            [r for r in rules if "pam_fprintd.so" in r],
                            [r for r in skipped if "pam_fprintd.so" in r],
                            "and past every reader",
                        )
                    elif "pam_exec.so" in rule:
                        self.assertEqual(
                            rule[1:3], ["[success=1", "default=ignore]"]
                        )
                        self.assertEqual(
                            rule[-1], "/etc/greetd/disk-encrypted"
                        )
                        self.assertEqual(
                            rules[index + 1],
                            ["-auth", "optional", "pam_gnome_keyring.so"],
                        )
                        self.assertFalse(
                            any(
                                r[0] in ("auth", "-auth")
                                for r in rules[index + 2 :]
                            )
                        )
                    # done: the fingers' count cleared, which only a
                    # reader's success jumps to; a miss never jumps.
                    if any("done" in word for word in rule):
                        self.assertEqual(
                            rule[1:],
                            ["[success=done", "default=die]", *MATCHED],
                        )
                    if "pam_fprintd.so" in rule:
                        jump = int(rule[1].removeprefix("[success="))
                        self.assertEqual(
                            rules[index + jump + 1],
                            [
                                "auth",
                                "[success=done",
                                "default=die]",
                                *MATCHED,
                            ],
                        )
                        self.assertIn(
                            rule[2], ("maxtries=ignore", "maxtries=bad")
                        )
                        self.assertEqual(rule[3], "default=die]")
                        self.assertEqual(
                            rule[4:], READER_RULE, "one try a line"
                        )
                        # Its miss is counted by the next line, before
                        # anything else is asked.
                        self.assertEqual(
                            rules[index + 1][-len(MISSED) :], MISSED
                        )
                    # Nothing but the fingers' own count is ever cleared
                    # or added to here: the password's is system-auth's.
                    if "pam_faillock.so" in rule:
                        self.assertEqual(rule[-2:], FINGERS)


# A stand-in reader: says what pam_fprintd says, and matches once the test
# put a finger on it (touched), as pam_fprintd's PAM_SUCCESS; otherwise an
# authentication failure.
READER = """#!/bin/sh
echo "Place your finger on the fingerprint reader"
echo attempt >>"{folder}/reads"
[ -e "{folder}/touched" ]
"""
PASSWORD = """#!/bin/sh
read -r password
[ "$password" = "{secret}" ]
"""
# A stand-in disk-encrypted: / is on LUKS once the test says so (encrypted).
DISK = """#!/bin/sh
[ -e "{folder}/encrypted" ]
"""
# A stand-in pam_gnome_keyring's password line: notes whether it was given a
# password (given), never the password itself.
KEYRING = """#!/bin/sh
[ -n "$(tr -d '\\000' | head -c 1)" ] && echo given >>"{folder}/keyring-given"
exit 0
"""
# system-local-login as the system's ends: the password checked, failing as a
# wrong one does (and as pam_faillock counts it, noted in failures).
LOCAL_LOGIN = """auth [success=1 default=ignore] pam_exec.so expose_authtok quiet {folder}/password
auth [default=die] pam_exec.so quiet {folder}/count-failure
auth required pam_permit.so
account required pam_permit.so
session required pam_permit.so
"""


@unittest.skipIf(pam.available(), pam.available())
class Conversations(unittest.TestCase):
    """etc/pam.d/greetd as greetd runs it, in harness/pam.py's sandbox: the
    password's question once, an empty answer to the reader alone, and the
    fingers that did not match counted by pam_faillock itself, in a folder
    of the test's. The reader is a stand-in in place of pam_fprintd (a
    script, or pam_debug returning pam_fprintd's codes), finger-asked the
    repo's, system-local-login a password check, disk-encrypted and
    gnome-keyring's password line stand-ins too."""

    def setUp(self) -> None:
        self.folder = temporary(self)
        self.stacks = self.folder / "pam.d"
        self.stacks.mkdir()
        scripts = {
            "reader": READER.format(folder=self.folder),
            "password": PASSWORD.format(secret=SECRET),
            "count-failure": f'#!/bin/sh\necho failed >>"{self.folder}/failures"\nexit 1\n',
            "disk": DISK.format(folder=self.folder),
            "keyring": KEYRING.format(folder=self.folder),
        }
        for name, text in scripts.items():
            (self.folder / name).write_text(text)
            (self.folder / name).chmod(0o755)
        (self.stacks / "system-local-login").write_text(
            LOCAL_LOGIN.format(folder=self.folder)
        )
        # The fingers' count: pam_faillock's own, in a folder it makes.
        self.tally = self.folder / "faillock-finger"
        self.stack(DOTFILES / "etc/greetd/finger-asked")

    def fingers(self, *codes: str) -> dict[str, Any]:
        """A scan (an empty answer) whose tries end as codes say."""
        self.stack(
            DOTFILES / "etc/greetd/finger-asked", fingers=" ".join(codes)
        )
        return self.login("")

    def misses(self) -> int:
        """The fingers that did not match, as faillock(8) lists them."""
        listed = subprocess.run(
            ["faillock", "--dir", str(self.tally), "--user", USER],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return sum(
            line.rstrip().endswith(" V") for line in listed.splitlines()
        )

    def stack(
        self, finger_asked: Path, reader: str = "", fingers: str = ""
    ) -> None:
        """The repo's stack with its stand-ins. reader: the module in place
        of every pam_fprintd line (the stand-in reader by default).
        fingers: what each of the three tries returns instead, as
        pam_debug's names for PAM's codes: "maxtries" a finger that did not
        match, "authinfo_unavail" a timeout, "success" one that matched."""
        reader = reader or f"pam_exec.so quiet stdout {self.folder}/reader"
        text = (DOTFILES / "etc/pam.d/greetd").read_text()
        rule = " ".join(READER_RULE)
        self.assertEqual(text.count(rule), 3, "three tries")
        for code in fingers.split() or [""] * 3:
            module = f"pam_debug.so auth={code}" if code else reader
            text = text.replace(rule, module, 1)
        tally = " ".join(FINGERS)
        self.assertEqual(text.count(tally), 7, "one count for all")
        text = text.replace(tally, f"dir={self.tally} deny=5")
        text = text.replace("/etc/greetd/finger-asked", str(finger_asked))
        text = text.replace(
            "/etc/greetd/disk-encrypted", f"{self.folder}/disk"
        )
        keyring = "optional     pam_gnome_keyring.so\n"
        self.assertEqual(text.count(keyring), 1, "the password's line")
        text = text.replace(
            keyring,
            f"optional pam_exec.so quiet expose_authtok {self.folder}/keyring\n",
        )
        (self.stacks / "greetd").write_text(text)

    def keyring_given(self) -> bool:
        return (self.folder / "keyring-given").exists()

    def login(self, *answers: str) -> dict[str, Any]:
        done = subprocess.run(
            pam.command(
                self.stacks,
                "python3",
                str(TESTING / "harness/converse.py"),
                "greetd",
                USER,
            ),
            input=json.dumps(list(answers)),
            capture_output=True,
            text=True,
            check=True,
        )
        result: dict[str, Any] = json.loads(done.stdout)
        return result

    def said(self, result: dict[str, Any]) -> list[str]:
        return [message["text"] for message in result["said"]]

    def reads(self) -> int:
        reads = self.folder / "reads"
        return len(reads.read_text().splitlines()) if reads.exists() else 0

    def test_the_password_logs_in_without_the_reader(self) -> None:
        result = self.login(SECRET)
        self.assertEqual((result["authenticate"], result["account"]), (0, 0))
        self.assertEqual(self.said(result), ["Password: "], "asked once")
        self.assertEqual(self.reads(), 0, "a typed password never waits on it")

    def test_a_wrong_password_does_not(self) -> None:
        result = self.login("not the password")
        self.assertNotEqual(result["authenticate"], 0)
        self.assertEqual(self.reads(), 0)

    def test_an_empty_answer_asks_the_reader(self) -> None:
        (self.folder / "touched").touch()
        result = self.login("")
        self.assertEqual((result["authenticate"], result["account"]), (0, 0))
        self.assertIn(
            "Place your finger on the fingerprint reader", self.said(result)
        )
        self.assertEqual(self.reads(), 1)

    def test_a_reader_that_fails_ends_the_login_uncounted(self) -> None:
        result = self.login("")
        self.assertNotEqual(result["authenticate"], 0)
        self.assertEqual(self.reads(), 1, "no second try")
        self.assertFalse(
            (self.folder / "failures").exists(), "no wrong password"
        )
        self.assertEqual(self.misses(), 0)

    def test_a_timeout_is_not_counted(self) -> None:
        # The greeter's own scan times out whenever nobody is there.
        for _ in range(6):
            result = self.fingers("authinfo_unavail", "success", "success")
            self.assertNotEqual(result["authenticate"], 0)
        self.assertEqual(self.misses(), 0)
        self.assertEqual(self.fingers("success")["authenticate"], 0)

    def test_every_finger_that_does_not_match_is_counted(self) -> None:
        result = self.fingers("maxtries", "maxtries", "maxtries")
        self.assertNotEqual(result["authenticate"], 0)
        self.assertEqual(self.misses(), 3)
        self.assertFalse(
            (self.folder / "failures").exists(), "no wrong password"
        )

    def test_misses_before_a_timeout_are_counted(self) -> None:
        # Two misses, then waiting the third try out: pam_fprintd with
        # three tries of its own told nothing of them.
        result = self.fingers("maxtries", "maxtries", "authinfo_unavail")
        self.assertNotEqual(result["authenticate"], 0)
        self.assertEqual(self.misses(), 2)

    def test_a_second_or_third_try_that_matches_logs_in(self) -> None:
        for codes in (
            ("maxtries", "success"),
            ("maxtries",) * 2 + ("success",),
        ):
            with self.subTest(codes=codes):
                result = self.fingers(*codes)
                self.assertEqual(
                    (result["authenticate"], result["account"]), (0, 0)
                )
                self.assertEqual(self.misses(), 0, "cleared by the match")
                self.assertFalse(self.keyring_given())

    def test_after_five_misses_the_reader_is_not_asked(self) -> None:
        self.fingers("maxtries", "maxtries", "maxtries")
        self.fingers("maxtries", "maxtries", "success")
        self.assertEqual(self.misses(), 5)
        # The owner's finger would match now: no reader is asked at all.
        self.stack(DOTFILES / "etc/greetd/finger-asked")
        (self.folder / "touched").touch()
        result = self.login("")
        self.assertNotEqual(result["authenticate"], 0)
        self.assertEqual(self.reads(), 0)
        self.assertIn(REFUSED, self.said(result))
        self.assertEqual(self.misses(), 5)

    def test_the_password_still_logs_in_then_and_clears_them(self) -> None:
        self.fingers("maxtries", "maxtries", "maxtries")
        self.fingers("maxtries", "maxtries", "maxtries")
        self.assertNotEqual(self.fingers("success")["authenticate"], 0)
        result = self.login(SECRET)
        self.assertEqual((result["authenticate"], result["account"]), (0, 0))
        self.assertEqual(self.said(result), ["Password: "])
        self.assertEqual(self.misses(), 0)
        self.assertEqual(self.fingers("success")["authenticate"], 0)

    def test_a_wrong_password_leaves_the_fingers_count(self) -> None:
        self.fingers("maxtries", "authinfo_unavail")
        self.assertNotEqual(self.login("not the password")["authenticate"], 0)
        self.assertEqual(self.misses(), 1)

    def test_without_pam_fprintd_an_empty_answer_fails(self) -> None:
        self.stack(
            DOTFILES / "etc/greetd/finger-asked", "pam_not_installed.so"
        )
        result = self.login("")
        self.assertNotEqual(result["authenticate"], 0)
        self.assertEqual(self.login(SECRET)["authenticate"], 0)

    def test_on_an_encrypted_disk_gnome_keyring_gets_no_password(self) -> None:
        # It would encrypt the plain login keyring with it, which no finger
        # opens after.
        (self.folder / "encrypted").touch()
        self.assertEqual(self.login(SECRET)["authenticate"], 0)
        self.assertFalse(self.keyring_given())

    def test_on_an_unencrypted_disk_it_gets_the_password(self) -> None:
        self.assertEqual(self.login(SECRET)["authenticate"], 0)
        self.assertTrue(self.keyring_given(), "the keyring opens with it")

    def test_a_finger_gives_it_nothing(self) -> None:
        (self.folder / "touched").touch()
        self.assertEqual(self.login("")["authenticate"], 0)
        self.assertFalse(self.keyring_given())

    def test_without_finger_asked_the_password_still_works(self) -> None:
        self.stack(self.folder / "missing")
        (self.folder / "touched").touch()
        self.assertEqual(self.login(SECRET)["authenticate"], 0)
        self.assertNotEqual(self.login("")["authenticate"], 0)
        self.assertEqual(self.reads(), 0)


class FingerAsked(unittest.TestCase):
    """etc/greetd/finger-asked as pam_exec runs it: the answer on stdin with
    a NUL after it, and no PATH."""

    def asked(self, answer: bytes) -> int:
        return subprocess.run(
            ["/bin/sh", str(DOTFILES / "etc/greetd/finger-asked")],
            input=answer + b"\0",
            env={},
            capture_output=True,
            check=False,
        ).returncode

    def test_only_an_empty_answer_asks_for_a_finger(self) -> None:
        self.assertEqual(self.asked(b""), 0)
        for answer in (SECRET.encode(), b" ", b"0"):
            with self.subTest(answer=answer):
                self.assertNotEqual(self.asked(answer), 0)

    def test_a_password_is_none_where_no_tool_is_on_the_path(self) -> None:
        # A tool not found would read as an empty answer, and send every
        # password to the reader: PATH names nowhere, as a shell with no
        # default of its own would have it.
        done = subprocess.run(
            ["/bin/sh", str(DOTFILES / "etc/greetd/finger-asked")],
            input=SECRET.encode() + b"\0",
            env={"PATH": "/nowhere"},
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, b"")


@unittest.skipUnless(
    shutil.which("findmnt") and shutil.which("lsblk"), "util-linux"
)
class DiskEncrypted(unittest.TestCase):
    """etc/greetd/disk-encrypted on this machine: whether / is on LUKS, as
    the installer's tpm.root_volume() reads it."""

    def test_tells_this_machines_root(self) -> None:
        source = (
            subprocess.run(
                ["findmnt", "--noheadings", "-o", "SOURCE", "/"],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .split("[", 1)[0]
        )
        luks = source.startswith("/dev/mapper/") and "crypto_LUKS" in (
            subprocess.run(
                [
                    "lsblk",
                    "--noheadings",
                    "--inverse",
                    "--list",
                    "-o",
                    "FSTYPE",
                    source,
                ],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.split()
        )
        done = subprocess.run(
            [str(DOTFILES / "etc/greetd/disk-encrypted")], check=False
        )
        self.assertEqual(done.returncode == 0, luks)


def install(
    dest: Path, state: Path, cache: Path, **env: str
) -> subprocess.CompletedProcess[str]:
    """install-greeter.sh into a staging folder, as the user."""
    result = subprocess.run(
        ["bash", str(INSTALL), str(dest)],
        capture_output=True,
        text=True,
        env=environment(
            XDG_STATE_HOME=str(state), XDG_CACHE_HOME=str(cache), **env
        ),
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result


class Installing(unittest.TestCase):
    """install-greeter.sh copies the owner's choices into a folder the
    greeter user, and so everyone, can read."""

    def test_a_file_that_is_no_image_is_not_installed(self) -> None:
        # The owner can read their own key; it is no login image, and must
        # not become everyone's.
        tmp = temporary(self)
        key = tmp / "id_ed25519"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n")
        renamed = tmp / "key.jpg"
        renamed.symlink_to(key)
        state = tmp / "state"
        (state / "quickshell").mkdir(parents=True)
        for image in (key, renamed):
            (state / "quickshell/lockscreen.json").write_text(
                json.dumps(
                    {"loginBackground": "image", "loginImage": str(image)}
                )
            )
            dest = tmp / f"greetd-{image.name}"
            result = install(dest, state, tmp / "cache")
            self.assertIn("is not an image", result.stderr)
            self.assertFalse((dest / "quickshell/wallpaper.jpg").exists())
            self.assertFalse(
                any(
                    "secret" in path.read_text(errors="replace")
                    for path in dest.rglob("*")
                    if path.is_file()
                )
            )

    def test_nothing_installed_is_writable_but_by_its_owner(self) -> None:
        tmp = temporary(self)
        dest = tmp / "greetd"
        install(dest, tmp / "state", tmp / "cache")
        for path in [dest, *dest.rglob("*")]:
            mode = path.lstat().st_mode
            self.assertFalse(path.is_symlink(), path)
            self.assertEqual(mode & 0o022, 0, f"{path} is writable by others")
            self.assertEqual(mode & 0o004, 0o004, f"{path} is not readable")


# As root of a namespace with jane in it: /etc/passwd says who she is, her
# home is hers, the rest root's, and the folders after the home are bound
# over the system's (their names follow, then a --). Her files are root's
# again after, or the test could not remove them.
SETUP = """
mount --bind "$1" /etc/passwd && mount --bind "$2" /etc/group || exit 90
home=$3
shift 3
while [ "$1" != -- ]; do mount --bind "$1" "$2" || exit 90; shift 2; done
shift
chown -R -h 1000:1000 "$home"
"$@"
status=$?
chown -R -h 0:0 "$home"
exit $status
"""


@unittest.skipUnless(shutil.which("newuidmap"), "needs newuidmap")
class AsRoot(unittest.TestCase):
    """install-greeter.sh as the Lock Screen tab runs it: root's copy
    (scripts/install-system.sh puts it in /usr/local/lib/jupiter/greeter)
    through pkexec, PKEXEC_UID the owner's and --from her clone. What she
    cannot read must not get out, and what runs as root (greetd's config, the
    PAM stacks) must be root's copy, whatever her clone says."""

    def setUp(self) -> None:
        self.root = Path(
            self.enterContext(tempfile.TemporaryDirectory(dir="/tmp"))
        )
        self.root.chmod(0o755)
        self.home = self.root / "home/jane"
        private = self.root / "root-only"
        private.mkdir(mode=0o700)
        self.secret = private / "secret.jpg"
        self.secret.write_bytes(JPEG + f"\n{ROOT_ONLY}\n".encode())
        self.state = self.home / ".local/state"
        cache = self.home / ".cache"
        for folder in (
            self.state / "quickshell",
            self.state / "wallust",
            cache / "wallust",
        ):
            folder.mkdir(parents=True)
        (self.root / "passwd").write_text(
            "root:x:0:0::/root:/bin/bash\n"
            f"jane:x:{OWNER}:{OWNER}:Jane:{self.home}:/bin/bash\n"
        )
        (self.root / "group").write_text(f"root:x:0:\njane:x:{OWNER}:\n")
        # Her clone of the dotfiles, which the Settings app names.
        self.repo = self.home / DOTFILES.name
        shutil.copytree(
            DOTFILES,
            self.repo,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*_cache"),
        )
        # Root's copy of the installer, as install-system.sh leaves it.
        system = self.root / "system"
        subprocess.run(
            ["bash", str(DOTFILES / "scripts/install-system.sh"), str(system)],
            capture_output=True,
            check=True,
            env=environment(),
        )
        self.trusted = system / "usr/local/lib/jupiter/greeter"

    def install(
        self, dest: str, binds: tuple[tuple[Path, str], ...] = ()
    ) -> subprocess.CompletedProcess[str]:
        bound = [part for pair in binds for part in (str(pair[0]), pair[1])]
        result = subprocess.run(
            [
                "unshare",
                "--map-auto",
                "--map-root-user",
                "--mount",
                "--",
                "sh",
                "-c",
                SETUP,
                "sh",
                str(self.root / "passwd"),
                str(self.root / "group"),
                str(self.root / "home"),
                *bound,
                "--",
                "bash",
                str(self.trusted / "scripts/install-greeter.sh"),
                "--from",
                str(self.repo),
                dest,
            ],
            capture_output=True,
            text=True,
            # What pkexec leaves: no XDG folders, the caller's uid.
            env={
                "PATH": "/usr/bin",
                "PKEXEC_UID": str(OWNER),
                **{
                    key: value
                    for key, value in os.environ.items()
                    if key.startswith(("COVERAGE_", "BASH_ENV", "CHECK_RAN"))
                },
            },
            check=False,
        )
        if result.returncode == 90 or "newuidmap" in result.stderr:
            self.skipTest(f"no namespace for two users: {result.stderr}")
        return result

    def leaked(self, dest: Path) -> list[str]:
        return [
            str(path.relative_to(dest))
            for path in dest.rglob("*")
            if path.is_file() and ROOT_ONLY.encode() in path.read_bytes()
        ]

    def test_the_owners_files_are_read_as_the_owner(self) -> None:
        # Her login image is root's file, named outright; everything else
        # she has is a link to it.
        (self.state / "quickshell/lockscreen.json").write_text(
            json.dumps(
                {"loginBackground": "image", "loginImage": str(self.secret)}
            )
        )
        for link in (
            self.state / "quickshell/monitors.lua",
            self.state / "quickshell/keyboard.lua",
            self.state / "quickshell/appearance.json",
            self.state / "quickshell/hyprpaper.conf",
            self.state / "wallust/theme",
            self.home / ".cache/wallust/quickshell.json",
        ):
            link.symlink_to(self.secret)
        dest = self.root / "greetd"
        result = self.install(str(dest))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"no wallpaper at '{self.secret}'", result.stderr)
        self.assertEqual(self.leaked(dest), [], "copied as root")

    def test_her_clone_is_read_as_her(self) -> None:
        # A greeter file of her clone that is a link to root's: it cannot be
        # read, and the install stops.
        (self.repo / "etc/greetd/quickshell/Stolen.qml").symlink_to(
            self.secret
        )
        dest = self.root / "greetd"
        result = self.install(str(dest))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.leaked(dest), [], "copied as root")

    @unittest.skipUnless(Path("/etc/greetd").is_dir(), "needs /etc/greetd")
    def test_what_runs_as_root_is_roots(self) -> None:
        # Her clone would have greetd run the greeter as root, and let anyone
        # in without a password.
        (self.repo / "etc/greetd/config.toml").write_text(
            '[default_session]\ncommand = "sh"\nuser = "root"\n'
        )
        for name in ("greetd", "greetd-greeter"):
            (self.repo / "etc/pam.d" / name).write_text(
                "auth sufficient pam_permit.so\n"
            )
        # The real install, into stand-ins bound over /etc/greetd and
        # /etc/pam.d.
        greetd = self.root / "etc-greetd"
        pam = self.root / "etc-pam.d"
        greetd.mkdir()
        pam.mkdir()
        result = self.install(
            "/etc/greetd", ((greetd, "/etc/greetd"), (pam, "/etc/pam.d"))
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (greetd / "config.toml").read_text(),
            (DOTFILES / "etc/greetd/config.toml").read_text(),
        )
        for name in ("greetd", "greetd-greeter"):
            self.assertEqual(
                (pam / name).read_text(),
                (DOTFILES / "etc/pam.d" / name).read_text(),
            )
        # And what the greeter user runs is still hers, as she changed it.
        self.assertEqual(
            (greetd / "quickshell/GreeterService.qml").read_text(),
            (
                self.repo / "etc/greetd/quickshell/GreeterService.qml"
            ).read_text(),
        )


class Applying(unittest.TestCase):
    """What the Lock Screen tab's Apply runs as root, and what that reads."""

    def test_apply_runs_roots_copy(self) -> None:
        page = (
            DOTFILES / ".config/quickshell/settings/LockPage.qml"
        ).read_text()
        [installer] = [
            block
            for block in source.objects(page, "Process")
            if "pkexec" in block.text
        ]
        command = source.binding(installer.text, "command") or ""
        self.assertIn(
            '"/usr/local/lib/jupiter/greeter/scripts/install-greeter.sh"',
            command,
        )
        self.assertIn('exec pkexec \\"$1\\" --from', command)
        # Only the clone is named from the home, and only after --from.
        self.assertEqual(command.count("Quickshell.shellDir"), 1)

    def test_root_reads_the_clone_only_as_the_owner(self) -> None:
        script = INSTALL.read_text()
        for number, line in enumerate(script.splitlines(), 1):
            if '"$repo' in line or "$repo/" in line:
                with self.subTest(line=number):
                    # Through owned (copy() is), a path named for that, or
                    # the loop over the names copy() reads.
                    self.assertTrue(
                        "owned " in line
                        or re.fullmatch(r"\s*\w+=\$repo/\S+", line)
                        or line.lstrip().startswith(("for f in", "echo "))
                        or line.lstrip().startswith("copy "),
                        f"install-greeter.sh:{number} reads the clone as root: {line}",
                    )
        for trusted in (
            '"$self/etc/greetd/config.toml"',
            '"$self/etc/pam.d/greetd"',
            '"$self/etc/pam.d/greetd-greeter"',
        ):
            self.assertIn(trusted, script)


if __name__ == "__main__":
    unittest.main()
