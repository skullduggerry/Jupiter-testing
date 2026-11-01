import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// The mouse's and the touchpad's speed and scrolling, as the Keyboard &
// Mouse page sets them: kept in pointer.lua for Hyprland's start, handed to
// modules/pointer.lua live, and the touchpads found among the pointers the
// stand-in hyprctl (fixtures/PointerTest/bin) lists.
TestCase {
    readonly property FileView asked: FileView {
        path: Quickshell.shellDir + "/../fixtures/hyprctl"
        blockAllReads: true
        printErrors: false
    }
    readonly property FileView kept: FileView {
        path: Quickshell.env("XDG_STATE_HOME") + "/quickshell/pointer.lua"
        blockAllReads: true
        printErrors: false
    }

    function calls(): var {
        asked.reload();
        return asked.text().split("\n").filter(line => line.startsWith("eval "));
    }

    function lua(): string {
        kept.reload();
        return kept.text();
    }

    function test_aChangeIsKeptAndHandedOver() {
        Pointer.setMouse(0.4, 2);
        compare(Pointer.mouseSpeed, 0.4);
        compare(Pointer.mouseScroll, 2);
        return tryVerify(() => lua().includes("mouseSpeed = 0.40, mouseScroll = 2.00"), 2000, "pointer.lua is written").then(() => {
            verify(lua().startsWith("-- Written by the shell"), "pointer.lua says where it comes from");
            return tryVerify(() => calls().length > 0, 2000, "hyprctl is asked");
        }).then(() => {
            compare(calls()[calls().length - 1], "eval " + 'require("modules.pointer").use({ mouseSpeed = 0.40, mouseScroll = 2.00, touchpadSpeed = 0.00, touchpadScroll = 1.00, touchpads = {  } })');
        });
    }

    function test_valuesStayInLibinputsRange() {
        Pointer.setTouchpad(3, 100);
        compare(Pointer.touchpadSpeed, 1);
        compare(Pointer.touchpadScroll, Pointer.scrollMost);
        Pointer.setTouchpad(-3, 0);
        compare(Pointer.touchpadSpeed, -1);
        compare(Pointer.touchpadScroll, Pointer.scrollLeast);
    }

    // Only names spelt as Hyprland spells devices reach the Lua.
    function test_touchpadsAreFoundByName() {
        Pointer.setTouchpad(-0.25, 1.5);
        Pointer.refresh();
        return tryVerify(() => Pointer.touchpads.length > 0, 3000, "the devices are read").then(() => {
            compare(Array.from(Pointer.touchpads), ["pixa3854:00-093a:0274-touchpad"]);
            return tryVerify(() => lua().includes('touchpads = { "pixa3854:00-093a:0274-touchpad" }'), 2000, "the touchpad is kept");
        }).then(() => {
            verify(lua().includes("touchpadSpeed = -0.25, touchpadScroll = 1.50"));
            verify(!lua().includes("os.execute"), "a name that breaks out of its string is left out");
        });
    }

    // A touchpad unplugged while the page looks keeps its speed for when it
    // is back. Last, as it adds to the touchpads the others compare.
    function test_whileAwayATouchpadIsKept() {
        Pointer.load([
            {
                name: "elan0712:00-04f3:30fd-touchpad"
            }
        ]);
        Pointer.load([
            {
                name: "logitech-usb-receiver"
            }
        ]);
        verify(Pointer.touchpads.includes("elan0712:00-04f3:30fd-touchpad"));
        return tryVerify(() => lua().includes('"elan0712:00-04f3:30fd-touchpad"'), 2000, "the touchpad away is still kept");
    }
}
