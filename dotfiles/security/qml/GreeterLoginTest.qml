import QtQuick
import Quickshell
import Quickshell.Io
import "../greeter"

// Logging in, against a stand-in greetd (fixtures/greeter/greetd.json): no
// attempt without a password, a wrong one starts no session, what PAM says
// is what the screen shows, a question after the password waits for its own
// answer, and choosing someone else while it waits ends that login. Nothing
// here logs in: a session that starts ends the greeter (GreeterLaunchTest).
TestCase {
    readonly property string secret: Quickshell.env("QML_SECRET")
    readonly property FileView log: FileView {
        path: Quickshell.env("GREETD_LOG")
        blockAllReads: true
        printErrors: false
    }

    // What greetd was asked, oldest first.
    function requests(): var {
        log.reload();
        return log.text().split("\n").filter(line => line !== "").map(line => JSON.parse(line));
    }

    function asked(type: string): var {
        return requests().filter(request => request.type === type);
    }

    // What greetd was asked in the latest login.
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

    function test_whoCanLogInAndIntoWhat() {
        // Quickshell's greetd client logs the session greetd ends after a
        // failure as an unexpected answer; greetd does answer it.
        ignoreWarning("Received unexpected greetd response");
        return tryVerify(() => GreeterService.ready, 5000, "users and sessions listed").then(() => {
            compare(GreeterService.users.length, 3);
            compare(GreeterService.username, "alice", "the first user is chosen");
            compare(GreeterService.sessionExec, "uwsm start -- hyprland.desktop", "a uwsm session first");
            verify(GreeterService.promptSecret, "the password field hides what is typed");
        });
    }

    function test_nothingIsSentWithoutAPassword() {
        enter("alice", "");
        verify(!GreeterService.busy);
        return wait(300).then(() => compare(requests().length, 0, "greetd was asked nothing"));
    }

    function test_aWrongPasswordStartsNothing() {
        enter("alice", "not the password");
        return settled().then(() => {
            compare(GreeterService.errorText, "Incorrect password");
            compare(GreeterService.password, "", "the field is emptied");
            compare(asked("create_session").map(request => request.username), ["alice"]);
            compare(asked("post_auth_message_response").map(request => request.response), ["not the password"]);
            compare(asked("start_session").length, 0);
        });
    }

    function test_whatPamSaysIsShown() {
        enter("carol", secret);
        return settled().then(() => {
            compare(GreeterService.errorText, "The account is locked due to 3 failed logins.");
            compare(asked("start_session").length, 0);
        });
    }

    // greetd refusing the login before it asks anything: the password typed
    // does not stay in the field.
    function test_aRefusedLoginEmptiesTheField() {
        ignoreWarning("Greetd error occurred");
        enter("dave", secret);
        return settled().then(() => {
            verify(GreeterService.errorText.includes("dave may not log in here"), GreeterService.errorText);
            compare(GreeterService.password, "");
            compare(thisLogin().length, 1, "only the login was asked for");
        });
    }

    function test_aSecondQuestionWaitsForItsAnswer() {
        enter("bob", secret);
        return tryVerify(() => GreeterService.answering, 5000, "the code is asked for").then(() => {
            compare(GreeterService.promptText, "Verification code:");
            verify(!GreeterService.promptSecret, "a visible question shows what is typed");
            compare(GreeterService.password, "", "the password is not left in the field");
            verify(!GreeterService.busy, "the field takes the answer");
            // Answered once: the password went to the password's question only.
            const answers = thisLogin().filter(request => request.type === "post_auth_message_response");
            compare(answers.length, 1);
            verify(answers[0].response === secret);
        });
    }

    // The code typed after choosing alice must not finish bob's login.
    function test_anotherUserEndsTheLoginThatWaits() {
        GreeterService.username = "alice";
        verify(!GreeterService.answering);
        compare(GreeterService.promptText, "Password", "back to the password");
        verify(GreeterService.promptSecret);
        return wait(300).then(() => {
            compare(requests().slice(-1)[0].type, "cancel_session");
            GreeterService.password = "123456";
            GreeterService.submit();
            return settled();
        }).then(() => {
            const sessions = asked("create_session").map(request => request.username);
            compare(sessions.slice(-1)[0], "alice", "a new login, for alice");
            compare(asked("start_session").length, 0);
        });
    }
}
