import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// A question PAM asks after the password (a one-time code, here pam_stress's
// "STRESS Password: ", fixtures/LockCodeTest/pam.d): the password typed before
// Enter answers only the first one, the field is emptied for the next, and a
// wrong answer keeps the session locked.
TestCase {
    readonly property string secret: Quickshell.env("QML_SECRET")
    readonly property FileView codes: FileView {
        path: Quickshell.shellDir + "/../fixtures/codes"
        blockAllReads: true
        printErrors: false
    }

    function answers(): var {
        codes.reload();
        return codes.text().split("\n").filter(line => line !== "");
    }

    function enter(text: string) {
        LockService.password = text;
        LockService.submit();
    }

    function asked(): var {
        return tryVerify(() => LockService.answering, 5000, "the second question");
    }

    function test_theQuestionWaitsForItsOwnAnswer() {
        LockService.lock();
        enter(secret);
        return asked().then(() => {
            compare(LockService.prompt, "STRESS Password: ");
            verify(!LockService.promptVisible, "a code is typed hidden, as PAM asks");
            compare(LockService.password, "", "the password is not left in the field");
            verify(!LockService.authenticating, "the field takes the answer");
            return wait(500);
        }).then(() => {
            verify(LockService.answering, "the password did not answer it");
            compare(answers().length, 0);
            verify(LockService.locked);
        });
    }

    function test_aWrongAnswerKeepsItLocked() {
        enter("000000");
        return tryVerify(() => !LockService.answering && !LockService.authenticating, 5000).then(() => {
            verify(LockService.locked);
            compare(LockService.errorText, "Wrong code");
            compare(LockService.prompt, "", "back to the password");
            compare(answers(), ["000000"]);
        });
    }

    function test_theRightAnswerUnlocks() {
        enter(secret);
        return asked().then(() => {
            enter("123456");
            return tryVerify(() => !LockService.locked, 5000, "unlocked");
        }).then(() => compare(LockService.prompt, ""));
    }
}
