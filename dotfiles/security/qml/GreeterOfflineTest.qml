import QtQuick
import "../greeter"

// Without greetd (no GREETD_SOCK) the login screen says so and takes no
// password.
TestCase {
    function test_noGreetdNoLogin() {
        return tryVerify(() => GreeterService.listed, 5000, "users listed").then(() => {
            verify(!GreeterService.ready);
            verify(!GreeterService.canSubmit);
            compare(GreeterService.errorText, "greetd is not running (no GREETD_SOCK)");
            GreeterService.password = "anything";
            GreeterService.submit();
            verify(!GreeterService.busy, "nothing started");
        });
    }
}
