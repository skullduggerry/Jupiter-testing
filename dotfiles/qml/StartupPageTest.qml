import QtQuick
import QtQuick.Window
import Quickshell
import Quickshell.Io
import "../shell/settings"

// Settings → Startup switching apps through a stand-in autostart.py
// (fixtures/StartupPageTest/settings), which takes a moment over each change:
// clicks while one runs are made after it, in turn, none dropped (Quickshell
// starts a running Process once more, with the last command it was given),
// and the list read again once all are done.
TestCase {
    readonly property Window window: Window {
        width: 900
        height: 900
        visible: true
    }
    readonly property Component page: Component {
        StartupPage {
            anchors.fill: parent
        }
    }
    readonly property FileView log: FileView {
        path: Quickshell.shellDir + "/../fixtures/autostart"
        blockAllReads: true
        printErrors: false
    }

    function calls(): var {
        log.reload();
        return log.text().split("\n").filter(line => line !== "");
    }

    function test_clicksWhileAChangeRunsAreMadeInTurn() {
        // No session here: no system bus for the services the page reads.
        ignoreWarning("Could not connect to DBus");
        ignoreWarning("Network will not work");
        ignoreWarning("Could not load icon");
        const shown = page.createObject(window.contentItem) as StartupPage;
        return tryVerify(() => shown.apps.length === 2, 3000, "the apps are listed").then(() => {
            shown.change(["set", "a", "off"]);
            shown.change(["set", "b", "off"]);
            shown.change(["remove", "a"]);
            return tryVerify(() => calls().length === 5, 5000, "every change made, then the list");
        }).then(() => {
            compare(calls(), ["list", "set a off", "set b off", "remove a", "list"]);
        });
    }
}
