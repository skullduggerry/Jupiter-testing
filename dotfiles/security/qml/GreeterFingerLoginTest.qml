import QtQuick
import Quickshell
import Quickshell.Io
import "../greeter"

// A finger the reader matches logs in: only once greetd says so, and with
// nothing typed. The one login of this file, last (fixtures/finger/).
TestCase {
    readonly property FileView log: FileView {
        path: Quickshell.env("GREETD_LOG")
        blockAllReads: true
        printErrors: false
    }

    function asked(type: string): var {
        log.reload();
        return log.text().split("\n").filter(line => line !== "").map(line => JSON.parse(line)).filter(request => request.type === type);
    }

    function test_aMatchingFingerLogsIn() {
        ignoreWarning("Hyprland");
        return tryVerify(() => GreeterService.ready, 5000).then(() => {
            GreeterService.username = "erin";
            GreeterService.password = "";
            GreeterService.submit();
            return tryVerify(() => asked("start_session").length > 0, 5000, "the session starts");
        }).then(() => {
            compare(asked("post_auth_message_response").map(request => request.response === undefined ? "-" : request.response).join(" "), " -");
            compare(asked("start_session")[0].cmd.join(" "), "uwsm start -- hyprland.desktop");
        });
    }
}
