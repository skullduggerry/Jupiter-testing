import QtQuick
import Quickshell
import "../shell/services"

// The apps on offer leave out an entry whose program is gone: an app's own
// copy of its entry can outlive the package (Claude's did). Nothing is on
// PATH here, so the lookup cannot run, and `missing` is set as it would.
TestCase {
    function test_aMissingProgramHidesItsEntry() {
        ignoreWarning("Process failed to start");
        Apps.check();
        return tryVerify(() => Apps.installed.length > 1, 3000, "the entries load").then(() => {
            compare(Apps.installed.length, DesktopEntries.applications.values.filter(entry => entry.name !== "").length, "nothing left out before the lookup answers");
            const gone = Apps.installed[0];
            Apps.missing = [Apps.program(gone)];
            verify(!Apps.installed.includes(gone), "an entry whose program is gone");
            verify(Apps.installed.length > 0, "the others stay");
            verify(Apps.installed.every(entry => Apps.program(entry) !== Apps.program(gone)));
        });
    }
}
