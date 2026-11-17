"""scripts/ci-repos.sh, which lays the repos out for CI: every kind there,
each told by its files, from the pushed branch where its repo has that kind
on it, else from the default branch.

GitHub is a folder of bare repos (JUPITER_GITHUB); each branch holds only
the file its kind is told by.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from harness import TESTING, temporary

SCRIPT = TESTING / "scripts/ci-repos.sh"
# The file each kind is told by (check.sh's kind_of).
FILES = {
    "dotfiles": [".config/quickshell/shell.qml"],
    "installer": ["jupiter/__main__.py"],
    "testing": ["harness/qml.py"],
}
GIT = [
    "-c",
    "user.name=test",
    "-c",
    "user.email=test",
    "-c",
    "init.defaultBranch=main",
]


def git(*arguments: str | Path, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *GIT, *map(str, arguments)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class Layout(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.github = self.tmp / "github"

    def repo(self, name: str, **branches: str) -> None:
        """A repo on the stand-in GitHub: branch=kind, main first."""
        tree = self.tmp / "trees" / name
        tree.mkdir(parents=True)
        git("init", "-q", tree)
        for branch, kind in branches.items():
            git("checkout", "-q", "--orphan", branch, cwd=tree)
            git("rm", "-rq", "--cached", "--ignore-unmatch", ".", cwd=tree)
            for path in tree.iterdir():
                if path.name != ".git":
                    subprocess.run(["rm", "-rf", str(path)], check=True)
            for file in FILES[kind]:
                (tree / file).parent.mkdir(parents=True, exist_ok=True)
                (tree / file).write_text(f"{name} {branch}\n")
            git("add", ".", cwd=tree)
            git("commit", "-qm", branch, cwd=tree)
        git("clone", "-q", "--bare", tree, self.github / f"{name}.git")
        git("--git-dir", self.github / f"{name}.git", "symbolic-ref",
            "HEAD", "refs/heads/main")  # fmt: skip

    def push(self, name: str, branch: str) -> Path:
        """The pushed repo, as actions/checkout leaves it, in a workspace of
        its own."""
        self.work = self.tmp / f"workspace-{len(list(self.tmp.iterdir()))}"
        self.work.mkdir()
        checkout = self.work / "checkout"
        git("clone", "-q", "--branch", branch,
            self.github / f"{name}.git", checkout)  # fmt: skip
        return checkout

    def layout(
        self, name: str, branch: str, **env: str
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        self.push(name, branch)
        done = subprocess.run(
            [str(SCRIPT), "checkout", branch],
            cwd=self.work,
            env=os.environ | {"JUPITER_GITHUB": str(self.github)} | env,
            capture_output=True,
            text=True,
            check=False,
        )
        found = {}
        for folder in sorted(self.work.iterdir()):
            [content] = {
                (folder / file).read_text().strip()
                for files in FILES.values()
                for file in files
                if (folder / file).exists()
            }
            found[folder.name] = content
        return done, found

    def test_each_repo_from_the_branch_where_it_has_it(self) -> None:
        self.repo("Jupiter-dotfiles", main="dotfiles", work="dotfiles")
        self.repo("Jupiter-testing", main="testing")
        self.repo("Jupiter-installer", main="installer", work="installer")
        done, found = self.layout("Jupiter-dotfiles", "work")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            found,
            {
                "Jupiter-dotfiles": "Jupiter-dotfiles work",
                "Jupiter-installer": "Jupiter-installer work",
                "Jupiter-testing": "Jupiter-testing main",
            },
        )
        self.assertIn("Jupiter-installer: Jupiter-installer@work", done.stdout)

    def test_a_push_to_main_gets_main(self) -> None:
        self.repo("Jupiter-dotfiles", main="dotfiles")
        self.repo("Jupiter-testing", main="testing")
        self.repo("Jupiter-installer", main="installer", work="installer")
        done, found = self.layout("Jupiter-installer", "main")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(found["Jupiter-installer"], "Jupiter-installer main")
        self.assertIn("Jupiter-installer: the push", done.stdout)

    def test_testing_pushed_is_the_one_tested_with(self) -> None:
        self.repo("Jupiter-dotfiles", main="dotfiles")
        self.repo("Jupiter-testing", main="testing", work="testing")
        self.repo("Jupiter-installer", main="installer")
        done, found = self.layout("Jupiter-testing", "work")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(found["Jupiter-testing"], "Jupiter-testing work")
        self.assertEqual(found["Jupiter-dotfiles"], "Jupiter-dotfiles main")

    def test_a_branch_holding_something_else_is_passed_over(self) -> None:
        # Told by its files: a branch of the installer's repo that holds no
        # installer is not taken for one.
        self.repo("Jupiter-dotfiles", main="dotfiles", work="dotfiles")
        self.repo("Jupiter-testing", main="testing")
        self.repo("Jupiter-installer", main="installer", work="testing")
        done, found = self.layout("Jupiter-dotfiles", "work")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(found["Jupiter-installer"], "Jupiter-installer main")

    def test_a_repo_found_nowhere_fails_naming_where_it_looked(self) -> None:
        self.repo("Jupiter-dotfiles", main="dotfiles")
        self.repo("Jupiter-testing", main="testing")
        self.repo("Jupiter-installer", main="testing")
        done, _ = self.layout("Jupiter-dotfiles", "main")
        self.assertEqual(done.returncode, 2)
        self.assertIn("found no installer in", done.stderr)
        self.assertIn("Jupiter-installer@main", done.stderr)


class Workflows(unittest.TestCase):
    """Each tested repo's check.yml lays the repos out and checks that repo
    alone, on Arch and on NixOS; this repo's Actions only mirror it."""

    WORKFLOWS = Path(".github/workflows")

    def workflow(self, repo: Path) -> str:
        """Its steps, without the comments that describe them."""
        path = repo / self.WORKFLOWS / "check.yml"
        if not path.exists():
            self.skipTest(f"no {path}")
        return "".join(
            line
            for line in path.read_text().splitlines(keepends=True)
            if not line.lstrip().startswith("#")
        )

    def test_each_repo_checks_itself_alone(self) -> None:
        from harness import DOTFILES, INSTALLER

        for repo, kind, other in (
            (DOTFILES, "dotfiles", "installer"),
            (INSTALLER, "installer", "dotfiles"),
        ):
            with self.subTest(repo=repo.name):
                text = self.workflow(repo)
                self.assertIn("scripts/ci-repos.sh checkout", text)
                self.assertIn(f"cd Jupiter-{kind}\n", text)
                self.assertIn("./check.sh lint\n", text)
                self.assertIn(f"./check.sh test {kind}\n", text)
                self.assertIn(f"scripts/nixos-check.sh {kind}\n", text)
                for elsewhere in (
                    "test all",
                    f"test {other}",
                    f"nixos-check.sh {other}",
                    "nixos-check.sh\n",
                ):
                    self.assertNotIn(
                        elsewhere,
                        text,
                        f"{repo.name}'s check.yml checks more than itself",
                    )

    def test_the_installer_tests_its_nixos_side(self) -> None:
        from harness import INSTALLER

        self.assertIn("JUPITER_NIXPKGS", self.workflow(INSTALLER))

    def test_this_repo_only_mirrors(self) -> None:
        self.assertEqual(
            sorted(p.name for p in (TESTING / self.WORKFLOWS).iterdir()),
            ["mirror-codeberg.yml"],
        )


