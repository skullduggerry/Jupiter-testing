import QtQuick
import "../shell/services"

// Hyprland's general:gaps_out as `hyprctl -j getoption` prints it, which the
// bar and what opens under it line up on: CSS's order, top, right, bottom,
// left, with the later sides left out where they repeat.
TestCase {
    function test_sidesAsCssHasThem() {
        // No compositor here to read the gaps from.
        ignoreWarning("HYPRLAND_INSTANCE_SIGNATURE is unset");
        ignoreWarning("Process failed to start");
        WindowGaps.load("8 8 8 8");
        compare([WindowGaps.top, WindowGaps.right, WindowGaps.bottom, WindowGaps.left], [8, 8, 8, 8]);
        WindowGaps.load("10 20 30 40");
        compare([WindowGaps.top, WindowGaps.right, WindowGaps.bottom, WindowGaps.left], [10, 20, 30, 40]);
        WindowGaps.load("5");
        compare([WindowGaps.top, WindowGaps.right, WindowGaps.bottom, WindowGaps.left], [5, 5, 5, 5]);
        WindowGaps.load("4 12");
        compare([WindowGaps.top, WindowGaps.right, WindowGaps.bottom, WindowGaps.left], [4, 12, 4, 12]);
        WindowGaps.load("1 2 3");
        compare([WindowGaps.top, WindowGaps.right, WindowGaps.bottom, WindowGaps.left], [1, 2, 3, 2]);
    }

    function test_somethingElseKeepsTheGaps() {
        ignoreWarning("window gaps: hyprctl printed");
        WindowGaps.load("6 6 6 6");
        WindowGaps.load("auto");
        WindowGaps.load("1 2 3 4 5");
        WindowGaps.load("");
        WindowGaps.load("  ");
        compare([WindowGaps.top, WindowGaps.right, WindowGaps.bottom, WindowGaps.left], [6, 6, 6, 6]);
    }
}
