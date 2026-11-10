import QtQuick
import QtQuick.Window
import Quickshell.Services.UPower
import "../shell/panels"

// The quick settings' first page (panels/BatteryPanel). A desktop has no
// battery, and its page read "Battery 0%, State Unknown": there it is the
// power profiles alone, under "Power". No UPower answers here, which is a
// machine without a battery.
TestCase {
    readonly property Window window: Window {
        width: 400
        height: 400
        visible: true
    }
    readonly property Component panel: Component {
        BatteryPanel {
            width: 320
        }
    }

    // Every DetailRow shown: the item with a label and a value.
    function rows(item, found): var {
        for (const child of item.children) {
            if (!child.visible)
                continue;
            if (typeof child.label === "string" && typeof child.value === "string")
                found.push(child.label);
            rows(child, found);
        }
        return found;
    }

    function test_aDesktopsPageIsThePowerProfilesAlone() {
        // No system bus here: no UPower, power profiles, network or adapter.
        ignoreWarning("Could not connect to DBus");
        ignoreWarning("Network will not work");
        const shown = panel.createObject(window.contentItem);
        verify(!UPower.displayDevice.isLaptopBattery, "no battery here");
        verify(!shown.battery);
        compare(shown.title, "Power");
        return wait(100).then(() => {
            const labels = rows(shown, []);
            compare(labels.length, 0, "no row of a battery: " + labels.join(", "));
            verify(shown.implicitHeight > shown.chromeHeight, "the power profiles are there: " + shown.implicitHeight);
        });
    }
}
