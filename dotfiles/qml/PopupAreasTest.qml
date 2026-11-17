import QtQuick
import "../shell/services"

// What the open popups cover, so the toasts move below one in their column
// (the dotfiles' AGENTS.md, "Where things go": a top-right surface).
TestCase {
    readonly property QtObject calendar: QtObject {}
    readonly property QtObject power: QtObject {}

    function test_theLowestEdgeOverTheSpan() {
        PopupAreas.set(calendar, {
            screen: "DP-2",
            x: 100,
            y: 0,
            width: 400,
            height: 300
        });
        PopupAreas.set(power, {
            screen: "DP-2",
            x: 450,
            y: 0,
            width: 200,
            height: 500
        });
        compare(PopupAreas.bottomOver("DP-2", 0, 200), 300);
        compare(PopupAreas.bottomOver("DP-2", 400, 1000), 500, "both overlap it");
        compare(PopupAreas.bottomOver("DP-2", 700, 900), 0, "neither overlaps it");
        compare(PopupAreas.bottomOver("DP-2", 0, 100), 0, "edges that touch do not overlap");
        compare(PopupAreas.bottomOver("eDP-1", 0, 1000), 0, "another screen");
    }

    function test_anOwnerHasOneArea() {
        PopupAreas.set(power, {
            screen: "DP-2",
            x: 450,
            y: 0,
            width: 200,
            height: 100
        });
        compare(PopupAreas.bottomOver("DP-2", 600, 700), 100, "the new area replaced the old");
        PopupAreas.set(power, null);
        PopupAreas.set(calendar, null);
        compare(PopupAreas.areas.length, 0, "closing takes it out");
    }
}
