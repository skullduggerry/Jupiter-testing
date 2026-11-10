import QtQuick
import "../shell/services"

// The binds as the Keybinds tab and the shortcuts overlay list them, from
// what `hyprctl binds -j` reports.
TestCase {
    function bind(key: string, modmask: int, description: string): var {
        return {
            key: key,
            keycode: 0,
            modmask: modmask,
            submap: "",
            has_description: description !== "",
            description: description
        };
    }

    function test_rowsByDescriptionAndModifiers() {
        // No compositor here, so no binds of its own to read, and Keymap's
        // shortcut has nowhere to register.
        ignoreWarning("HYPRLAND_INSTANCE_SIGNATURE is unset");
        ignoreWarning("Process failed to start");
        ignoreWarning("wl_display|hyprland_global_shortcuts_v1|GlobalShortcut will not work");
        const keycode = bind("", 0, "Quick menu");
        keycode.keycode = 66;
        Keybinds.load([bind("1", 64, "Go to that workspace"), bind("2", 64, "Go to that workspace"), bind("Q", 65, "Close"), bind("Q", 65, "Close"), bind("3", 64, "Go to that workspace"), keycode, bind("X", 64, ""), bind("Y", 64, "")]);
        compare(Keybinds.rows.length, 5);
        compare(Keybinds.rows[0].keys, ["1", "2", "3"]);
        compare(Keybinds.rows[0].modifiers, ["SUPER"]);
        compare(Keybinds.rows[1].keys, ["Q"], "a press and a release bind are one key");
        compare(Keybinds.rows[1].modifiers, ["SUPER", "SHIFT"]);
        compare(Keybinds.rows[2].keys, ["code:66"], "a bind on a keycode, as Hyprland 0.57.1's JSON has it: no key, keycode 66");
        compare(Keybinds.rows[3].keys, ["X"], "binds without a description stay apart");
    }

    function test_digitRunsAreRanges() {
        compare(Keybinds.keysLabel(["1", "2", "3", "4"]), "1–4");
        verify(Keybinds.keysLabel(["1", "3"]) !== "1–3");
    }

    // A pad key's shortcut names the bind it runs.
    function test_describeAShortcut() {
        Keybinds.load([bind("R", 64, "Open the launcher"), bind("1", 64, "Go to that workspace"), bind("2", 64, "Go to that workspace"), bind("M", 65, "Log out")]);
        compare(Keybinds.describe("SUPER + r"), "Open the launcher");
        compare(Keybinds.describe("SUPER + 2"), "Go to that workspace");
        compare(Keybinds.describe("SHIFT + SUPER + m"), "Log out", "modifiers in any order");
        compare(Keybinds.describe("SUPER + SHIFT + r"), "", "more modifiers are another shortcut");
        compare(Keybinds.describe("CTRL + z"), "");
    }

    // The tablet's recording submap binds Escape, which is no bind of the desktop's.
    function test_otherSubmapsLeftOut() {
        const recording = bind("Escape", 0, "Stop recording a pad key's shortcut");
        recording.submap = "tablet-record";
        Keybinds.load([bind("A", 64, "First"), recording]);
        compare(Keybinds.rows.length, 1);
    }
}
