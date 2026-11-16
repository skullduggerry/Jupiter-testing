import QtQuick
import "../shell/services"

// The lock's fingerprint where the system declares the reader's stack
// (/etc/pam.d/jupiter-fingerprint, as the installer does on NixOS): that stack is
// run, and the shell's own pam/fingerprint.conf, here one that refuses
// every finger, is not.
TestCase {
    function test_theSystemsStackUnlocks() {
        verify(LockService.systemFingerprint, "the system's stack is found");
        LockService.lock();
        verify(LockService.locked);
        return tryVerify(() => !LockService.locked, 3000, "its finger unlocks").then(() => {
            compare(LockService.errorText, "");
        });
    }
}
