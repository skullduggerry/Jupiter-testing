import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/panels"

// Clipboard history's actions against a stand-in cliphist
// (fixtures/ClipboardHistoryTest/bin), whose delete takes a moment: an entry
// forgotten while another goes is forgotten all the same, and the list read
// again once they are gone; of copies made while one runs, the last is
// the clipboard's. The services it
// reads (QuickToggles) complain once that the session is not here.
TestCase {
    id: root

    readonly property Component historyComponent: Component {
        ClipboardHistory {
            active: false
        }
    }
    readonly property FileView log: FileView {
        path: Quickshell.shellDir + "/../fixtures/cliphist"
        blockAllReads: true
        printErrors: false
    }
    readonly property FileView calls: FileView {
        path: Quickshell.shellDir + "/../fixtures/calls"
        blockAllReads: true
        printErrors: false
    }

    function lines(view: FileView): var {
        view.reload();
        return view.text().split("\n").filter(line => line !== "");
    }

    function make(): ClipboardHistory {
        ignoreWarning("DBus|Network will not work");
        return historyComponent.createObject(root) as ClipboardHistory;
    }

    function test_entriesForgottenMeanwhileGoToo() {
        const history = make();
        history.forget("1\tone");
        history.forget("2\ttwo");
        history.forget("3\tthree");
        return tryVerify(() => lines(log).filter(line => line.startsWith("delete ")).length === 3, 5000, "every entry deleted").then(() => {
            compare(lines(log).filter(line => line.startsWith("delete ")).sort(), ["delete 1\tone", "delete 2\ttwo", "delete 3\tthree"]);
            return tryVerify(() => history.entries.length === 3, 5000, "the list read again");
        }).then(() => {
            compare(lines(calls).filter(call => call === "delete").length, 2, "those forgotten meanwhile went together");
            compare(lines(calls)[lines(calls).length - 1], "list", "read once they were gone");
        });
    }

    function test_theLastCopyWins() {
        const history = make();
        history.copy("1\tone");
        history.copy("2\ttwo");
        history.copy("3\tthree");
        return tryVerify(() => lines(log).some(line => line === "copy three"), 5000, "the last copied").then(() => wait(500)).then(() => {
            const copies = lines(log).filter(line => line.startsWith("copy "));
            compare(copies[copies.length - 1], "copy three", "nothing after it");
        });
    }
}
