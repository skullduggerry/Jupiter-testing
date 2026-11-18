"""The Settings app's monitor helper, and monitors.lua picking up what it kept.

`apply` has to hand hyprctl Lua that hl.monitor takes, `save` has to leave a
file that .config/hypr/modules/monitors.lua applies after its own rules (the
newest matching rule is the one Hyprland uses), and bad input must never reach
either. monitors.lua runs under plain lua with a stand-in `hl` that records
its calls; hyprctl is a stand-in on PATH that records what it was asked.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from typing import Any

from harness import DOTFILES, QUICKSHELL, executable, temporary

HELPER = QUICKSHELL / "settings/displays.py"
MONITORS = DOTFILES / ".config/hypr/modules/monitors.lua"
RECORD = r"""
local calls = {}
hl = { monitor = function(rule) table.insert(calls, rule) end }
dofile(arg[1])
for _, rule in ipairs(calls) do
  local keys = {}
  for key in pairs(rule) do table.insert(keys, key) end
  table.sort(keys)
  local parts = {}
  for _, key in ipairs(keys) do table.insert(parts, key .. "=" .. tostring(rule[key])) end
  print(table.concat(parts, " "))
end
"""
LG = {
    "output": 'desc:LG "27GL650F" 0x1',
    "mode": "1920x1080@143.98",
    "position": "0x0",
    "scale": 1.25,
    "transform": 0,
    "vrr": 1,
}
HDMI = {
    "output": "HDMI-A-1",
    "mode": "1920x1080@60",
    "position": "1920x0",
    "scale": 1,
    "transform": 1,
    "disabled": False,
}


class Displays(unittest.TestCase):
    def setUp(self) -> None:
        self.root = temporary(self)
        self.asked = self.root / "asked"
        executable(
            self.root / "bin/hyprctl",
            f"#!/bin/sh\nprintf '%s' \"$2\" > '{self.asked}'\necho ok\n",
        )
        self.record = self.root / "record.lua"
        self.record.write_text(RECORD)
        self.env = dict(
            os.environ,
            XDG_STATE_HOME=str(self.root / "state"),
            HOME=str(self.root),
            PATH=f"{self.root / 'bin'}:{os.environ.get('PATH', '')}",
        )

    def run_helper(self, *args: str, ok: bool = True) -> None:
        result = subprocess.run(
            [sys.executable, str(HELPER), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode == 0, ok, f"{args[0]}: {result.stderr}"
        )

    def kept(self) -> list[dict[str, Any]]:
        path = self.root / "state/quickshell/monitors.json"
        kept: list[dict[str, Any]] = json.loads(path.read_text())
        return kept

    def applied(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["lua", str(self.record), str(MONITORS)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_apply_hands_hyprctl_lua(self) -> None:
        self.run_helper("apply", json.dumps([LG]))
        self.assertEqual(
            self.asked.read_text(),
            'hl.monitor({ output = "desc:LG \\"27GL650F\\" 0x1", mode = "1920x1080@143.98", '
            'position = "0x0", scale = 1.25, transform = 0, vrr = 1 })',
        )

    def test_bad_rules_never_reach_hyprctl(self) -> None:
        for bad in (
            '[{"mode": "1920x1080"}]',
            '[{"output": "DP-2", "nonsense": 1}]',
            '[{"output": "DP-2", "scale": "big"}]',
            '[{"output": "DP-2", "vrr": true}]',
            '[{"output": "DP-2", "scale": NaN}]',
            '[{"output": "DP-2", "scale": Infinity}]',
            "not json",
        ):
            with self.subTest(rules=bad):
                self.asked.unlink(missing_ok=True)
                self.run_helper("apply", bad, ok=False)
                self.assertFalse(self.asked.exists())

    @unittest.skipUnless(shutil.which("lua"), "needs lua")
    def test_saved_rules_come_last(self) -> None:
        self.run_helper("save", json.dumps([LG]))
        self.run_helper("save", json.dumps([HDMI]))
        self.run_helper("save", json.dumps([dict(LG, scale=1)]))
        kept = self.kept()
        self.assertEqual(
            [rule["output"] for rule in kept], [LG["output"], "HDMI-A-1"]
        )
        self.assertEqual(kept[0]["scale"], 1, "a second save replaces")

        result = self.applied(self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = result.stdout.splitlines()
        base = sum(
            1
            for line in calls
            if 'desc:LG "27GL650F"' not in line and "transform=1" not in line
        )
        self.assertEqual(len(calls), base + 2)
        self.assertEqual(
            calls[-2:],
            [
                'mode=1920x1080@143.98 output=desc:LG "27GL650F" 0x1 position=0x0 scale=1 transform=0 vrr=1',
                "disabled=false mode=1920x1080@60 output=HDMI-A-1 position=1920x0 scale=1 transform=1",
            ],
        )

        self.run_helper("forget", "HDMI-A-1")
        self.assertEqual(
            [rule["output"] for rule in self.kept()], [LG["output"]]
        )

        # Nothing kept, or no HOME at all (the login screen's user): the
        # config's own rules and nothing else, and no error.
        for scene in (
            dict(self.env, XDG_STATE_HOME=str(self.root / "empty")),
            {
                key: value
                for key, value in self.env.items()
                if key not in ("HOME", "XDG_STATE_HOME")
            },
        ):
            result = self.applied(scene)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(result.stdout.splitlines()), base)

    @unittest.skipUnless(shutil.which("lua"), "needs lua")
    def test_a_line_break_in_a_name_stays_in_its_string(self) -> None:
        # Any control character: a raw one ends a Lua string, and the file.
        odd = dict(HDMI, output='desc:Odd\r\n\x00Name \\ "q"\x7f')
        self.run_helper("save", json.dumps([odd]))
        lua = self.root / "state/quickshell/monitors.lua"
        loaded = subprocess.run(
            ["lua", "-e", f"io.write(dofile('{lua}')[1].output)"],
            capture_output=True,
            check=False,
        )
        self.assertEqual(loaded.returncode, 0, loaded.stderr)
        self.assertEqual(loaded.stdout.decode(), odd["output"])

    def test_an_unreadable_record_is_kept_aside(self) -> None:
        state = self.root / "state/quickshell"
        state.mkdir(parents=True)
        (state / "monitors.json").write_text('[{"output": "DP-1", "sca')
        result = subprocess.run(
            [sys.executable, str(HELPER), "save", json.dumps([HDMI])],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "monitors.json.broken", result.stderr, "said, for the page"
        )
        self.assertEqual(
            (state / "monitors.json.broken").read_text(),
            '[{"output": "DP-1", "sca',
        )
        self.assertEqual(self.kept(), [HDMI])


if __name__ == "__main__":
    unittest.main()
