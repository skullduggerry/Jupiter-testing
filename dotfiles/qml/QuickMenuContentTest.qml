import QtQuick
import "../shell/quickmenu"
import "../shell/services"
import "../shell/style"

// The wheel over a list's slot goes into the list and along its rows, with
// the pointer left on the slot; moving off the slot gives the pointer the
// selection back. Nothing of the session is here, so every service the
// items read complains once.
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
}
