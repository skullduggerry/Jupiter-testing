"""The drawing tablet: services/tablet.py and .config/hypr/modules/tablet.lua.

tablet.py has to find the tablet and its pad by udev's properties in a
stand-in /sys and udev database, with the tablet's size and the pad's
buttons (the digitizer's own codes left out), and read the pad's buttons as
press and release lines numbered in code order, ignoring everything else; a
FIFO cannot be grabbed, so it says "shared" first.

tablet.lua runs under plain Lua against a stand-in `hl`: from tablet.lua in
the state it maps every screen, the focused one or a named one, keeps the
tablet's used area to the shape of what it draws on (or the whole tablet
with keepRatio off), holds to a screen or a window and lets go on the second
press or when the window closes, and sends Hyprland nothing unchanged. A pad
key's shortcut runs the bind keybinds.lua made on those keys, whatever the
case or the order of the modifiers (a release bind is no press), and anything
else goes to the window down and up; the recording submap's Escape leaves it.
That a locked session takes no pad button is security/qml/TabletLockTest's.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, ClassVar

from harness import DOTFILES, QUICKSHELL, temporary

HELPER = QUICKSHELL / "services/tablet.py"
MODULE = DOTFILES / ".config/hypr/modules/tablet.lua"
EVENT = struct.Struct("llHHi")
LUA_BINARY = shutil.which("lua5.4") or shutil.which("lua")

# A stand-in for Hyprland's `hl`: two screens side by side, the left one
# focused, and a window on it. Every hl.config is printed as a line of JSON.
LUA = r"""
local function json(value)
	if type(value) == "table" then
		local parts = {}
		if #value > 0 then
			for _, item in ipairs(value) do parts[#parts + 1] = json(item) end
			return "[" .. table.concat(parts, ",") .. "]"
		end
		local keys = {}
		for key in pairs(value) do keys[#keys + 1] = key end
		table.sort(keys)
		for _, key in ipairs(keys) do parts[#parts + 1] = string.format("%q:%s", key, json(value[key])) end
		return "{" .. table.concat(parts, ",") .. "}"
	elseif type(value) == "string" then
		return string.format("%q", value)
	end
	return tostring(value)
end

local left = { name = "DP-2", x = 0, y = 0, width = 1920, height = 1080, scale = 1 }
local right = { name = "eDP-1", x = 1920, y = 0, width = 2880, height = 1920, scale = 1.5 }
local window = { address = "0xabc", at = { x = 100, y = 50 }, size = { x = 800, y = 800 }, monitor = left, workspace = { active = true } }
local windows = { ["address:0xabc"] = window }
local timer = { on = false }
function timer:set_enabled(on) self.on = on end

hl = {
	timer = function(callback) timer.callback = callback return timer end,
	on = function() end,
	exec_cmd = function(command) print("exec " .. command) end,
	get_monitors = function() return { left, right } end,
	get_monitor = function(name) return name == left.name and left or name == right.name and right or nil end,
	get_active_monitor = function() return left end,
	get_active_window = function() return window end,
	get_window = function(selector) return windows[selector] end,
	config = function(config) print("config " .. json(config.input)) end,
	bind = function(keys, dispatcher) print("bind " .. keys .. " " .. json(dispatcher)) end,
	define_submap = function(name, binds) print("submap " .. name) binds() end,
	dispatch = function(dispatcher) print("dispatch " .. json(dispatcher)) end,
	dsp = {
		submap = function(name) return { submap = name } end,
		send_key_state = function(key) return { send = key } end,
	},
}

local tablet = dofile(arg[1])
print("step use focused")
tablet.use({ area = "focused", keepRatio = true, width = 216, height = 135 })
print("step use focused again")
tablet.use({ area = "focused", keepRatio = true, width = 216, height = 135 })
print("step use eDP-1 stretched")
tablet.use({ area = "eDP-1", keepRatio = false, width = 216, height = 135, leftHanded = true, pressureMin = 0.1, pressureMax = 0.8 })
print("step use unplugged")
tablet.use({ area = "HDMI-A-1", width = 216, height = 135 })
print("step hold window")
tablet.holdWindow()
print("step timer " .. tostring(timer.on))
window.at = { x = 300, y = 50 }
timer.callback()
print("step hidden")
window.workspace = { active = false }
timer.callback()
print("step closed")
window.workspace = { active = true }
windows["address:0xabc"] = nil
timer.callback()
print("step timer " .. tostring(timer.on))
print("step hold screen")
tablet.holdScreen()
print("step release screen")
tablet.holdScreen()
print("step bind")
tablet.bind("SUPER + SHIFT + M", { logout = true }, { description = "Log out" })
tablet.bind("SUPER + A", { menu = "release" }, { release = true })
print("step press bound")
tablet.press("SHIFT SUPER", "m")
print("step press a release bind")
tablet.press("SUPER", "a")
print("step press unbound")
tablet.press("CTRL", "z")
print("step press bare")
tablet.press("", "Escape")
"""


def device(
    root: Path,
    event: str,
    number: str,
    name: str,
    props: dict[str, str],
    keys: str = "0",
) -> None:
    sysfs = root / "sys/class/input" / event
    (sysfs / "device/capabilities").mkdir(parents=True)
    (sysfs / "dev").write_text(f"13:{number}\n")
    (sysfs / "device/name").write_text(name + "\n")
    (sysfs / "device/capabilities/key").write_text(keys + "\n")
    udev = root / "run/udev/data"
    udev.mkdir(parents=True, exist_ok=True)
    lines = (
        ["I:123"]
        + [f"E:{key}={value}" for key, value in props.items()]
        + ["G:seat"]
    )
    (udev / f"c13:{number}").write_text("\n".join(lines) + "\n")


class Helper(unittest.TestCase):
    def setUp(self) -> None:
        self.root = temporary(self)

    def describe(self) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, str(HELPER)],
            env=dict(os.environ, TABLET_ROOT=str(self.root)),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        found: dict[str, Any] = json.loads(result.stdout)
        return found

    def test_finding_the_tablet_and_reading_its_pad(self) -> None:
        self.assertEqual(self.describe(), {"tablet": None, "pad": None})
        (self.root / "dev/input").mkdir(parents=True)
        # A keyboard first, which is neither.
        device(
            self.root,
            "event2",
            "66",
            "AT Keyboard",
            {"ID_INPUT": "1", "ID_INPUT_KEYBOARD": "1"},
        )
        device(
            self.root,
            "event21",
            "85",
            "Wacom Intuos BT M Pen",
            {
                "ID_INPUT": "1",
                "ID_INPUT_TABLET": "1",
                "ID_INPUT_WIDTH_MM": "216",
                "ID_INPUT_HEIGHT_MM": "135",
            },
            "1c01 0 0 0 0 0",
        )
        # BTN_0 to BTN_3, and BTN_STYLUS, which marks a pad as a tablet's.
        device(
            self.root,
            "event22",
            "86",
            "Wacom Intuos BT M Pad",
            {
                "ID_INPUT": "1",
                "ID_INPUT_TABLET": "1",
                "ID_INPUT_TABLET_PAD": "1",
            },
            "800 f 0 0 0 0",
        )
        node = self.root / "dev/input/event22"
        node.write_bytes(b"")
        node.chmod(0)
        self.assertEqual(
            self.describe(),
            {
                "tablet": {
                    "name": "Wacom Intuos BT M",
                    "width": 216,
                    "height": 135,
                },
                "pad": {"buttons": 4, "readable": os.geteuid() == 0},
            },
            "a tablet and an unreadable pad",
        )
        node.unlink()
        os.mkfifo(node)
        self.assertEqual(
            self.describe()["pad"], {"buttons": 4, "readable": True}
        )

        reader = subprocess.Popen(
            [sys.executable, str(HELPER), "pad"],
            env=dict(os.environ, TABLET_ROOT=str(self.root)),
            stdout=subprocess.PIPE,
            bufsize=0,
        )
        self.addCleanup(reader.wait)
        # SIGTERM, which coverage saves its measurement on; SIGKILL loses it.
        self.addCleanup(reader.terminate)
        assert reader.stdout is not None
        with open(node, "wb") as pad:
            events = [
                (3, 0, 1200),  # EV_ABS: not a button
                (1, 258, 1),  # BTN_2 down
                (1, 258, 2),  # an auto-repeat, which pads never mean
                (1, 331, 1),  # BTN_STYLUS: the digitizer's
                (1, 258, 0),  # BTN_2 up
                (1, 256, 1),  # BTN_0 down
                (0, 0, 0),  # EV_SYN
            ]
            pad.write(
                b"".join(
                    EVENT.pack(0, 0, kind, code, value)
                    for kind, code, value in events
                )
            )
        # Unbuffered: select() cannot see lines a buffered reader holds.
        output = b""
        deadline = time.monotonic() + 10
        while output.count(b"\n") < 6 and time.monotonic() < deadline:
            if select.select([reader.stdout], [], [], 0.5)[0]:
                output += os.read(reader.stdout.fileno(), 4096)
        self.assertEqual(
            output.decode().splitlines(),
            [
                "shared",
                "connected 4",
                "press 2",
                "release 2",
                "press 0",
                "disconnected",
            ],
        )

    def test_usage(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HELPER), "what"],
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)


@unittest.skipUnless(LUA_BINARY, "needs lua")
class Module(unittest.TestCase):
    """modules/tablet.lua's run against the stand-in `hl`, once: each step's
    lines are in `steps`, by the name LUA prints before it."""

    result: ClassVar[subprocess.CompletedProcess[str]]
    steps: ClassVar[dict[str, list[str]]]

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            state = root / "state"
            (state / "quickshell").mkdir(parents=True)
            (state / "quickshell/tablet.lua").write_text(
                "return { area = 'all', width = 216, height = 135 }\n"
            )
            script = root / "hl.lua"
            script.write_text(LUA)
            assert LUA_BINARY is not None
            cls.result = subprocess.run(
                [LUA_BINARY, str(script), str(MODULE)],
                env=dict(os.environ, XDG_STATE_HOME=str(state)),
                capture_output=True,
                text=True,
                check=False,
            )
        cls.steps = {"load": []}
        current = "load"
        for line in cls.result.stdout.splitlines():
            if line.startswith("step "):
                current = line[5:]
                cls.steps[current] = []
            else:
                cls.steps[current].append(line)

    def config(self, step: str) -> Any:
        lines = [
            line for line in self.steps[step] if line.startswith("config ")
        ]
        self.assertEqual(len(lines), 1, f"{step}: one config")
        return json.loads(lines[0][7:])

    def test_lua_runs(self) -> None:
        self.assertEqual((self.result.returncode, self.result.stderr), (0, ""))

    def test_every_screen(self) -> None:
        # 3840 x 1280 (the right one is 1920 x 1280 at scale 1.5), so the
        # tablet's full width and the middle 72 mm of its height. Hyprland
        # takes no 0x0 region for all of it, so the layout's box is given.
        loaded = self.config("load")
        self.assertEqual(
            (
                loaded["tablet"]["output"],
                loaded["tablet"]["region_position"],
                loaded["tablet"]["region_size"],
                loaded["tablet"]["absolute_region_position"],
            ),
            ("", [0, 0], [3840, 1280], True),
        )
        self.assertEqual(loaded["tablet"]["active_area_size"], [216, 72])
        self.assertEqual(loaded["tablet"]["active_area_position"], [0, 31.5])
        self.assertEqual(
            loaded["tablettool"],
            {"pressure_range_max": 1, "pressure_range_min": 0},
            "libinput's pressure",
        )

    def test_a_screen(self) -> None:
        focused = self.config("use focused")
        self.assertEqual(focused["tablet"]["output"], "current")
        self.assertEqual(
            focused["tablet"]["active_area_size"], [216, 121.5], "16:9"
        )
        self.assertEqual(
            self.steps["use focused again"], [], "nothing unchanged sent"
        )
        stretched = self.config("use eDP-1 stretched")
        self.assertEqual(stretched["tablet"]["output"], "eDP-1")
        self.assertEqual(stretched["tablet"]["active_area_size"], [216, 135])
        self.assertIs(stretched["tablet"]["left_handed"], True)
        self.assertEqual(
            stretched["tablettool"],
            {"pressure_range_max": 0.8, "pressure_range_min": 0.1},
        )
        unplugged = self.config("use unplugged")
        self.assertEqual(
            (
                unplugged["tablet"]["output"],
                unplugged["tablet"]["active_area_size"],
            ),
            ("HDMI-A-1", [216, 72]),
            "kept, every screen's shape",
        )

    def test_holding(self) -> None:
        held = self.config("hold window")
        self.assertEqual(
            (
                held["tablet"]["output"],
                held["tablet"]["region_position"],
                held["tablet"]["region_size"],
            ),
            ("DP-2", [100, 50], [800, 800]),
        )
        self.assertEqual(
            (
                held["tablet"]["active_area_position"],
                held["tablet"]["active_area_size"],
            ),
            ([40.5, 0], [135, 135]),
            "square",
        )
        self.assertTrue(
            any(
                "Held to the window" in line
                for line in self.steps["hold window"]
            )
        )
        followed = self.steps["timer true"][0]
        self.assertTrue(followed.startswith("config "))
        self.assertEqual(
            json.loads(followed[7:])["tablet"]["region_position"], [300, 50]
        )
        self.assertEqual(self.config("hidden")["tablet"]["output"], "HDMI-A-1")
        self.assertTrue(
            any("Back on" in line for line in self.steps["closed"])
        )
        self.assertIn("timer false", self.steps, "the timer stops")
        self.assertEqual(
            self.config("hold screen")["tablet"]["output"], "DP-2"
        )
        self.assertEqual(
            self.config("release screen")["tablet"]["output"],
            "HDMI-A-1",
            "the second press lets go",
        )

    def test_pad_keys(self) -> None:
        self.assertEqual(
            [
                line
                for line in self.steps["load"]
                if not line.startswith("config ")
            ],
            ["submap tablet-record", 'bind Escape {"submap":"reset"}'],
            "the recording submap's Escape leaves it",
        )
        self.assertEqual(
            self.steps["bind"],
            [
                'bind SUPER + SHIFT + M {"logout":true}',
                'bind SUPER + A {"menu":"release"}',
            ],
        )
        self.assertEqual(
            self.steps["press bound"], ['dispatch {"logout":true}']
        )

        def sent(mods: str, key: str) -> list[str]:
            return [
                f'dispatch {{"send":{{"key":"{key}","mods":"{mods}","state":"{state}"}}}}'
                for state in ("down", "up")
            ]

        self.assertEqual(
            self.steps["press a release bind"], sent("SUPER", "a")
        )
        self.assertEqual(self.steps["press unbound"], sent("CTRL", "z"))
        self.assertEqual(self.steps["press bare"], sent("", "Escape"))


if __name__ == "__main__":
    unittest.main()
