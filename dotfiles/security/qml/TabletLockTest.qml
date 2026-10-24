import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// The drawing tablet's pad buttons press their shortcut through Hyprland
// (modules/tablet.lua's press()), around the binds Hyprland itself keeps off
// while the session is locked: locked, a pad button does nothing at all. The
// stand-in hyprctl (fixtures/TabletLockTest/bin) notes what it is asked.
TestCase {
    readonly property FileView asked: FileView {
        path: Quickshell.shellDir + "/../fixtures/hyprctl"
        blockAllReads: true
        printErrors: false
    }

    function calls(): var {
        asked.reload();
        return asked.text().split("\n").filter(line => line !== "");
    }

    function test_unlockedAButtonPressesItsShortcut() {
        Tablet.setButton(0, "keys:SUPER + SHIFT + m");
        Tablet.setButton(1, "quickmenu");
        Tablet.press(0, true);
        return tryVerify(() => calls().length === 1, 3000, "hyprctl is asked").then(() => {
            compare(calls()[0], 'eval require("modules.tablet").press("SUPER SHIFT", "m")');
        });
    }

    function test_lockedNoButtonDoesAnything() {
        LockService.lock();
        Tablet.press(0, true);
        Tablet.press(1, true);
        Tablet.press(1, false);
        return wait(500).then(() => compare(calls().length, 1, "nothing asked while locked"));
    }
}
