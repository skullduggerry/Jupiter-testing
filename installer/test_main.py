"""The installer's entry point (jupiter/__main__.py): phases 3 and 4 stop
before anything when there is no network, saying how to connect, and the
closing words after phases 1 and 2 say the network is needed.

nm-online is a stand-in that exits $ONLINE; the phases themselves are
mocks, so nothing is installed.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupiter import __main__ as entry

NM_ONLINE = f"""#!{sys.executable}
import os, sys
with open(os.environ["CALLS"], "a") as calls:
    calls.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ["ONLINE"]))
"""


class Entry(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / "nm-online").write_text(NM_ONLINE)
        (tmp / "nm-online").chmod(0o755)
        self.calls = tmp / "calls"
        environment = {"PATH": str(tmp), "CALLS": str(self.calls)}
        self.enterContext(mock.patch.dict(os.environ, environment))
        self.ran: list[int] = []
        phases = {n: (lambda n=n: self.ran.append(n)) for n in entry.PHASES}
        self.enterContext(mock.patch.dict(entry.PHASES, phases))
        self.enterContext(mock.patch("os.geteuid", return_value=1000))
        self.printed = self.enterContext(mock.patch("builtins.print"))

    def start(self, *arguments: str, online: bool, live: bool = False) -> None:
        os.environ["ONLINE"] = "0" if online else "1"
        with (
            mock.patch.object(entry, "LIVE", live),
            mock.patch.object(sys, "argv", ["jupiter", *arguments]),
        ):
            entry.main()

    def said(self) -> str:
        return " ".join(
            str(a) for c in self.printed.call_args_list for a in c.args
        )


class Network(Entry):
    def test_offline_phases_3_and_4_stop_before_anything(self) -> None:
        with self.assertRaises(SystemExit) as stopped:
            self.start(online=False)
        self.assertEqual(self.ran, [])
        self.assertIn("nmtui", str(stopped.exception))
        self.assertIn("bootstrap.sh again", str(stopped.exception))
        # Waits a while for a connection coming up, then gives up.
        self.assertEqual(self.calls.read_text(), "--quiet --timeout=30\n")

    def test_online_they_run(self) -> None:
        self.start(online=True)
        self.assertEqual(self.ran, [3, 4])

    def test_the_live_iso_is_not_asked(self) -> None:
        self.start(online=False, live=True)
        self.assertEqual(self.ran, [1, 2])
        self.assertFalse(self.calls.exists())

    def test_without_networkmanager_they_run(self) -> None:
        os.environ["PATH"] = "/nonexistent"
        self.start(online=False)
        self.assertEqual(self.ran, [3, 4])

    def test_after_phases_1_and_2_it_says_the_network_is_needed(self) -> None:
        self.start(online=True, live=True)
        self.assertIn("connect with `nmtui` first", self.said())


if __name__ == "__main__":
    unittest.main()
