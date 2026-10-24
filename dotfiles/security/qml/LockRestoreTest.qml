import QtQuick
import "../shell/services"

// A shell that crashed while locked is started again by Quickshell's crash
// handler, unlocked, while Hyprland keeps the screen covered: the marker it
// left beside Hyprland's socket (fixtures/LockRestoreTest/runtime) locks it
// again at once, before anything is drawn unlocked.
TestCase {
    function test_aShellRestartedWhileLockedLocksAgain() {
        verify(LockService.locked);
        compare(LockService.password, "");
    }
}
