import QtQuick
import Quickshell
import "../shell/services"

// The three-finger-swipe overlay's zones (PROJECT_STRUCTURE.md, "Arrow
// keys"): a swipe over a third of the screen opens that zone, the same one
// again closes it, and the arrow keys stop at the screen's edges.
TestCase {
    function test_aSwipeTogglesItsZone() {
        DropdownState.close();
        DropdownState.toggle(DropdownState.zoneCalendar, null);
        verify(DropdownState.visible);
        compare(DropdownState.zone, "calendar");
        DropdownState.toggle(DropdownState.zoneWorkspaces, null);
        verify(DropdownState.visible, "another zone takes over");
        compare(DropdownState.zone, "workspaces");
        DropdownState.toggle(DropdownState.zoneWorkspaces, null);
        verify(!DropdownState.visible, "the same zone again closes it");
    }

    function test_arrowKeysStopAtTheEdges() {
        DropdownState.zone = DropdownState.zoneWorkspaces;
        DropdownState.step(-1);
        compare(DropdownState.zone, "workspaces");
        DropdownState.step(1);
        compare(DropdownState.zone, "calendar");
        DropdownState.step(1);
        compare(DropdownState.zone, "quicksettings");
        DropdownState.step(1);
        compare(DropdownState.zone, "quicksettings", "no wrapping");
    }

    function test_thirdsOfTheScreen() {
        const screen = Quickshell.screens[0];
        verify(screen, "the offscreen platform has a screen");
        compare(DropdownState.zoneAt(screen.x, screen), "workspaces");
        compare(DropdownState.zoneAt(screen.x + screen.width / 2, screen), "calendar");
        compare(DropdownState.zoneAt(screen.x + screen.width - 1, screen), "quicksettings");
    }

    function test_aSwipeOpensOnItsScreen() {
        // Screens reads the focused monitor from a Hyprland there is none of.
        ignoreWarning("HYPRLAND_INSTANCE_SIGNATURE is unset");
        const screen = Quickshell.screens[0];
        DropdownState.close();
        DropdownState.openAt(screen.x + screen.width - 1, screen.y + 1);
        verify(DropdownState.visible);
        compare(DropdownState.zone, "quicksettings");
        compare(DropdownState.screen, screen);
    }

    function test_aSwipeOffEveryScreen() {
        ignoreWarning("dropdown: no screen contains");
        DropdownState.close();
        DropdownState.openAt(-100000, -100000);
        verify(!DropdownState.visible);
    }
}
