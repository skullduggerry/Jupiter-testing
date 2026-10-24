import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// pam_fprintd only tells (place a finger, no match). A fingerprint stack that
// asks something instead (fixtures/LockFingerQuestionTest/pam) is not the one
// the lock expects: it is ended unanswered, and the session stays locked.
TestCase {
    readonly property FileView answer: FileView {
        path: Quickshell.shellDir + "/../fixtures/answered-once"
        blockAllReads: true
        printErrors: false
    }

    function test_aQuestionGetsNoAnswer() {
        LockService.lock();
        LockService.password = "typed so far";
        return wait(1500).then(() => {
            verify(LockService.locked);
            verify(!LockService.fingerprint, "not listening on a stack that asks");
            answer.reload();
            compare(answer.text(), "", "nothing was answered");
        });
    }
}
