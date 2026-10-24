"""What the suites share: where the two repos are, helpers loaded by path,
stand-in commands and throwaway folders.

The repos are found next to this one (../Jupiter-dotfiles and
../Jupiter-installer), or wherever JUPITER_DOTFILES and JUPITER_INSTALLER
point. Nothing here, and no test, changes anything outside a temporary
folder: every command a helper would reach the system with is a stand-in.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

TESTING = Path(__file__).resolve().parent.parent
DOTFILES = Path(
    os.environ.get("JUPITER_DOTFILES") or TESTING.parent / "Jupiter-dotfiles"
).resolve()
INSTALLER = Path(
    os.environ.get("JUPITER_INSTALLER") or TESTING.parent / "Jupiter-installer"
).resolve()
QUICKSHELL = DOTFILES / ".config/quickshell"

# The stand-in password every login, lock and keyring test types. The QML
# runner fails a file whose log shows it anywhere, and so do the helpers'
# tests for what they print.
SECRET = "correct horse battery staple"


def load(path: Path) -> Any:
    """A helper script as a module, by path: most have a dash in their name
    and none is in a package."""
    name = path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    # Registered, so a dataclass or pickle inside it finds its module.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def executable(path: Path, text: str) -> Path:
    """Write a script (a stand-in command, usually) and make it runnable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


def temporary(case: unittest.TestCase) -> Path:
    """A folder that lives as long as the test."""
    return Path(case.enterContext(tempfile.TemporaryDirectory()))


def environment(**changes: str | None) -> dict[str, str]:
    """This process's environment with changes, None removing a variable,
    and without the XDG folders of whoever runs the tests."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("XDG_")
    }
    for key, value in changes.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env
