import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// The lock screen's password, through a stand-in "login" stack
// (fixtures/lock/pam.d) that takes the harness's password: a wrong one keeps
// the session locked and says so, what PAM says is what the lock shows, the
// field is emptied after every attempt, and nothing is asked without a
// password. The functions run in order, on one LockService.
TestCase {
    readonly property string secret: Quickshell.env("QML_SECRET")
    readonly property FileView marker: FileView {
        path: Quickshell.env("XDG_RUNTIME_DIR") + "/hypr/" + Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") + "/quickshell-locked"
        blockAllReads: true
        printErrors: false
    }
    readonly property FileView attempts: FileView {
        path: Quickshell.shellDir + "/../fixtures/attempts"
        blockAllReads: true
        printErrors: false
    }

    function attemptCount(): int {
        attempts.reload();
        return attempts.text().split("\n").filter(line => line !== "").length;
    }

    function marked(): string {
        marker.reload();
        return marker.text();
    }

    // Types a password and presses Enter, then waits for PAM's answer.
    function enter(password: string): var {
        LockService.password = password;
        LockService.submit();
        return tryVerify(() => !LockService.authenticating, 5000, "PAM answers");
    }

    function test_aNewSessionStartsUnlocked() {
        verify(!LockService.locked);
    }

    function test_lockingIsRecordedForACrash() {
        LockService.lock();
        verify(LockService.locked);
        return tryVerify(() => marked() === "locked\n", 2000, "the marker says locked");
    }

    function test_nothingIsAskedWithoutAPassword() {
        LockService.password = "";
        LockService.submit();
        verify(!LockService.authenticating, "no attempt started");
        return wait(300).then(() => {
            compare(attemptCount(), 0, "PAM was never asked");
            verify(LockService.locked);
        });
    }

    function test_aWrongPasswordKeepsItLocked() {
        return enter("not the password").then(() => {
            verify(LockService.locked);
            compare(LockService.errorText, "Incorrect password");
            compare(LockService.password, "", "the field is emptied");
            compare(attemptCount(), 1);
        });
    }

    function test_whatPamSaysIsShown() {
        return enter("locked out").then(() => {
            verify(LockService.locked);
            compare(LockService.errorText, "The account is locked due to 3 failed logins.");
        });
    }

    function test_typingAgainClearsTheError() {
        LockService.password = "x";
        compare(LockService.errorText, "");
        LockService.password = "";
    }

    function test_thePasswordUnlocks() {
        return enter(secret).then(() => {
            verify(!LockService.locked);
            compare(LockService.password, "", "the password does not stay in the field");
            compare(LockService.errorText, "");
            return tryVerify(() => marked() === "", 2000, "the marker is cleared");
        });
    }

    // Unlocking is no lasting permission: the next lock asks again.
    function test_theNextLockAsksAgain() {
        LockService.password = "half typed";
        LockService.lock();
        compare(LockService.password, "", "a lock starts with an empty field");
        return enter("not the password").then(() => {
            verify(LockService.locked);
            return enter(secret);
        }).then(() => verify(!LockService.locked));
    }
}
