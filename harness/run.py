"""Run test modules in parallel, each test in a process of its own.

    python3 -m harness.run [-j JOBS] [-k PATTERN ...] MODULE.py ...

A test that starts Quickshell, a helper or a server spends its time waiting
on it, so the tests run side by side, as many at once as there are CPUs,
the slowest first: how long each took is kept in the user's cache for the
next run. A process per test keeps them apart as running them one module
at a time did: a singleton, a loaded helper or an environment change never
reaches another test, and coverage measures each process by itself.

Prints a line per module, in the order given, under a heading for each
repo's (the folder they are in: dotfiles, installer, testing), with the
output of every test that failed and why tests were skipped, as a skip
in CI is a check that did not run; exits 1 if any failed. `-k` selects tests as
unittest's does, and `--heading` adds to each heading.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import unittest
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from . import TESTING

CACHE = (
    Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    / "jupiter-testing/durations.json"
)


def module_name(path: Path) -> str:
    """dotfiles/test_shelf.py as unittest names it, dotfiles.test_shelf."""
    relative = path.resolve().relative_to(TESTING).with_suffix("")
    return ".".join(relative.parts)


def tests(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from tests(test)
        else:
            yield test


def collect(name: str, patterns: list[str]) -> list[str]:
    """The ids of a module's tests that match the patterns, as -k matches."""
    loader = unittest.TestLoader()
    if patterns:
        loader.testNamePatterns = [
            pattern if "*" in pattern else f"*{pattern}*"
            for pattern in patterns
        ]
    suite = loader.loadTestsFromName(name)
    if loader.errors:
        raise SystemExit("\n".join(map(str, loader.errors)))
    return [test.id() for test in tests(suite)]


def run(test: str) -> tuple[str, int, str, float]:
    """One test in a process of its own: its id, exit code, output, time;
    verbose, as only then does unittest say why a test was skipped."""
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", test],
        cwd=TESTING,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    return test, result.returncode, output, time.monotonic() - start


def skips(output: str) -> list[str]:
    """Why unittest's verbose output says tests were skipped, one reason
    per test (or subtest)."""
    return [
        match.group(2)
        for match in re.finditer(
            r"\.\.\. skipped (['\"])(.*)\1$", output, re.MULTILINE
        )
    ]


def durations() -> dict[str, float]:
    try:
        loaded = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def remember(times: dict[str, float]) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(durations() | times, indent=0))
    except OSError:
        pass  # only the order of the next run suffers


def indented(text: str, lines: int = 40) -> str:
    return "\n".join(f"        {line}" for line in text.splitlines()[-lines:])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m harness.run")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count())
    parser.add_argument(
        "-k", dest="patterns", action="append", default=[], metavar="PATTERN"
    )
    parser.add_argument("--heading", default="", metavar="TEXT")
    parser.add_argument("modules", nargs="+", type=Path, metavar="MODULE.py")
    arguments = parser.parse_args(argv)

    modules = {path: module_name(path) for path in arguments.modules}
    ids = {
        path: collect(name, arguments.patterns)
        for path, name in modules.items()
    }
    known = durations()
    # The slowest first, so none is left to run alone at the end.
    queue = sorted(
        (test for found in ids.values() for test in found),
        key=lambda test: known.get(test, 1.0),
        reverse=True,
    )
    results: dict[str, tuple[int, str]] = {}
    times: dict[str, float] = {}
    failed = 0
    group = ""
    with concurrent.futures.ThreadPoolExecutor(arguments.jobs) as pool:
        futures = {test: pool.submit(run, test) for test in queue}
        for path, found in ids.items():
            for test in found:
                _, code, output, took = futures[test].result()
                results[test] = (code, output)
                times[test] = took
            if not found:
                continue
            if group != (group := modules[path].partition(".")[0]):
                print(f"\n== tests: {group}{arguments.heading}")
            bad = [test for test in found if results[test][0] != 0]
            skipped = sum(
                int(match.group(1))
                for test in found
                if (match := re.search(r"skipped=(\d+)", results[test][1]))
            )
            if bad:
                failed += 1
                print(f"  FAIL  {path}: {len(bad)} of {len(found)} tests")
                for test in bad:
                    print(f"      {test.removeprefix(modules[path] + '.')}")
                    print(indented(results[test][1]))
            elif skipped:
                print(f"  skip  {path}: skipped={skipped} of {len(found)}")
                reasons = Counter(
                    reason
                    for test in found
                    for reason in skips(results[test][1])
                )
                for reason, count in sorted(reasons.items()):
                    print(f"        {reason} ({count})")
            else:
                print(f"  ok    {path}: {len(found)} tests")
            sys.stdout.flush()
    remember(times)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
