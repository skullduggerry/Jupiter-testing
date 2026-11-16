import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// Fingers that do not match (fixtures/LockFingerMissesTest/pam, each attempt
// one try, as pam/fingerprint.conf's) are counted: after three the lock
// leaves the password, until it is locked again.
TestCase {
    readonly property FileView attempts: FileView {
        path: Quickshell.shellDir + "/../fixtures/attempts"
        blockAllReads: true
        printErrors: false
    }
    readonly property string refused: "Fingerprint not recognised: type the password"

    function attemptCount(): int {
        attempts.reload();
        return attempts.text().split("\n").filter(line => line !== "").length;
    }

    function test_threeMissesLeaveThePassword() {
        LockService.lock();
        return tryVerify(() => LockService.errorText !== "", 5000, "the third miss says so").then(() => {
            compare(LockService.errorText, refused);
            verify(LockService.locked);
            compare(attemptCount(), 3);
            return wait(2500).then(() => {
                compare(attemptCount(), 3, "the reader is not asked a fourth time");
                verify(!LockService.fingerprint, "and the prompt no longer offers it");
                verify(LockService.locked);
            });
        });
    }

    function test_theNextLockCountsAnew() {
        LockService.locked = false;
        const before = attemptCount();
        LockService.lock();
        return tryVerify(() => LockService.errorText === refused, 5000, "three more, then the password").then(() => {
            compare(attemptCount(), before + 3);
            verify(LockService.locked);
        });
    }
}
