import QtQuick
import Quickshell
import Quickshell.Io
import "../greeter"

// A machine with a fingerprint reader (fixtures/finger/): the greeter asks
// the first user (dana) for a finger as it opens, by answering the
// password's question with nothing, which etc/pam.d/greetd sends to the
// reader, and says nothing when that times out. Enter on an empty field asks
// again; while the reader has greetd, a password entered goes after it, as a
// login of its own; what the reader says is shown; a typed password still
// goes as the password; someone with no finger enrolled is told no password
// was entered. Someone else picked while it scans is not logged in by the
// finger (the password they typed waits for Enter), nor told how the scan
// ended. The login a finger finishes is
// GreeterFingerLoginTest's.
TestCase {
    readonly property string secret: Quickshell.env("QML_SECRET")
    readonly property FileView log: FileView {
        path: Quickshell.env("GREETD_LOG")
        blockAllReads: true
        printErrors: false
    }

    function requests(): var {
        log.reload();
        return log.text().split("\n").filter(line => line !== "").map(line => JSON.parse(line));
    }

    function created(): int {
        return requests().filter(request => request.type === "create_session").length;
    }

    function thisLogin(): var {
        const all = requests();
        const start = all.map(request => request.type).lastIndexOf("create_session");
        return start < 0 ? [] : all.slice(start);
    }

    function enter(user: string, password: string) {
        GreeterService.username = user;
        GreeterService.password = password;
        GreeterService.submit();
    }

    function settled(): var {
        return tryVerify(() => !GreeterService.busy && !GreeterService.scanning, 5000, "greetd answers");
    }

    // First: the scan the greeter begins as it opens, before anything else.
    function test_aFingerIsAskedForAsItOpens() {
        ignoreWarning("Received unexpected greetd response");
        return tryVerify(() => GreeterService.scanning, 5000, "the greeter scans by itself").then(() => {
            verify(GreeterService.fingerprint, "greeter-env.py found a reader");
            compare(GreeterService.username, "dana");
            compare(GreeterService.promptText, "Password or fingerprint", "as the lock screen's");
            verify(!GreeterService.busy, "the field takes a password meanwhile");
            return settled();
        }).then(() => {
            const login = thisLogin();
            compare(created(), 1);
            compare(login[0].username, "dana");
            compare(login[1].response, "", "the password's question answered with nothing");
            compare(GreeterService.errorText, "", "no finger in time is no error");
            compare(GreeterService.promptText, "Password or fingerprint");
        });
    }

    function test_aPasswordEnteredWhileItScansGoesAfter() {
        ignoreWarning("Received unexpected greetd response");
        let before = 0;
        return settled().then(() => {
            before = created() + 1;
            enter("dana", "");
            verify(GreeterService.scanning);
            // Its answer, and the reader's message acknowledged, which greetd
            // answers once the reader is done.
            return tryVerify(() => created() === before && thisLogin().length >= 3, 5000, "the reader has greetd");
        }).then(() => {
            compare(thisLogin()[1].response, "");
            enter("dana", "not the password");
            verify(GreeterService.busy, "the password waits for the reader");
            compare(created(), before, "nothing more until the reader is done");
            return tryVerify(() => created() > before, 5000, "a login of its own").then(() => settled());
        }).then(() => {
            compare(thisLogin()[1].response, "not the password");
            compare(GreeterService.errorText, "Incorrect password");
        });
    }

    function test_aFingerThatDoesNotMatch() {
        ignoreWarning("Received unexpected greetd response");
        return settled().then(() => {
            enter("frank", "");
            return settled();
        }).then(() => {
            const login = thisLogin();
            // Quickshell ends the session greetd ended with cancel_session.
            compare(login.slice(0, 4).map(request => request.type).join(" "), "create_session post_auth_message_response post_auth_message_response post_auth_message_response");
            compare(login[1].response, "", "the password's question answered with nothing");
            compare(GreeterService.errorText, "Place your finger on the fingerprint reader\nFailed to match fingerprint");
            compare(GreeterService.promptText, "Password or fingerprint");
            verify(!GreeterService.answering);
        });
    }

    function test_noFingerEnrolledIsNoPasswordEntered() {
        ignoreWarning("Received unexpected greetd response");
        return settled().then(() => {
            enter("gina", "");
            return settled();
        }).then(() => {
            compare(thisLogin()[1].response, "");
            compare(GreeterService.errorText, "No password entered!");
        });
    }

    function test_aFingerForTheUserPickedBeforeLogsNobodyIn() {
        ignoreWarning("Received unexpected greetd response");
        let before = 0;
        return settled().then(() => {
            before = created() + 1;
            enter("hana", "");
            return tryVerify(() => created() === before && thisLogin().length >= 3, 5000, "the reader has greetd");
        }).then(() => {
            enter("frank", "not the password");
            verify(GreeterService.busy, "the password waits for the reader");
            return settled();
        }).then(() => {
            // greetd's answer to the cancel must not meet a login of frank's.
            const login = thisLogin();
            compare(login[0].username, "hana");
            compare(login.map(request => request.type).filter(type => type === "start_session" || type === "cancel_session").join(" "), "cancel_session", "hana's finger started nothing");
            compare(GreeterService.password, "not the password", "kept for Enter");
            compare(GreeterService.errorText, "");
            GreeterService.submit();
            return tryVerify(() => created() > before, 5000, "frank's own login").then(() => settled());
        }).then(() => {
            compare(thisLogin()[0].username, "frank");
            compare(thisLogin()[1].response, "not the password");
            compare(GreeterService.errorText, "Incorrect password");
            compare(requests().filter(request => request.type === "start_session").length, 0);
        });
    }

    function test_aScanForTheUserPickedBeforeEndsQuietly() {
        ignoreWarning("Received unexpected greetd response");
        return settled().then(() => {
            enter("dana", "");
            verify(GreeterService.scanning);
            GreeterService.username = "erin";
            return settled();
        }).then(() => {
            compare(GreeterService.errorText, "", "dana's reader timing out is not erin's error");
            compare(GreeterService.promptText, "Password or fingerprint");
        });
    }

    function test_aTypedPasswordIsThePasswordStill() {
        ignoreWarning("Received unexpected greetd response");
        return settled().then(() => {
            enter("erin", "not the password");
            return settled();
        }).then(() => {
            const login = thisLogin();
            compare(login[1].response, "not the password");
            compare(GreeterService.errorText, "Incorrect password");
        });
    }
}
