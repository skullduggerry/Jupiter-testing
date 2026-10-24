import QtQuick
import "../greeter/style"

// style/ as the login screen runs it once scripts/install-greeter.sh has put
// the desktop's theme beside it (LOCKSCREEN_THEME): read, and as unwritable as
// it is in /etc/greetd, so a write would log here.
TestCase {
    function test_readsTheInstalledTheme() {
        // The theme and its palette load as the desktop's do, after the start.
        return tryVerify(() => Theme.theme === "Everforest-Light-Hard" && Colors.light, 2000, "the installed theme").then(() => {
            compare(Colors.palette.background, "#fffbef");
            compare(Theme.accent, "green");
            verify(LockLook.glass, "the desktop's blur, its theme followed by default");
            compare(Colors.lock.text, Colors.text.base);
            // The desktop's own record of its light theme is behind (a theme
            // applied since); the greeter must not bring the copy up to date.
            return wait(500);
        }).then(() => compare(Theme.lightTheme, "Catppuccin-Latte"));
    }
}
