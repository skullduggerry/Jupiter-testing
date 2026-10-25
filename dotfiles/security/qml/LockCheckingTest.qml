import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// While PAM checks the password the lock says so: the field is read only
// and shows "Checking…" (LockSurface reads `authenticating`), and Enter
// again starts or answers nothing. The stand-in stack takes a second over
// each password, as pam_unix does after a wrong one.
TestCase {
    readonly property string secret: Quickshell.env("QML_SECRET")
    readonly property FileView attempts: FileView {
        path: Quickshell.shellDir + "/../fixtures/attempts"
        blockAllReads: true
        printErrors: false
    }

    function attemptCount(): int {
        attempts.reload();
        return attempts.text().split("\n").filter(line => line !== "").length;
    }

    // Whether PAM had answered by the time `authenticating` ended.
    function checkingThroughout(): var {
        return new Promise(resolve => {
            const look = () => {
                if (!LockService.authenticating)
                    return resolve(LockService.errorText !== "" || !LockService.locked);
                wait(50).then(look);
            };
            look();
        });
    }

    function test_checkingShowsUntilPamAnswers() {
        LockService.lock();
        LockService.password = "not the password";
        LockService.submit();
        verify(LockService.authenticating, "checking at once");
        return wait(300).then(() => {
            verify(LockService.authenticating, "still checking while PAM is");
            verify(!LockService.answering, "no question is waiting on the field");
            LockService.password = "typed again";
            LockService.submit();
            return checkingThroughout();
        }).then(answered => {
            verify(answered, "checking ended before PAM answered");
            compare(LockService.errorText, "Incorrect password");
            verify(LockService.locked);
            compare(attemptCount(), 1, "a second Enter started nothing");
        });
    }

    function test_thenThePasswordUnlocks() {
        LockService.password = secret;
        LockService.submit();
        return wait(300).then(() => {
            verify(LockService.authenticating);
            return tryVerify(() => !LockService.locked, 5000, "unlocked");
        });
    }
}
