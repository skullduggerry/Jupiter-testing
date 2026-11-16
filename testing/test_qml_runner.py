"""harness/qml.py, against QML test files written for the purpose: a file
passes only when every test_ function does, and fails on a FAIL, on a
warning nothing expected, on the password in its log, when it does not
load, and when it never finishes. Fixtures reach it filled in.
"""

from __future__ import annotations

import unittest
from unittest import mock

from harness import SECRET, qml, temporary

HEADER = "import QtQuick\nimport Quickshell\nimport Quickshell.Io\n\n"


class Runner(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)

    def run_qml(self, body: str, name: str = "SampleTest") -> list[str]:
        """The failures of a TestCase file with this body."""
        test = self.tmp / f"{name}.qml"
        test.write_text(f"{HEADER}TestCase {{\n{body}\n}}\n")
        return qml.run(test)

    def test_passing(self) -> None:
        failures = self.run_qml("""
    function test_sums() { compare(1 + 1, 2); }
    function test_later() { return wait(10).then(() => verify(true)); }
    function test_eventually() {
        let ready = false;
        wait(20).then(() => ready = true);
        return tryVerify(() => ready, 500);
    }""")
        self.assertEqual(failures, [])

    def test_what_must_happen_is_waited_for_on_a_slow_machine(self) -> None:
        # Later than the test's own 50 ms, well within the floor.
        failures = self.run_qml("""
    function test_slow() {
        let ready = false;
        wait(400).then(() => ready = true);
        return tryVerify(() => ready, 50, "never ready");
    }""")
        self.assertEqual(failures, [])

    def test_what_never_happens_fails_with_its_message(self) -> None:
        [failure] = self.run_qml("""
    function test_never() { return tryVerify(() => false, 50, "never ready"); }""")
        self.assertIn("test_never: never ready", failure)

    def test_a_failure_names_its_test_and_line(self) -> None:
        [failure] = self.run_qml("""
    function test_fine() {}
    function test_wrong() { compare(1 + 1, 3, "arithmetic"); }""")
        self.assertIn("test_wrong: arithmetic: got 2, expected 3", failure)
        self.assertIn("SampleTest.qml:", failure)

    def test_an_unexpected_warning(self) -> None:
        failures = self.run_qml("""
    function test_warns() { console.warn("something is off"); }""")
        self.assertTrue(
            [line for line in failures if "something is off" in line],
            failures,
        )
        expected = self.run_qml("""
    function test_warns() {
        ignoreWarning("something is off");
        console.warn("something is off");
    }""")
        self.assertEqual(expected, [], "let through by ignoreWarning()")

    def test_the_password_in_the_log(self) -> None:
        failures = self.run_qml("""
    function test_leaks() { console.info(Quickshell.env("QML_SECRET")); }""")
        self.assertIn("the password is in the log: ", failures[0])
        self.assertIn(SECRET, failures[0])

    def test_a_file_that_does_not_load(self) -> None:
        failures = self.run_qml("    property int broken: ")
        self.assertTrue(failures)
        self.assertNotIn("never finished", "\n".join(failures))

    def test_no_test_functions(self) -> None:
        [failure] = self.run_qml("    property int nothing: 0")
        self.assertIn("no test_ functions", failure)

    def test_one_that_never_finishes(self) -> None:
        self.enterContext(mock.patch.object(qml, "TIMEOUT", 2))
        failures = self.run_qml("""
    function test_hangs() { return new Promise(() => {}); }""")
        self.assertEqual(failures[0], "never finished; its log:")

    def test_fixtures_are_filled_in_and_on_path(self) -> None:
        fixtures = self.tmp / "fixtures/FixtureTest"
        (fixtures / "bin").mkdir(parents=True)
        (fixtures / "note.txt").write_text("@FIXTURES@|@SECRET@")
        failures = self.run_qml(
            """
    readonly property FileView note: FileView {
        path: Quickshell.shellDir + "/note.txt"
        blockLoading: true
    }
    function test_filled() {
        const parts = note.text().split("|");
        verify(parts[0].endsWith("/fixtures"), parts[0]);
        verify(Quickshell.env("PATH").endsWith("/fixtures/bin"));
        verify(parts[1] === Quickshell.env("QML_SECRET"), "@SECRET@ filled in");
    }""",
            name="FixtureTest",
        )
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
