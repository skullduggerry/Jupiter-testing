"""The QML tests: each *Test.qml, run inside Quickshell itself.

Every file gets a Quickshell of its own, offscreen and in a throwaway home,
with nothing of the session around it: no display, no D-Bus, no Hyprland,
nothing on PATH. harness/qml/shell.qml runs its test_ functions, and a test
can use any singleton, as a service that reaches for the desktop fails here
instead of acting on it.

A file is staged in a short folder under /tmp (Quickshell's IPC socket
lives in the runtime folder, and a socket's path must stay short):

    tests/      the file, TestCase.qml and shell.qml: the shell's folder,
                Quickshell.shellDir to the code under test
    shell/      a copy of the dotfiles' .config/quickshell, which the tests
                import as "../shell/services" and so on
    greeter/    the login screen as scripts/install-greeter.sh installs it:
                etc/greetd/quickshell with a copy of style/ beside it

What else a file runs with comes from fixtures/<its name>/ beside it:

    pam.d/      the stacks it runs with as /etc/pam.d (harness/pam.py)
    greetd.json a stand-in greetd's scenario (harness/greetd.py), its
                socket in GREETD_SOCK and what it was asked in GREETD_LOG
    theme/      the desktop's theme as installed beside the login screen,
                read only, in LOCKSCREEN_THEME
    runtime/    copied into XDG_RUNTIME_DIR, with HYPRLAND_INSTANCE_SIGNATURE
                naming its hypr/<signature>/
    bin/        PATH, which is empty otherwise
    anything else is copied into tests/ (a stand-in pam/, greeter-env.py)

Text files among them have @FIXTURES@ (the copy's own folder), @SECRET@ and
@PYTHON@ filled in. A file named Greeter*Test.qml runs as the login screen
does, with HOME=/nonexistent and no XDG folders.

A test fails on a FAIL line, and so does its file on any warning or error
Quickshell logs, as the running shell would show them in its log, except
those a test let through with ignoreWarning(), and on any line that shows
harness.SECRET.

    python3 -m harness.qml dotfiles/qml/ColorsTest.qml ...
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path

from . import DOTFILES, QUICKSHELL, SECRET, pam
from .greetd import Greetd

HARNESS = Path(__file__).resolve().parent / "qml"
TIMEOUT = 60  # seconds for one file
SIGNATURE = "qmltest"
RESULT = re.compile(r"\bqml: (PASS|FAIL|DONE|IGNORE)\b ?(.*)")
PROBLEM = re.compile(r"^\s*(WARN|ERROR|FATAL|CRITICAL)\b")
SPECIAL = {"pam.d", "greetd.json", "theme", "runtime", "bin", "share"}
IGNORE = shutil.ignore_patterns("__pycache__")


def stage(test: Path, root: Path) -> Path:
    """The folders a file runs in; returns the fixtures' copy."""
    tests = root / "tests"
    tests.mkdir()
    for name in ("TestCase.qml", "shell.qml"):
        shutil.copy(HARNESS / name, tests)
    shutil.copy(test, tests)
    shutil.copytree(QUICKSHELL, root / "shell", ignore=IGNORE)
    greeter = root / "greeter"
    shutil.copytree(DOTFILES / "etc/greetd/quickshell", greeter, ignore=IGNORE)
    shutil.copytree(QUICKSHELL / "style", greeter / "style", ignore=IGNORE)

    fixtures = root / "fixtures"
    source = test.parent / "fixtures" / test.stem
    if source.is_dir():
        shutil.copytree(source, fixtures, ignore=IGNORE)
    else:
        fixtures.mkdir()
    for path in fixtures.rglob("*"):
        if path.is_file() and not path.is_symlink():
            fill(path, fixtures)
    for path in fixtures.iterdir():
        if path.name not in SPECIAL:
            target = tests / path.name
            if path.is_dir():
                shutil.copytree(path, target, symlinks=True)
            else:
                shutil.copy2(path, target)
    return fixtures


def fill(path: Path, fixtures: Path) -> None:
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        return
    filled = (
        text.replace("@FIXTURES@", str(fixtures))
        .replace("@SECRET@", SECRET)
        .replace("@PYTHON@", sys.executable)
    )
    if filled != text:
        path.write_text(filled)


