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
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from harness import DOTFILES, environment, load, qml, temporary

QML = Path(__file__).resolve().parent / "qml"
GREETER_ENV = DOTFILES / "etc/greetd/quickshell/greeter-env.py"
INSTALL = DOTFILES / "scripts/install-greeter.sh"
greeter_env = load(GREETER_ENV)

# The smallest file `file` takes for a JPEG, and a marker for what only root
# may read.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
ROOT_ONLY = "ROOT-ONLY-CONTENT"
OWNER = 1000


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
                ["auth", "include", "system-local-login"],
                ["-auth", "optional", "pam_gnome_keyring.so"],
                ["account", "include", "system-local-login"],
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
            for rule in self.rules(name):
                with self.subTest(stack=name, rule=" ".join(rule)):
                    self.assertNotIn(rule[1], ("sufficient",))
                    self.assertNotIn(
                        rule[2],
                        ("pam_permit.so", "pam_rootok.so", "pam_exec.so"),
                    )
                    if rule[1] == "optional":
                        self.assertTrue(rule[0].startswith("-"), "may fail")


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

    @unittest.skipUnless(shutil.which("newuidmap"), "needs newuidmap")
    def test_as_root_the_owners_files_are_read_as_the_owner(self) -> None:
        """As pkexec runs it: root, with PKEXEC_UID the owner's. The owner's
        login image is a file only root can read, and each other file of
        hers the script copies a link to it; none of it may reach the
        installed tree."""
        root = Path(self.enterContext(tempfile.TemporaryDirectory(dir="/tmp")))
        root.chmod(0o755)
        home = root / "home/jane"
        private = root / "root-only"
        private.mkdir(mode=0o700)
        secret = private / "secret.jpg"
        secret.write_bytes(JPEG + f"\n{ROOT_ONLY}\n".encode())
        state = home / ".local/state"
        cache = home / ".cache"
        for folder in (
            state / "quickshell",
            state / "wallust",
            cache / "wallust",
        ):
            folder.mkdir(parents=True)
        # Her login image is root's file, named outright; everything else
        # she has is a link to it.
        (state / "quickshell/lockscreen.json").write_text(
            json.dumps({"loginBackground": "image", "loginImage": str(secret)})
        )
        for link in (
            state / "quickshell/monitors.lua",
            state / "quickshell/keyboard.lua",
            state / "quickshell/appearance.json",
            state / "quickshell/hyprpaper.conf",
            state / "wallust/theme",
            cache / "wallust/quickshell.json",
        ):
            link.symlink_to(secret)
        passwd = root / "passwd"
        passwd.write_text(
            "root:x:0:0::/root:/bin/bash\n"
            f"jane:x:{OWNER}:{OWNER}:Jane:{home}:/bin/bash\n"
        )
        group = root / "group"
        group.write_text(f"root:x:0:\njane:x:{OWNER}:\n")
        dest = root / "greetd"
        # Her clone of the dotfiles, which the Settings app runs it from.
        repo = home / DOTFILES.name
        shutil.copytree(
            DOTFILES,
            repo,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*_cache"),
        )
        # As root of a namespace with jane in it: /etc/passwd says who she
        # is, her home is hers, the private folder root's. Her files are
        # root's again after, or the test could not remove them.
        setup = (
            'mount --bind "$1" /etc/passwd && mount --bind "$2" /etc/group'
            ' && chown -R -h 1000:1000 "$3" && home=$3 && shift 3'
            ' && { "$@"; status=$?; chown -R -h 0:0 "$home"; exit $status; }'
        )
        result = subprocess.run(
            [
                "unshare",
                "--map-auto",
                "--map-root-user",
                "--mount",
                "--",
                "sh",
                "-c",
                setup,
                "sh",
                str(passwd),
                str(group),
                str(root / "home"),
                "bash",
                str(repo / INSTALL.relative_to(DOTFILES)),
                str(dest),
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
        if "newuidmap" in result.stderr or "unshare:" in result.stderr:
            self.skipTest(f"no namespace for two users: {result.stderr}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"no wallpaper at '{secret}'", result.stderr, "refused as jane"
        )
        leaked = [
            str(path.relative_to(dest))
            for path in dest.rglob("*")
            if path.is_file() and ROOT_ONLY.encode() in path.read_bytes()
        ]
        self.assertEqual(leaked, [], "copied as root, readable by everyone")


if __name__ == "__main__":
    unittest.main()
