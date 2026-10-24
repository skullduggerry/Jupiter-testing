import QtQuick
import Quickshell
import Quickshell.Io
import "../greeter"

// A login with a code after the password: the session starts once both are
// right, and the code goes to the code's question only.
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

    function test_theCodeFinishesTheLogin() {
        ignoreWarning("Hyprland");
        return tryVerify(() => GreeterService.ready, 5000).then(() => {
            GreeterService.username = "bob";
            GreeterService.password = secret;
            GreeterService.submit();
            return tryVerify(() => GreeterService.answering, 5000, "the code is asked for");
        }).then(() => {
            compare(asked("start_session").length, 0, "not before the code");
            GreeterService.password = "123456";
            GreeterService.submit();
            return tryVerify(() => asked("start_session").length > 0, 5000, "the session starts");
        }).then(() => {
            compare(asked("post_auth_message_response").map(request => request.response === secret ? "password" : request.response).join(" "), "password 123456");
            compare(asked("create_session").map(request => request.username).join(" "), "bob");
        });
    }
}
