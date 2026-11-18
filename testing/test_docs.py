"""The Markdown in the three repos names what is there: each relative link
leads to a file, each path in backticks is one the repos hold (written from
the repo's root, from the document's folder, or from a folder further in,
as `style/Colors.qml` for .config/quickshell/style/Colors.qml), and each
`file.Name` names a class or function that file defines. A rename that
leaves a document behind fails here rather than misleading its next reader.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

from harness import DOTFILES, INSTALLER, TESTING

REPOS = {"dotfiles": DOTFILES, "installer": INSTALLER, "testing": TESTING}
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
# A path of two parts at least, without a glob or a placeholder in it.
PATH = re.compile(r"`(\.{0,2}[\w.-]*(?:/[\w.-]+)+/?)`")
# Folders of an installed system, which documents name relative to a prefix.
SYSTEM = {"share", "X11", "lib", "etc"}
# installer/test_phase1.Installing, a test's module and a name in it.
NAME = re.compile(r"`([\w/]+)\.([A-Z]\w*)`")


def tracked(repo: Path) -> list[str]:
    found = subprocess.run(
        ["git", "ls-files"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return found.stdout.splitlines() if found.returncode == 0 else []


class Documents(unittest.TestCase):
    files: dict[str, list[str]]
    paths: set[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.files = {name: tracked(repo) for name, repo in REPOS.items()}
        if not all(cls.files.values()):
            raise unittest.SkipTest("needs the three repos as git clones")
        # Every tracked file and folder, as a path from its repo's root.
        cls.paths = set()
        for files in cls.files.values():
            for file in files:
                parts = file.split("/")
                for end in range(1, len(parts) + 1):
                    cls.paths.add("/".join(parts[:end]))

    def known(self, path: str) -> bool:
        """A path some repo holds, from its root or from a folder in it; a
        QML type or a Python module may leave its extension off."""
        path = path.removeprefix("./").rstrip("/")
        for name in REPOS:
            for prefix in (f"Jupiter-{name}/", f"../Jupiter-{name}/"):
                path = path.removeprefix(prefix)
        path = path.removeprefix("../")
        return any(
            ("/" + known).endswith("/" + path)
            or ("/" + known.rsplit(".", 1)[0]).endswith("/" + path)
            for known in self.paths
        )

    def documents(self) -> list[tuple[str, Path, str]]:
        return [
            (name, REPOS[name] / file, (REPOS[name] / file).read_text())
            for name, files in self.files.items()
            for file in files
            # A deletion not yet committed is no document.
            if file.endswith(".md") and (REPOS[name] / file).exists()
        ]

    def test_relative_links_lead_somewhere(self) -> None:
        for name, document, text in self.documents():
            for link in LINK.findall(text):
                if "://" in link or link.startswith("mailto:"):
                    continue
                with self.subTest(
                    document=f"{name}/{document.name}", link=link
                ):
                    self.assertTrue((document.parent / link).exists())

    def test_paths_in_backticks_are_there(self) -> None:
        for name, document, text in self.documents():
            for path in PATH.findall(text):
                if self.outside(path):
                    continue
                with self.subTest(
                    document=f"{name}/{document.name}", path=path
                ):
                    self.assertTrue(self.known(path))

    def outside(self, path: str) -> bool:
        """Not a repo's path: one of an installed system (share/... under a
        prefix, X11/xkb), a sibling folder (`../Jupiter-testing`, or one a
        test lays out), a range of names (min/max), or a test's name
        (`module.Name`, which test_named_tests_are_defined checks)."""
        if path.startswith(("/", "~")) or NAME.fullmatch(f"`{path}`"):
            return True
        if self.known(path):
            return False
        first = path.lstrip("./").split("/", 1)[0]
        return (
            first in SYSTEM
            or re.fullmatch(r"\.\./[\w.-]+/?", path) is not None
            or re.fullmatch(r"\w+_min/max", path) is not None
        )

    def modules(self, module: str) -> list[Path]:
        """The files a `module.Name` may mean: module.py, or a package's
        __init__.py, at a repo's root or in any folder of it."""
        names = (f"{module}.py", f"{module}/__init__.py")
        return [
            REPOS[repo] / file
            for repo, files in self.files.items()
            for file in files
            if file in names or file.endswith(tuple(f"/{n}" for n in names))
        ]

    def test_named_tests_are_defined(self) -> None:
        for name, document, text in self.documents():
            for module, defined in NAME.findall(text):
                files = self.modules(module)
                # A bare word.Name with no such module is prose (a domain,
                # a file name), unless it names a path.
                if not files and "/" not in module:
                    continue
                with self.subTest(
                    document=f"{name}/{document.name}",
                    name=f"{module}.{defined}",
                ):
                    self.assertTrue(files, f"no module {module}")
                    self.assertTrue(
                        any(
                            re.search(
                                rf"(?m)^\s*(class {defined}\b|def {defined}\b"
                                rf"|{defined}\b[^=\n]*=)",
                                file.read_text(),
                            )
                            for file in files
                        ),
                        f"{module} defines no {defined}",
                    )


if __name__ == "__main__":
    unittest.main()
