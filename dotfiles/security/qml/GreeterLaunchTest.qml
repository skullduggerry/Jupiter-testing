import QtQuick
import Quickshell
import Quickshell.Io
import "../greeter"

// A session starts only once PAM let the user in, and only one of those
// listed (fixtures/greeter/greeter-env.py), as the argv it is listed with:
// greetd runs it without a shell, so nothing in its name is run.
TestCase {
    readonly property string secret: Quickshell.env("QML_SECRET")
    readonly property FileView log: FileView {
        path: Quickshell.env("GREETD_LOG")
        blockAllReads: true
        printErrors: false
    }

    function asked(type: string): var {
        log.reload();
        return log.text().split("\n").filter(line => line !== "").map(line => JSON.parse(line)).filter(request => request.type === type);
    }

    function test_aSessionNotListedIsNeverStarted() {
        ignoreWarning("Received unexpected greetd response");
        return tryVerify(() => GreeterService.ready, 5000).then(() => {
            GreeterService.sessionExec = "rm -rf ~";
            GreeterService.password = secret;
            GreeterService.submit();
            return tryVerify(() => GreeterService.errorText !== "", 5000, "the login ends");
        }).then(() => {
            compare(GreeterService.errorText, "No session to start");
            compare(asked("cancel_session").length, 1);
            compare(asked("start_session").length, 0);
        });
    }

    function test_theChosenSessionStarts() {
        // Hyprland ends the greeter's compositor once the session started;
        // there is none here.
        ignoreWarning("Hyprland");
        GreeterService.sessionExec = GreeterService.sessions[1].exec;
        GreeterService.password = secret;
        GreeterService.submit();
        return tryVerify(() => asked("start_session").length > 0, 5000, "a session starts").then(() => {
            const [started] = asked("start_session");
            compare(JSON.stringify(started.cmd), JSON.stringify(["sh", "-c", "echo; $(not run)"]));
            compare(started.env.length, 0, "no environment of the greeter's");
            compare(asked("create_session").slice(-1)[0].username, "alice");
        });
    }
}
