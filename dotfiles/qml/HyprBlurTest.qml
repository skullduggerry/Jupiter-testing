import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// Hyprland's blur as the Settings app hands it in (PROJECT_STRUCTURE.md,
// "Wallpaper"): one Lua table, sent live with `hyprctl eval` (a stand-in in
// fixtures/HyprBlurTest/bin notes the call) and kept in blur.lua, which
// .config/hypr/styles/layout.lua applies at the next start.
TestCase {
    readonly property FileView kept: FileView {
        path: HyprBlur.config
        blockLoading: true
        printErrors: false
    }
    readonly property FileView calls: FileView {
        path: Quickshell.env("HOME") + "/hyprctl.log"
        blockLoading: true
        printErrors: false
    }

    function read(file: FileView): string {
        file.reload();
        return file.text();
    }

    // Sub-options grouped by variant, keys sorted, colours quoted.
    function test_oneTableGroupedByVariant() {
        HyprBlur.variant = 8;
        HyprBlur.size = 5;
        HyprBlur.options = {
            "glass.size": 40,
            "acrylic.clarity": 0.35
        };
        HyprBlur.colors = {
            "acrylic.tint": "rgba(16161659)"
        };
        compare(HyprBlur.table(), '{ variant = 8, size = 5, acrylic = { clarity = 0.35, tint = "rgba(16161659)" }, glass = { size = 40 } }');
    }

    // Nothing reaches Hyprland before the Settings app's bindings are in
    // place; then the table is sent and kept.
    function test_sentAndKeptOnceActive() {
        HyprBlur.active = false;
        HyprBlur.options = {};
        HyprBlur.colors = {};
        HyprBlur.size = 7;
        HyprBlur.variant = 6;
        return wait(400).then(() => {
            compare(read(calls), "", "sent while inactive");
            HyprBlur.active = true;
            return tryVerify(() => read(calls) !== "", 2000, "never sent");
        }).then(() => {
            compare(read(calls).trim(), "eval hl.config({ decoration = { blur = { variant = 6, size = 7 } } })");
            return tryVerify(() => read(kept) !== "", 2000, "never kept");
        }).then(() => {
            verify(read(kept).includes("\nreturn { variant = 6, size = 7 }\n"), read(kept));
        });
    }
}
