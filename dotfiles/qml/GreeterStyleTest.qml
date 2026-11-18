import QtQuick
import "../greeter/style"

// style/ as the login screen runs it ("style/ must run as the greeter" in
// the dotfiles' CLAUDE.md): with no home it builds on its defaults, and a write,
// a process or Quickshell.statePath() would log a warning here.
TestCase {
    function test_buildsWithoutAHome() {
        compare(Theme.theme, "Oxocarbon-Dark");
        compare(Colors.palette.background, "#0f0f0f");
        verify(Style.bar !== null && Colors.lock !== null);
        verify(LockLook.dim > 0);
        // Whatever it started has had the time to complain.
        return wait(200);
    }
}
