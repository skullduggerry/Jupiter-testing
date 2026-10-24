import QtQuick
import Quickshell.Io
import "../shell/services"

// The idle times the Power page picks, as the config hypridle is started on.
TestCase {
    readonly property FileView written: FileView {
        path: Idle.config
        blockLoading: true
        printErrors: false
    }

    // Whether the config hypridle reads has this line, once it is on disk.
    function onDisk(line: string): bool {
        written.reload();
        return written.text().split("\n").includes(line);
    }

    function test_minutesAreWrittenAsSeconds() {
        Idle.write(5, 120);
        return tryVerify(() => onDisk("$lockAfter = 300")).then(() => {
            verify(onDisk("$suspendAfter = 7200"));
            compare(Idle.lockMinutes, 5);
            compare(Idle.suspendMinutes, 120);
        });
    }

    // hyprlang's `if` tests for a value, so never is an empty one.
    function test_neverIsEmpty() {
        Idle.write(0, 10);
        return tryVerify(() => onDisk("$lockAfter = ")).then(() => compare(Idle.lockMinutes, 0));
    }
}
