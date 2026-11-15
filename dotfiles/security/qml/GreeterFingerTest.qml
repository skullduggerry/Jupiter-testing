import QtQuick
import Quickshell
import Quickshell.Io
import "../greeter"

// A machine with a fingerprint reader (fixtures/finger/): Enter on an empty
// field answers the password's question with nothing, which etc/pam.d/greetd
// sends to the reader; what the reader says is shown; a typed password still
// goes as the password; someone with no finger enrolled is told no password
// was entered. The
// login a finger finishes is GreeterFingerLoginTest's.
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
        return tryVerify(() => !GreeterService.busy, 5000, "greetd answers");
    }

    function test_aFingerThatDoesNotMatch() {
        ignoreWarning("Received unexpected greetd response");
        return tryVerify(() => GreeterService.ready, 5000).then(() => {
            verify(GreeterService.fingerprint, "greeter-env.py found a reader");
            compare(GreeterService.promptText, "Password, or Enter for fingerprint");
            enter("frank", "");
            return settled();
        }).then(() => {
            const login = thisLogin();
            // Quickshell ends the session greetd ended with cancel_session.
            compare(login.slice(0, 4).map(request => request.type).join(" "), "create_session post_auth_message_response post_auth_message_response post_auth_message_response");
            compare(login[1].response, "", "the password's question answered with nothing");
            compare(GreeterService.errorText, "Place your finger on the fingerprint reader\nFailed to match fingerprint");
            compare(GreeterService.promptText, "Password, or Enter for fingerprint");
            verify(!GreeterService.answering);
        });
    }

    function test_noFingerEnrolledIsNoPasswordEntered() {
        ignoreWarning("Received unexpected greetd response");
        return tryVerify(() => GreeterService.ready, 5000).then(() => {
            enter("gina", "");
            return settled();
        }).then(() => {
            compare(thisLogin()[1].response, "");
            compare(GreeterService.errorText, "No password entered!");
        });
    }

    function test_aTypedPasswordIsThePasswordStill() {
        ignoreWarning("Received unexpected greetd response");
        return tryVerify(() => GreeterService.ready, 5000).then(() => {
            enter("erin", "not the password");
            return settled();
        }).then(() => {
            const login = thisLogin();
            compare(login[1].response, "not the password");
            compare(GreeterService.errorText, "Incorrect password");
        });
    }
}
