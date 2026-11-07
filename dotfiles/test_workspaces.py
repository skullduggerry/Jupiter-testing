"""Each monitor's own workspaces: .config/hypr/modules/workspaces.lua.

The module runs under plain Lua against a stand-in `hl`, two monitors with
their blocks already in workspace-blocks.json (HDMI-A-1 0, DP-2 1). A reload
leaves a monitor on its own workspace, even an empty one it has company for,
where it was put. A monitor plugged back in shows the first of its own
workspaces, handed to set_workspace as Hyprland takes it (a selector, never a
table of options, which Hyprland 0.57 refuses); one with none of its own
opens its workspace 1 and gives focus and the pointer back, and with no
monitor focused before, there is none to give back. The keys' workspace 1
to 9 are the focused monitor's, and the arrows step through its workspaces,
past the last one to a new one; the scratchpad, on DP-2 in every world, is
none of them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest

from harness import DOTFILES, temporary

MODULE = DOTFILES / ".config/hypr/modules/workspaces.lua"
LUA_BINARY = shutil.which("lua5.4") or shutil.which("lua")

# A stand-in for Hyprland's `hl`. arg[2] names the world to build and the
# event to fire; what the module does is printed a line each.
LUA = r"""
local function json(value)
	if type(value) == "table" then
		if value.name ~= nil and value.active_workspace ~= nil then
			return string.format("%q", value.name)
		end
		local keys, parts = {}, {}
		for key in pairs(value) do keys[#keys + 1] = key end
		table.sort(keys)
		for _, key in ipairs(keys) do parts[#parts + 1] = string.format("%q:%s", key, json(value[key])) end
		return "{" .. table.concat(parts, ",") .. "}"
	elseif type(value) == "string" then
		return string.format("%q", value)
	end
	return tostring(value)
end

local workspaces = {}
local function workspace(id, monitor, windows)
	local made = { id = id, monitor = monitor, windows = windows, special = false }
	table.insert(workspaces, made)
	return made
end
-- Hyprland 0.57.0 hands Lua a special workspace without an id.
local function scratchpad(monitor)
	table.insert(workspaces, { name = "special:magic", monitor = monitor, windows = 1, special = true })
end

-- Hyprland 0.57 takes a workspace or a selector here, and nothing else.
local function set_workspace(self, selector)
	local kind = type(selector)
	if not (kind == "number" or kind == "string" or (kind == "table" and selector.id ~= nil)) then
		error("HLMonitor.set_workspace: expected a workspace object or selector", 2)
	end
	print("set_workspace " .. self.name .. " " .. tostring(kind == "table" and selector.id or selector))
end

local hdmi = { name = "HDMI-A-1", set_workspace = set_workspace }
local dp = { name = "DP-2", set_workspace = set_workspace }
local monitors = { hdmi, dp }
local active = hdmi
local handlers = {}

hl = {
	on = function(event, callback) handlers[event] = callback end,
	get_monitors = function() return monitors end,
	get_active_monitor = function() return active end,
	get_workspaces = function() return workspaces end,
	get_workspace = function(id)
		for _, known in ipairs(workspaces) do
			if known.id == id then return known end
		end
	end,
	get_cursor_pos = function() return { x = 10, y = 20 } end,
	dispatch = function(dispatcher) print("dispatch " .. json(dispatcher)) end,
	dsp = {
		focus = function(target) return { focus = target } end,
		window = { move = function(target) return { move = target } end },
		cursor = { move = function(to) return { cursor = to } end },
	},
}

local module = dofile(arg[1])
local world = arg[2]
hdmi.active_workspace = workspace(1, hdmi, 2)
scratchpad(dp)
if world == "reload on an empty workspace" then
	workspace(101, dp, 1)
	dp.active_workspace = workspace(103, dp, 0)
	handlers["config.reloaded"]()
elseif world == "plugged back in" then
	-- Its 102 came back with it, and Hyprland put it up on a new workspace.
	workspace(102, dp, 1)
	dp.active_workspace = workspace(3, dp, 0)
	handlers["monitor.added"](dp)
elseif world == "plugged in with nothing of its own" then
	dp.active_workspace = workspace(2, dp, 0)
	handlers["monitor.added"](dp)
elseif world == "plugged in with no monitor focused" then
	active = nil
	dp.active_workspace = workspace(2, dp, 0)
	handlers["monitor.added"](dp)
elseif world == "keys" then
	active = dp
	dp.active_workspace = workspace(101, dp, 1)
	module.focus(3)
	module.moveWindow(4)
elseif world == "stepping" then
	active = dp
	workspace(101, dp, 1)
	dp.active_workspace = workspace(102, dp, 1)
	workspace(104, dp, 1)
	module.step(1)
	module.step(-1)
	dp.active_workspace = workspaces[#workspaces]
	module.step(1)
end
"""


@unittest.skipUnless(LUA_BINARY, "needs lua")
class Settling(unittest.TestCase):
    def run_world(self, world: str) -> list[str]:
        root = temporary(self)
        hypr = root / "hypr/instance"
        hypr.mkdir(parents=True)
        (hypr / "workspace-blocks.json").write_text(
            json.dumps({"blocks": {"HDMI-A-1": 0, "DP-2": 1}}) + "\n"
        )
        script = root / "hl.lua"
        script.write_text(LUA)
        assert LUA_BINARY is not None
        result = subprocess.run(
            [LUA_BINARY, str(script), str(MODULE), world],
            env=dict(
                os.environ,
                XDG_RUNTIME_DIR=str(root),
                HYPRLAND_INSTANCE_SIGNATURE="instance",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            (result.returncode, result.stderr), (0, ""), f"{world}: Lua ran"
        )
        return result.stdout.splitlines()

    def test_a_reload_leaves_a_monitor_where_it_was_put(self) -> None:
        self.assertEqual(
            self.run_world("reload on an empty workspace"),
            [],
            "DP-2 stays on its empty 103, though 101 is its own too",
        )

    def test_a_monitor_plugged_back_in_shows_its_own_workspace(self) -> None:
        self.assertEqual(
            self.run_world("plugged back in"), ["set_workspace DP-2 102"]
        )

    def test_a_new_monitor_opens_its_workspace_1(self) -> None:
        self.assertEqual(
            self.run_world("plugged in with nothing of its own"),
            [
                'dispatch {"focus":{"monitor":"DP-2"}}',
                'dispatch {"focus":{"workspace":101}}',
                'dispatch {"focus":{"monitor":"HDMI-A-1"}}',
                'dispatch {"cursor":{"x":10,"y":20}}',
            ],
            "focus and pointer go back to HDMI-A-1",
        )

    def test_with_no_monitor_focused_there_is_none_to_go_back_to(self) -> None:
        self.assertEqual(
            self.run_world("plugged in with no monitor focused"),
            [
                'dispatch {"focus":{"monitor":"DP-2"}}',
                'dispatch {"focus":{"workspace":101}}',
            ],
        )

    def test_the_keys_reach_the_focused_monitors_workspaces(self) -> None:
        self.assertEqual(
            self.run_world("keys"),
            [
                'dispatch {"focus":{"workspace":103}}',
                'dispatch {"move":{"workspace":104}}',
            ],
        )

    def test_the_arrows_step_through_the_monitors_workspaces(self) -> None:
        self.assertEqual(
            self.run_world("stepping"),
            [
                'dispatch {"focus":{"workspace":104}}',
                'dispatch {"focus":{"workspace":101}}',
                'dispatch {"focus":{"workspace":105}}',
            ],
            "from 102 right and left, then right past the last one, 104",
        )


if __name__ == "__main__":
    unittest.main()
