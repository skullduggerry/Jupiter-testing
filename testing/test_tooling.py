"""scripts/lint.sh, check.sh and harness/run.py, made to fail.

lint.sh runs on throwaway clones: the installer's settings over a file of
each kind gone wrong, and a copy of the dotfiles with every rule of their
own broken once, which must each be named. check.sh runs over stand-in
lint.sh and test.sh that record how they were called, from inside clones of
each repo and outside them. The runner runs a
real module selected by -k, and the installer's tests against a broken copy
of the installer, which must fail with what went wrong.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from harness import DOTFILES, INSTALLER, TESTING, executable, temporary

LINT = TESTING / "scripts/lint.sh"
CHECK = TESTING / "check.sh"
LINT_TOOLS = ("ruff", "mypy", "shellcheck", "shfmt")
DOTFILES_TOOLS = (
    *LINT_TOOLS,
    "/usr/lib/qt6/bin/qmlformat",
    "Hyprland",
    "luac",
    "stylua",
    "lua-language-server",
    "zsh",
)
# Records how it was called, and answers $ANSWER.
RECORD = """#!/bin/sh
echo "${0##*/} $*" >>"$CALLS"
exit "${ANSWER:-0}"
"""


def needs(*tools: str) -> None:
    missing = [tool for tool in tools if not shutil.which(tool)]
    if missing:
        raise unittest.SkipTest(f"not installed: {' '.join(missing)}")


def clone(source: Path, target: Path) -> Path:
    """A git repo holding what source's git knows of, as it is on disk."""
    listed = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-co", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for name in listed:
        path = source / name
        if path.is_symlink() or path.is_file():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target / name, follow_symlinks=False)
    git(target, "init", "-q")
    git(target, "add", "-A")
    return target


def git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(repo), *arguments], check=True)


