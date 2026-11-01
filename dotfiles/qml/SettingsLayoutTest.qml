import QtQuick
import QtQuick.Window
import "../shell/services"
import "../shell/settings"

// The Settings app tiled narrower than its minimum size, as Hyprland tiles
// it on a laptop: the page's tabs, the wallpaper tab's rows and its import
// wrap rather than run off the window or onto each other. Opened wide and
// then narrowed, since a layout settles only once it is in a window.
TestCase {
    readonly property Window window: Window {
        width: 1100
        height: 895
        visible: true
    }
    readonly property Component content: Component {
        SettingsContent {
            anchors.fill: parent
        }
    }

    // Every pill shown: a PillButton is the item with both of these.
    function pills(item, found) {
        for (const child of item.children) {
            if (!child.visible)
                continue;
            if (typeof child.checked === "boolean" && typeof child.text === "string" && typeof child.action === "boolean")
                found.push(child);
            pills(child, found);
        }
        return found;
    }

    function test_aNarrowWindowWrapsThePills() {
        ignoreWarning("HYPRLAND_INSTANCE_SIGNATURE is unset");
        SettingsState.page = "wallpaper";
        content.createObject(window.contentItem);
        return wait(300).then(() => {
            window.width = 704;
            return wait(300);
        }).then(() => {
            const shown = pills(window.contentItem, []);
            const boxes = shown.map(pill => {
                const at = pill.mapToItem(window.contentItem, 0, 0);
                return {
                    text: pill.text,
                    left: at.x,
                    top: at.y,
                    right: at.x + pill.width,
                    bottom: at.y + pill.height
                };
            });
            for (const name of ["Lock Screen", "Tile", "Add from file…"])
                verify(boxes.some(box => box.text === name), name + " is shown");
            for (const box of boxes)
                verify(box.right <= window.width, box.text + " ends at " + box.right + ", past the window's " + window.width);
            for (let one = 0; one < boxes.length; one++) {
                for (let other = one + 1; other < boxes.length; other++) {
                    const a = boxes[one];
                    const b = boxes[other];
                    const overlap = a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
                    verify(!overlap, a.text + " and " + b.text + " overlap");
                }
            }
        });
    }
}
