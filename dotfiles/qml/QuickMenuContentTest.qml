import QtQuick
import "../shell/quickmenu"
import "../shell/services"
import "../shell/style"

// The wheel over a list's slot goes into the list and along its rows, with
// the pointer left on the slot; moving off the slot gives the pointer the
// selection back. A list is a wheel of spokes: the pointer picks the spoke
// it is on, and the wheel over the list turns it under the pointer. Nothing
// of the session is here, so every service the items read complains once.
TestCase {
    id: root

    readonly property Component itemsComponent: Component {
        QuickMenuItems {}
    }
    property QuickMenuItems items: null
    property QuickMenuContent menu: null

    // Where a slot's middle is, in the menu's window.
    function slotPoint(slot: int): point {
        const angle = (slot * menu.step - 90) * Math.PI / 180;
        return Qt.point(menu.center.x + menu.slotRadius * menu.zoom * Math.cos(angle), menu.center.y + menu.slotRadius * menu.zoom * Math.sin(angle));
    }

    // Where a visible row of the list is, in the menu's window: `out` along
    // its spoke from the fan's inner edge.
    function rowPoint(row: int, out: real): point {
        const list = menu.list;
        const angle = list.angleAt(list.pitch * (row + 1.5) - list.offset);
        const radius = Style.quickMenu.arcInner + out;
        return Qt.point(menu.center.x + menu.zoom * list.side * radius * Math.cos(angle), menu.center.y + menu.zoom * radius * Math.sin(angle));
    }

    function setUp() {
        ignoreWarning("DBus|NetworkManager|Network will not work|Bluetooth|PowerProfiles|pipewire|Mpris|UPower|Process failed to start|wl_display|GlobalShortcut|global_shortcuts");
        items = itemsComponent.createObject(root);
        const component = Qt.createComponent("../shell/quickmenu/QuickMenuContent.qml");
        menu = component.createObject(null, {
            items: root.items,
            origin: Qt.point(700, 450),
            width: 1400,
            height: 900
        });
        verify(menu !== null, component.errorString());
    }

    // Along the radius from the hub: letter, glyph, label, so a label is
    // above its glyph on the upper half and under it elsewhere.
    function test_labelsGoAwayFromTheHub() {
        setUp();
        for (const angle of [0, 45, 315, -45])
            verify(menu.labelAbove(angle), `above at ${angle}°`);
        for (const angle of [90, 135, 180, 225, 270])
            verify(!menu.labelAbove(angle), `under at ${angle}°`);
        const top = menu.labelPoint(Qt.point(0, -100), 0);
        verify(top.y < -100, "the top slot's label is further out than its middle");
        const bottom = menu.labelPoint(Qt.point(0, 100), 180);
        verify(bottom.y > 100, "and the bottom slot's too");
        menu.destroy();
    }

    function test_theWheelOverAListsSlotStepsItsRows() {
        setUp();
        const apps = menu.slots.indexOf("item:apps");
        verify(apps >= 0, "the apps have a slot");
        Apps.missing = [];
        const at = slotPoint(apps);
        menu.move(at.x, at.y);
        compare(menu.selectedArea, "ring", "the pointer on the slot");
        return tryVerify(() => menu.list !== null && menu.list.count > 2, 3000, "the apps load").then(() => {
            menu.wheel(-Style.quickMenu.wheelStep);
            compare(menu.selectedArea, "panel", "the first notch goes into the list");
            compare(menu.selectedIndex, 0);
            menu.wheel(-Style.quickMenu.wheelStep * 2);
            compare(menu.selectedIndex, 2, "each notch down a row");
            menu.wheel(Style.quickMenu.wheelStep);
            compare(menu.selectedIndex, 1, "and up");
            menu.move(at.x + 1, at.y + 1);
            compare(menu.selectedArea, "panel", "a nudge on the slot keeps the row");
            const other = slotPoint((apps + menu.count / 2) % menu.count);
            menu.move(other.x, other.y);
            compare(menu.selectedArea, "ring", "another slot takes the selection back");
            menu.destroy();
        });
    }

    // The notifications' slot puts them out in a list, with Clear and Do Not
    // Disturb, rather than only opening the bar's centre.
    function test_theNotificationsAreAList() {
        setUp();
        QuickMenu.setSlot(0, "item:notifications");
        compare(items.kindOf("item:notifications"), "list");
        compare(items.describe("item:notifications").detail, "None");
        NotificationService.doNotDisturb = true;
        compare(items.describe("item:notifications").detail, "None · Do Not Disturb");
        NotificationService.doNotDisturb = false;
        const at = slotPoint(0);
        menu.move(at.x, at.y);
        verify(menu.list instanceof QuickMenuNotifications, "its list is out");
        compare(menu.list.count, 0);
        verify(!menu.list.pick(0), "an empty list has nothing to use");
        menu.destroy();
        QuickMenu.reset();
    }

    function test_aListIsAWheel() {
        setUp();
        const apps = menu.slots.indexOf("item:apps");
        Apps.missing = [];
        const at = slotPoint(apps);
        menu.move(at.x, at.y);
        return tryVerify(() => menu.list !== null && menu.list.count > menu.list.shownRows + 2, 3000, "the apps load").then(() => {
            menu.wheel(-Style.quickMenu.wheelStep);
            const list = menu.list;
            for (const row of [0, 2, list.shownRows - 1]) {
                const point = rowPoint(row, 40);
                menu.move(point.x, point.y);
                compare(menu.selectedArea, "panel", `row ${row}'s spoke is on the list`);
                compare(menu.selectedIndex, row, `and picks it`);
            }
            const middle = rowPoint(Math.floor(list.shownRows / 2), 40);
            menu.move(middle.x, middle.y);
            verify(Math.abs(middle.y - menu.center.y) < list.pitch * menu.zoom / 2, "the middle row is level with the slot");
            const before = menu.selectedIndex;
            menu.wheel(-Style.quickMenu.wheelStep * 2);
            compare(list.offset, list.pitch * 2, "two notches turn it two rows");
            compare(menu.selectedIndex, before + 2, "and the pointer picks what came under it");
            const inside = rowPoint(0, -Style.quickMenu.gap * 4);
            verify(!list.covers((inside.x - menu.center.x) / menu.zoom, (inside.y - menu.center.y) / menu.zoom), "the ring is not the list");
            list.show(0);
            compare(list.offset, 0, "the first row shows from the top");
            menu.destroy();
        });
    }
}