def lint(kind: str, repo: Path, *options: str) -> tuple[int, str]:
    result = subprocess.run(
        [str(LINT), kind, str(repo), *options],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


class Lint(unittest.TestCase):
    """The rules every repo has, on a repo with the installer's settings."""

    def setUp(self) -> None:
        needs(*LINT_TOOLS)
        self.repo = temporary(self)
        shutil.copy(INSTALLER / "pyproject.toml", self.repo)
        shutil.copy(INSTALLER / ".editorconfig", self.repo)
        (self.repo / "good.py").write_text('"""Fine."""\n\nVALUE = 1\n')
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")

    def test_a_clean_repo(self) -> None:
        code, output = lint("installer", self.repo)
        self.assertEqual(code, 0, output)

    def test_each_problem_is_named(self) -> None:
        (self.repo / "ugly.py").write_text("VALUE   =  1\n")
        (self.repo / "unused.py").write_text("import os\n")
        (self.repo / "typed.py").write_text('def f() -> int:\n    return ""\n')
        (self.repo / "run.sh").write_text("#!/bin/sh\necho $1\n")
        (self.repo / "notes.txt").write_text("trailing \nno newline")
        (self.repo / "data.json").write_text("{nope")
        code, output = lint("installer", self.repo)
        self.assertEqual(code, 1)
        for problem in (
            "ugly.py is not formatted",
            "unused.py:1:8: F401",
            "typed.py:2: error: Incompatible return value",
            "run.sh:2:6: note: Double quote to prevent globbing",
            "notes.txt has trailing whitespace",
            "notes.txt has no final newline",
            "data.json: Expecting property name",
        ):
            with self.subTest(problem=problem):
                self.assertIn(problem, output)

    def test_fix_formats_and_fixes(self) -> None:
        (self.repo / "ugly.py").write_text("import os\nVALUE   =  1\n")
        (self.repo / "notes.txt").write_text("trailing \nno newline")
        code, output = lint("installer", self.repo, "--fix")
        self.assertEqual(code, 0, output)
        self.assertEqual((self.repo / "ugly.py").read_text(), "VALUE = 1\n")
        self.assertEqual(
            (self.repo / "notes.txt").read_text(), "trailing\nno newline\n"
        )

    def test_staged_looks_at_the_staged_files_alone(self) -> None:
        (self.repo / "ugly.py").write_text("VALUE   =  1\n")
        (self.repo / "staged.py").write_text("VALUE   =  2\n")
        git(self.repo, "add", "staged.py")
        code, output = lint("installer", self.repo, "--staged")
        self.assertEqual(code, 1)
        self.assertIn("staged.py is not formatted", output)
        self.assertNotIn("ugly.py", output)
        code, output = lint("installer", self.repo, "--staged", "--fix")
        self.assertEqual(code, 0, output)
        self.assertIn("fixed staged.py", output)
        staged = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--cached", "staged.py"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("+VALUE = 2", staged, "the fix staged again")

    def test_staged_documents_alone_are_nothing_to_format(self) -> None:
        """A commit of documents alone was refused: no name to format was
        taken for one empty name, which does not parse."""
        (self.repo / "NOTES.md").write_text("# Notes\n")
        git(self.repo, "add", "NOTES.md")
        code, output = lint("installer", self.repo, "--staged")
        self.assertEqual(code, 0, output)
        self.assertNotIn("does not parse", output)

    def test_a_missing_tool_is_named_with_its_package(self) -> None:
        bin_dir = self.repo / "bin"
        # What runs before the check: xargs runs echo.
        for tool in ("bash", "realpath", "dirname", "sort", "xargs", "echo"):
            if found := shutil.which(tool):
                (bin_dir / tool).parent.mkdir(exist_ok=True)
                (bin_dir / tool).symlink_to(found)
        result = subprocess.run(
            [str(LINT), "installer", str(self.repo)],
            env=dict(os.environ, PATH=str(bin_dir)),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "sudo pacman -S --needed mypy ruff shellcheck shfmt", result.stderr
        )


class LintDotfiles(unittest.TestCase):
    """The dotfiles' own rules, each broken once in a copy of them."""

    def test_every_rule_is_enforced(self) -> None:
        needs(*DOTFILES_TOOLS)
        repo = clone(DOTFILES, temporary(self))
        shell = repo / ".config/quickshell"
        # A type its qmldir does not name.
        (shell / "osd/Unlisted.qml").write_text("import QtQuick\n\nItem {}\n")
        # A popup Hyprland's blur rule does not match, a pasted glyph and
        # a Nerd Font one, all in a file that is otherwise fine.
        clock = shell / "bar/widgets/ClockWidget.qml"
        text = clock.read_text()
        clock.write_text(
            text.rstrip()[:-1]
            + '    readonly property string pasted: "\uf101"\n'
            + '    readonly property string nerd: "\\u{F0141}"\n'
            + '    readonly property string namespaceSuffix: "clock"\n}\n'
        )
        # Lua that does not parse, and a Hyprland config that does not verify.
        (repo / ".config/hypr/modules/broken.lua").write_text("local = 1\n")
        layout = repo / ".config/hypr/styles/layout.lua"
        layout.write_text(layout.read_text() + "\nhl.no_such_thing()\n")
        git(repo, "add", "-A")
        code, output = lint("dotfiles", repo)
        self.assertEqual(code, 1)
        for problem in (
            "Unlisted.qml missing from .config/quickshell/osd/qmldir",
            "namespaceSuffix 'clock' will not match the blur rule",
            "pasted glyphs, write them as \\u{...}: "
            ".config/quickshell/bar/widgets/ClockWidget.qml",
            "Nerd Font glyphs, use icons/Icons.qml",
            ".config/hypr/modules/broken.lua does not parse",
            ".config/hypr/hyprland.lua does not verify",
        ):
            with self.subTest(problem=problem):
                self.assertIn(problem, output)


class Check(unittest.TestCase):
    """check.sh: which repos it lints and tests, and how it answers."""

    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.testing = self.tmp / "Jupiter-testing"
        shutil.copy2(CHECK, executable(self.testing / "check.sh", ""))
        executable(self.testing / "harness/qml.py", "")
        for name in ("lint.sh", "test.sh"):
            executable(self.testing / "scripts" / name, RECORD)
        self.dotfiles = self.tmp / "Jupiter-dotfiles"
        executable(self.dotfiles / ".config/quickshell/shell.qml", "")
        self.installer = self.tmp / "Jupiter-installer"
        executable(self.installer / "jupiter/__main__.py", "")
        for repo in (self.testing, self.dotfiles, self.installer):
            git(repo, "init", "-q")
        self.calls = self.tmp / "calls"

    def check(
        self, *arguments: str, cwd: Path | None = None, answer: int = 0
    ) -> tuple[int, list[str], str]:
        self.calls.write_text("")
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("JUPITER_")
        }
        result = subprocess.run(
            [str(self.testing / "check.sh"), *arguments],
            cwd=cwd or self.tmp,
            env=env | {"CALLS": str(self.calls), "ANSWER": str(answer)},
            capture_output=True,
            text=True,
            check=False,
        )
        calls = self.calls.read_text().splitlines()
        return result.returncode, calls, result.stdout + result.stderr

    def everything(self, *test: str) -> list[str]:
        return [
            f"lint.sh dotfiles {self.dotfiles}",
            f"lint.sh installer {self.installer}",
            f"lint.sh testing {self.testing}",
            " ".join(["test.sh dotfiles installer testing", *test]),
        ]

    def test_outside_the_repos_all_three(self) -> None:
        code, calls, output = self.check()
        self.assertEqual((code, calls), (0, self.everything()))
        self.assertIn("all checks passed: dotfiles installer testing", output)
        self.assertEqual(self.check("check", "all")[1], self.everything())

    def test_inside_one_that_one(self) -> None:
        elsewhere = self.tmp / "src/dots"
        executable(elsewhere / ".config/quickshell/shell.qml", "")
        git(elsewhere, "init", "-q")
        for cwd, expected in (
            (self.dotfiles / ".config", ["dotfiles", self.dotfiles]),
            (self.installer / "jupiter", ["installer", self.installer]),
            (self.testing / "scripts", ["testing", self.testing]),
            (elsewhere, ["dotfiles", elsewhere]),
        ):
            with self.subTest(cwd=cwd):
                kind, path = expected
                self.assertEqual(
                    self.check("lint", cwd=cwd)[1], [f"lint.sh {kind} {path}"]
                )

    def test_another_jupiter_testing_checks_itself(self) -> None:
        other = self.tmp / "other-testing"
        executable(other / "harness/qml.py", "")
        executable(
            other / "check.sh", '#!/bin/sh\necho "other $*" >"$CALLS"\n'
        )
        git(other, "init", "-q")
        self.assertEqual(
            self.check("lint", "--fix", cwd=other)[1], ["other lint --fix"]
        )

    def test_each_command_and_its_options(self) -> None:
        for arguments, expected in (
            (
                ("check", "installer", "--fix", "--staged"),
                [
                    f"lint.sh installer {self.installer} --fix --staged",
                    "test.sh installer",
                ],
            ),
            (("lint", "dotfiles"), [f"lint.sh dotfiles {self.dotfiles}"]),
            (
                ("test", "testing", "--security", "-k", "Lock"),
                ["test.sh testing --security -k Lock"],
            ),
            (
                ("test", "all", "dotfiles"),
                ["test.sh dotfiles installer testing"],
            ),
            (
                ("--fix", "installer"),
                [
                    f"lint.sh installer {self.installer} --fix",
                    "test.sh installer",
                ],
            ),
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.check(*arguments)[1], expected)

    def test_a_clone_by_its_path(self) -> None:
        elsewhere = self.tmp / "elsewhere"
        executable(elsewhere / "jupiter/__main__.py", "")
        _, calls, _ = self.check("lint", str(elsewhere / "."))
        self.assertEqual(calls, [f"lint.sh installer {elsewhere}"])

    def test_failures_are_summed_up(self) -> None:
        code, calls, output = self.check("installer", answer=1)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2, "the tests run after a failed lint")
        self.assertIn("FAILED: lint installer, tests", output)
        code, calls, _ = self.check("installer", answer=2)
        self.assertEqual((code, len(calls)), (2, 1), "a tool is missing")

    def test_what_it_refuses(self) -> None:
        for arguments, message in (
            (("check", "elsewhere"), "unknown repo: elsewhere"),
            ((str(self.tmp),), "unknown repo: "),
            (("--nope",), "unknown option: --nope"),
            (("test", "-k"), "-k needs a pattern"),
        ):
            with self.subTest(arguments=arguments):
                code, calls, output = self.check(*arguments)
                self.assertEqual((code, calls), (2, []))
                self.assertIn(message, output)

    def test_help(self) -> None:
        code, calls, output = self.check("--help")
        self.assertEqual((code, calls), (0, []))
        self.assertTrue(
            output.lstrip().startswith("./check.sh [check|lint|test]")
        )
        self.assertIn("--security, -k PATTERN", output)