def environment(test: Path, root: Path, fixtures: Path) -> dict[str, str]:
    runtime = root / "run"
    runtime.mkdir(mode=0o700)
    env = {
        "PATH": str(fixtures / "bin"),
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "XDG_RUNTIME_DIR": str(runtime),
        "QT_QPA_PLATFORM": "offscreen",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
        "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent",
        "QML_TEST": str(root / "tests" / test.name),
        "QML_SECRET": SECRET,
    }
    if (fixtures / "runtime").is_dir():
        shutil.copytree(fixtures / "runtime", runtime, dirs_exist_ok=True)
        env["HYPRLAND_INSTANCE_SIGNATURE"] = SIGNATURE
    # The desktop entries a file sees are its own, never the machine's.
    if (fixtures / "share").is_dir():
        env["XDG_DATA_DIRS"] = str(fixtures / "share")
    if (fixtures / "theme").is_dir():
        theme = fixtures / "theme"
        for path in [*theme.rglob("*"), theme]:
            path.chmod(0o555 if path.is_dir() else 0o444)
        env["LOCKSCREEN_THEME"] = str(theme)
    if test.name.startswith("Greeter"):
        return env | {"HOME": "/nonexistent"}
    home = root / "home"
    return env | {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
    }


def run(test: Path) -> list[str]:
    """The failures in one file, as lines to print."""
    qs = shutil.which("qs")
    if qs is None:
        return ["qs (quickshell) is not installed"]
    with tempfile.TemporaryDirectory(prefix="qmltest.", dir="/tmp") as tmp:
        root = Path(tmp)
        fixtures = stage(test, root)
        env = environment(test, root, fixtures)
        command = [qs, "--no-color", "-p", str(root / "tests/shell.qml")]
        if (fixtures / "pam.d").is_dir():
            if why := pam.available():
                raise unittest.SkipTest(why)
            command = pam.command(fixtures / "pam.d", *command)
        scenario = fixtures / "greetd.json"
        if not scenario.exists():
            return watch(command, env)
        env |= {
            "GREETD_SOCK": str(root / "greetd.sock"),
            "GREETD_LOG": str(root / "greetd.log"),
        }
        with Greetd(
            root / "greetd.sock",
            root / "greetd.log",
            json.loads(scenario.read_text()),
        ):
            return watch(command, env)


def watch(command: list[str], env: dict[str, str]) -> list[str]:
    failures: list[str] = []
    ignored: list[re.Pattern[str]] = []
    log: list[str] = []
    done = False
    with subprocess.Popen(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ) as process:
        watchdog = threading.Timer(TIMEOUT, process.kill)
        watchdog.start()
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip("\n")
            log.append(line)
            if SECRET in line:
                failures.append(f"the password is in the log: {line}")
            if match := RESULT.search(line):
                kind, text = match.groups()
                if kind == "FAIL":
                    failures.append(text)
                elif kind == "IGNORE":
                    ignored.append(re.compile(text))
                elif kind == "DONE":
                    done = True
                    break
            elif PROBLEM.match(line) and not any(
                pattern.search(line) for pattern in ignored
            ):
                failures.append(line.strip())
        process.terminate()
        watchdog.cancel()
    if not done:
        failures.append("never finished; its log:")
        failures.extend(log[-20:])
    return failures


def files(
    directory: Path, pattern: str = "*Test.qml"
) -> Callable[[type[unittest.TestCase]], type[unittest.TestCase]]:
    """A class decorator: a test_<Name> per QML file matching `pattern` in
    `directory`, so `python3 -m unittest -k LockServiceTest` runs one."""

    def decorate(cls: type[unittest.TestCase]) -> type[unittest.TestCase]:
        for path in sorted(directory.glob(pattern)):

            def test(self: unittest.TestCase, path: Path = path) -> None:
                failures = run(path)
                if failures:
                    self.fail("\n".join(["", *failures]))

            test.__doc__ = f"{path.relative_to(directory.parent)}"
            setattr(cls, f"test_{path.stem}", test)
        return cls

    return decorate


def main() -> int:
    failed = 0
    for name in sys.argv[1:]:
        test = Path(name).resolve()
        try:
            failures = run(test)
        except unittest.SkipTest as skipped:
            print(f"skip  {test.name}: {skipped}")
            continue
        print(f"{'FAIL' if failures else 'ok  '}  {test.name}")
        for failure in failures:
            print(f"      {failure}")
        failed += bool(failures)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