# check.sh's stand-in: records its arguments; with --fix it changes the
# pushed repo's file when $FORMAT is set, as a formatter would.
CHECK = """#!/bin/sh
echo "$*" >>"$CALLS"
case "$*" in *--fix*) [ -n "$FORMAT" ] && echo formatted >>"$2/file" ;; esac
exit 0
"""


class PrePush(unittest.TestCase):
    """.githooks/pre-push: the pushed repo linted (formatted first), then
    every repo's suites, Arch's and NixOS's; a change formatting made stops
    the push before them."""

    def setUp(self) -> None:
        self.tmp = temporary(self)
        hooks = self.tmp / "testing/.githooks"
        hooks.mkdir(parents=True)
        (hooks / "pre-push").write_text(
            (TESTING / ".githooks/pre-push").read_text()
        )
        (hooks / "pre-push").chmod(0o755)
        (self.tmp / "testing/check.sh").write_text(CHECK)
        (self.tmp / "testing/check.sh").chmod(0o755)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        (self.repo / "file").write_text("as committed\n")
        git("init", "-q", self.repo)
        git("add", ".", cwd=self.repo)
        git("commit", "-qm", "x", cwd=self.repo)
        self.calls = self.tmp / "calls"

    def push(self, **env: str) -> tuple[int, list[str]]:
        self.calls.write_text("")
        done = subprocess.run(
            [str(self.tmp / "testing/.githooks/pre-push")],
            cwd=self.repo,
            env=os.environ | {"CALLS": str(self.calls), "FORMAT": ""} | env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done.returncode, self.calls.read_text().splitlines()

    def test_lints_the_repo_then_tests_every_repo(self) -> None:
        self.assertEqual(
            self.push(), (0, [f"lint {self.repo} --fix", "test all"])
        )

    def test_a_formatting_change_stops_it_before_the_suites(self) -> None:
        self.assertEqual(
            self.push(FORMAT="1"), (1, [f"lint {self.repo} --fix"])
        )


if __name__ == "__main__":
    unittest.main()
