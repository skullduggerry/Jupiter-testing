import QtQuick
import "../shell/services"

// The lock's fingerprint, with pam/fingerprint.conf here standing in for the
// reader (it says what pam_fprintd says, then lets the finger in). Nothing
// here submits a password: that would go through the system's own "login"
// stack, and pam_faillock.
TestCase {
    function test_aFingerUnlocks() {
        LockService.lock();
        verify(LockService.locked);
        return tryVerify(() => !LockService.locked, 3000, "the finger unlocks").then(() => {
            verify(!LockService.fingerprint, "and is not listened for once unlocked");
            compare(LockService.errorText, "");
        });
    }

    function test_againAtTheNextLock() {
        LockService.lock();
        return tryVerify(() => !LockService.locked, 3000, "a second lock listens again");
    }
}
