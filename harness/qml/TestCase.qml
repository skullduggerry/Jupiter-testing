import QtQuick

// The base of every *Test.qml: shell.qml calls each of its functions named
// test_*, in order. A test fails by throwing, which the checks below do, and
// may return a Promise (wait(), tryVerify()) to finish once the event loop
// has run, e.g. after a FileView has loaded. Any warning fails it too, unless
// ignoreWarning() expected it.
QtObject {
    id: root

    readonly property Component delay: Component {
        Timer {}
    }

    function verify(condition, message) {
        if (!condition)
            throw new Error(message || "verify failed");
    }

    // Colours and lists compare by their text, so a colour equals "#61afef".
    function compare(actual, expected, message) {
        const same = actual === expected || (typeof actual === "object" && actual !== null && String(actual) === String(expected));
        if (!same)
            throw new Error(`${message || "compare"}: got ${actual}, expected ${expected}`);
    }

    function fuzzyCompare(actual, expected, delta, message) {
        if (!(Math.abs(actual - expected) <= delta))
            throw new Error(`${message || "fuzzyCompare"}: got ${actual}, expected ${expected} ± ${delta}`);
    }

    // Lets warnings matching pattern (a regular expression) through from now
    // on, such as a service's complaint that there is no Hyprland here.
    function ignoreWarning(pattern: string) {
        console.info("IGNORE", pattern);
    }

    function wait(ms) {
        return new Promise(resolve => {
            const timer = root.delay.createObject(root, {
                interval: ms
            });
            timer.triggered.connect(() => {
                timer.destroy();
                resolve();
            });
            timer.start();
        });
    }

    // tryVerify waits on what must happen, so a longer wait costs a passing
    // test nothing: never less than this, as a CI runner with every core busy
    // took more than a test's 2 s for a Process and a debounce.
    readonly property int tryVerifyFloor: 10000

    // Resolves once condition() holds, checking every 10 ms for up to timeout
    // ms, and at least tryVerifyFloor.
    function tryVerify(condition, timeout, message) {
        const deadline = Date.now() + Math.max(timeout || 1000, root.tryVerifyFloor);
        const poll = () => {
            if (condition())
                return Promise.resolve();
            if (Date.now() > deadline)
                return Promise.reject(new Error(message || "tryVerify timed out"));
            return root.wait(10).then(poll);
        };
        return poll();
    }
}
