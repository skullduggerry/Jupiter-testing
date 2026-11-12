import QtQuick
import QtQuick.Window
import "../shell/settings"

// Settings → Displays arranging the monitors the stand-in hyprctl
// (fixtures/DisplaysPageTest/bin) lists: a laptop under a big display. A
// drop or a change of size leaves every monitor flush against another along
// enough of an edge, anywhere along it, and covering none; a row closes up
// round one that turns off. A display that grew over its neighbour was how
// two of them came to overlap.
TestCase {
    readonly property Window window: Window {
        width: 900
        height: 900
        visible: true
    }
    readonly property Component page: Component {
        DisplaysPage {
            anchors.fill: parent
        }
    }

    // A fresh page, once it has read the monitors.
    function opened(): var {
        // No session here: no Hyprland, system bus or backlight for the
        // services the page's other rows read.
        ignoreWarning("HYPRLAND_INSTANCE_SIGNATURE is unset");
        ignoreWarning("Could not connect to DBus");
        ignoreWarning("Network will not work");
        ignoreWarning("/sys/class/backlight");
        const shown = page.createObject(window.contentItem) as DisplaysPage;
        return tryVerify(() => shown.monitors.length === 2, 3000, "hyprctl's monitors are read").then(() => shown);
    }

    // Where each monitor would go, in logical pixels.
    function places(shown: DisplaysPage): var {
        const result = {};
        for (const monitor of shown.enabledMonitors)
            result[monitor.name] = shown.box(monitor);
        return result;
    }

    function at(shown: DisplaysPage, name: string): string {
        const one = places(shown)[name];
        return one.x + "," + one.y;
    }

    // Each monitor touches another along an edge, and none covers another.
    function verifyArranged(shown: DisplaysPage) {
        const boxes = Object.values(places(shown));
        for (const one of boxes) {
            verify(boxes.some(other => other !== one && shown.side(one, other) !== ""), one.name + " touches another: " + JSON.stringify(boxes));
            verify(!boxes.some(other => other !== one && shown.overlaps(one, other)), one.name + " covers none: " + JSON.stringify(boxes));
        }
        compare(Math.min(...boxes.map(one => one.x)), 0, "the layout starts at x 0");
        compare(Math.min(...boxes.map(one => one.y)), 0, "the layout starts at y 0");
    }

    function row(shown: DisplaysPage) {
        shown.pending = {};
        shown.monitors = ["A", "B", "C"].map((name, index) => ({
                    name: name,
                    description: "",
                    width: 1920,
                    height: 1080,
                    refreshRate: 60,
                    x: index * 1920,
                    y: 0,
                    scale: 1,
                    transform: 0,
                    vrr: false,
                    disabled: false,
                    modes: []
                }));
    }

    function test_aDropSlidesAlongTheEdgeToAnyOffset() {
        return opened().then(shown => {
            compare(at(shown, "eDP-1"), "1120,1440", "the laptop starts lined up at the right");
            shown.drop("eDP-1", -800, 0);
            compare(at(shown, "eDP-1"), "320,1440", "neither lined up nor centred");
            verifyArranged(shown);
            shown.destroy();
        });
    }

    function test_aDropNearAnEndOrTheMiddleSnapsToIt() {
        return opened().then(shown => {
            // From 1120: 620 is near the middle, 50 near the left, 1100 the right.
            const cases = [[-500, "560,1440", "the middle"], [-510, "0,1440", "the left"], [1100, "1120,1440", "the right"]];
            for (const one of cases) {
                shown.drop("eDP-1", one[0], 0);
                compare(at(shown, "eDP-1"), one[1], "snapped to " + one[2]);
            }
            shown.destroy();
        });
    }

    function test_aDropOntoAnotherLandsBesideIt() {
        return opened().then(shown => {
            shown.drop("eDP-1", -500, -1200);
            verifyArranged(shown);
            shown.destroy();
        });
    }

    // Past a corner the laptop keeps a quarter of its 1440-wide edge.
    function test_aDropKeepsEnoughOfTheEdgeToCross() {
        return opened().then(shown => {
            // Below and past the right corner, nearer below than beside it.
            shown.drop("eDP-1", 1300, 500);
            compare(at(shown, "eDP-1"), "2200,1440", "a quarter of the edge is shared");
            shown.drop("eDP-1", -9000, 0);
            verifyArranged(shown);
            const boxes = places(shown);
            const laptop = boxes["eDP-1"];
            const big = boxes["DP-2"];
            const across = ["left", "right"].includes(shown.side(laptop, big));
            const shared = across ? Math.min(laptop.y + laptop.height, big.y + big.height) - Math.max(laptop.y, big.y) : Math.min(laptop.x + laptop.width, big.x + big.width) - Math.max(laptop.x, big.x);
            verify(shared >= Math.ceil((across ? laptop.height : laptop.width) / 4), "a quarter of the edge is shared: " + JSON.stringify(boxes));
            shown.destroy();
        });
    }

    function test_aRescaledDisplayKeepsHowItSat() {
        return opened().then(shown => {
            shown.drop("eDP-1", -560, 0);
            compare(at(shown, "eDP-1"), "560,1440", "centred");
            shown.reshape("DP-2", {
                scale: 1.25
            });
            compare(at(shown, "eDP-1"), "816,1728", "still centred under the larger display");
            shown.reshape("eDP-1", {
                transform: 1
            });
            compare(at(shown, "eDP-1"), "1056,1728", "still centred, turned on its side");
            verifyArranged(shown);
            shown.drop("eDP-1", -700, 0);
            const offset = places(shown)["eDP-1"].x;
            shown.reshape("eDP-1", {
                scale: 1.5
            });
            compare(places(shown)["eDP-1"].x, offset, "an offset is kept too");
            verifyArranged(shown);
            shown.destroy();
        });
    }

    function test_aGrownDisplayPushesTheRowAlong() {
        return opened().then(shown => {
            row(shown);
            shown.reshape("B", {
                width: 2560,
                height: 1440
            });
            compare([at(shown, "A"), at(shown, "B"), at(shown, "C")], ["0,0", "1920,0", "4480,0"]);
            shown.reshape("B", {
                width: 1280,
                height: 720
            });
            compare([at(shown, "A"), at(shown, "B"), at(shown, "C")], ["0,0", "1920,0", "3200,0"], "and closes up when it shrinks");
            shown.destroy();
        });
    }

    function test_aRowClosesUpRoundOneTurnedOffOrMoved() {
        return opened().then(shown => {
            row(shown);
            shown.reshape("B", {
                disabled: true
            });
            compare([at(shown, "A"), at(shown, "C")], ["0,0", "1920,0"], "C moves up against A");
            verifyArranged(shown);
            shown.reshape("B", {
                disabled: false
            });
            verifyArranged(shown);
            row(shown);
            shown.drop("B", 0, 1500);
            verifyArranged(shown);
            shown.destroy();
        });
    }
}