class Runner(unittest.TestCase):
    """harness/run.py on real modules."""

    def runner(self, *arguments: str, **env: str) -> tuple[int, str]:
        # Unmeasured: what they run is measured where it runs for itself,
        # and a broken copy would be measured in a folder that is gone.
        unmeasured = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("COVERAGE_")
        }
        result = subprocess.run(
            [sys.executable, "-m", "harness.run", *arguments],
            cwd=TESTING,
            env=unmeasured | env,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout + result.stderr

    def test_selected_tests_and_their_times(self) -> None:
        cache = temporary(self)
        code, output = self.runner(
            "-k",
            "not_updated_first",
            "-k",
            "nothing_matches_this",
            "installer/test_check.py",
            "installer/test_fingerprint.py",
            XDG_CACHE_HOME=str(cache),
        )
        self.assertEqual(
            (code, output),
            (
                0,
                "\n== tests: installer\n  ok    installer/test_check.py: 1 tests\n",
            ),
        )
        times = (cache / "jupiter-testing/durations.json").read_text()
        self.assertIn(
            "installer.test_check.Bootstrap.test_the_installer_is_not_updated_first",
            times,
        )

    def test_a_failure_with_its_output(self) -> None:
        broken = temporary(self)
        for name in ("jupiter", "packages", "bootstrap.sh", "check.sh"):
            source = INSTALLER / name
            if source.is_dir():
                shutil.copytree(source, broken / name)
            else:
                shutil.copy2(source, broken / name)
        check = broken / "check.sh"
        check.write_text(
            check.read_text().replace('check.sh" "$@"', 'check.sh"')
        )
        code, output = self.runner(
            "-k",
            "Check.test_the_arguments",
            "installer/test_check.py",
            JUPITER_INSTALLER=str(broken),
            XDG_CACHE_HOME=str(broken / "cache"),
        )
        self.assertEqual(code, 1)
        self.assertIn("  FAIL  installer/test_check.py: 1 of 1 tests", output)
        self.assertIn("Check.test_the_arguments_as_they_are", output)
        self.assertIn("AssertionError", output)

    def test_a_module_that_does_not_load(self) -> None:
        code, output = self.runner("testing/no_such_module.py")
        self.assertNotEqual(code, 0)
        self.assertIn("no_such_module", output)


if __name__ == "__main__":
    unittest.main()
