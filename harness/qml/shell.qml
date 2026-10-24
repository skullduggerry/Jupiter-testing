import QtQuick
import Quickshell

// Runs one test file, the one in QML_TEST, for harness/qml.py: a PASS or
// FAIL line per test_ function, then DONE. Quickshell has no way to quit
// from QML, so the script stops it after DONE.
ShellRoot {
    id: root

    // Where in the test file an error was thrown: its stack's frame there.
    function place(error, file: string): string {
        const frame = String(error.stack || "").split("\n").find(line => line.includes(file));
        return frame ? " (" + frame.slice(frame.lastIndexOf("/") + 1) + ")" : "";
    }

    Component.onCompleted: {
        const file = Quickshell.env("QML_TEST");
        const component = Qt.createComponent(file);
        if (component.status !== Component.Ready) {
            console.info("FAIL", component.errorString());
            console.info("DONE");
            return;
        }
        const test = component.createObject(root);
        const names = [];
        for (const name in test)
            if (name.startsWith("test_") && typeof test[name] === "function")
                names.push(name);
        if (names.length === 0)
            console.info("FAIL no test_ functions in", file);

        const fileName = file.slice(file.lastIndexOf("/") + 1);
        let done = Promise.resolve();
        for (const name of names)
            done = done.then(() => test[name]()).then(() => console.info("PASS", name), error => console.info("FAIL", `${name}: ${error.message}${root.place(error, fileName)}`));
        done.then(() => console.info("DONE"));
    }
}
