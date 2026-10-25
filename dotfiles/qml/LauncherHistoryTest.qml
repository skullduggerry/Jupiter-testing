import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// The launcher's order (quickmenu/QuickMenuApps): each launch is counted by
// its command and kept in the state folder, once the launches settle.
TestCase {
    readonly property FileView written: FileView {
        path: Quickshell.statePath("launcher-history.json")
        blockAllReads: true
        printErrors: false
    }

    function launches(): var {
        written.reload();
        const text = written.text();
        return text === "" ? null : JSON.parse(text).launches;
    }

    function test_launchesAreCounted() {
        compare(LauncherHistory.count("firefox"), 0);
        LauncherHistory.record("firefox");
        LauncherHistory.record("firefox");
        LauncherHistory.record("kitty");
        LauncherHistory.record("");
        compare(LauncherHistory.count("firefox"), 2);
        compare(LauncherHistory.count("kitty"), 1);
        compare(LauncherHistory.count(""), 0, "nothing to count by");
    }

    function test_keptInTheStateFolder() {
        return tryVerify(() => launches() !== null).then(() => {
            compare(launches().firefox, 2);
            compare(launches().kitty, 1);
        });
    }
}
