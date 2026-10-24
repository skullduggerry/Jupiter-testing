import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// A finger the reader does not match (fixtures/LockFingerRefusedTest/pam)
// never unlocks; the lock goes on listening, a second apart.
TestCase {
    readonly property FileView attempts: FileView {
        path: Quickshell.shellDir + "/../fixtures/attempts"
        blockAllReads: true
        printErrors: false
    }

    function attemptCount(): int {
        attempts.reload();
        return attempts.text().split("\n").filter(line => line !== "").length;
    }

    function test_anUnknownFingerKeepsItLocked() {
        LockService.lock();
        return tryVerify(() => attemptCount() >= 2, 5000, "the lock listens again after a refusal").then(() => {
            verify(LockService.locked);
            compare(LockService.errorText, "", "a refused finger is no error to show");
        });
    }

    function test_unlockedItStopsListening() {
        LockService.locked = false;
        return wait(1500).then(() => {
            const after = attemptCount();
            return wait(1500).then(() => compare(attemptCount(), after, "no reader is asked while unlocked"));
        });
    }
}
