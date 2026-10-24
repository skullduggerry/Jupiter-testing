import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// The quick menu's look and Halo's labels, which Settings and the pencil's
// panel pick: kept in its file, and the look Auto for anything it does not
// know, as a file from before the choice existed, or one edited by hand,
// would have.
TestCase {
    readonly property FileView written: FileView {
        path: Quickshell.statePath("quick-menu.json")
        blockLoading: true
        printErrors: false
    }

    function stored(): var {
        written.reload();
        return JSON.parse(written.text() || "{}");
    }

    function test_aLookIsKept() {
        compare(QuickMenu.look, "auto", "the look before one is picked");
        QuickMenu.setLook("orbit");
        compare(QuickMenu.look, "orbit");
        return tryVerify(() => stored().look === "orbit", 2000, "the look is written").then(() => {
            QuickMenu.setLook("halo");
            compare(QuickMenu.look, "halo");
        });
    }

    function test_labelsCanBeHidden() {
        verify(QuickMenu.labels, "labels before any choice");
        QuickMenu.setLabels(false);
        verify(!QuickMenu.labels);
        return tryVerify(() => stored().labels === false, 2000, "the choice is written").then(() => QuickMenu.setLabels(true));
    }

    function test_anUnknownLookIsAuto() {
        QuickMenu.setLook("sparkly");
        compare(QuickMenu.look, "auto");
    }
}
