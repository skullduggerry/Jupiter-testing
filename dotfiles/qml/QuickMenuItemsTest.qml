import QtQuick
import "../shell/quickmenu"

// A slot's entry is "kind:id", and a paired device's id is its Bluetooth
// address, which has colons of its own: the whole address is the id, or
// every device slot finds no device and shows as empty. Nothing of the
// session is here, so every service the items read complains once.
TestCase {
    id: root

    readonly property Component itemsComponent: Component {
        QuickMenuItems {}
    }
    property QuickMenuItems items: null

    function setUp() {
        ignoreWarning("DBus|NetworkManager|Network will not work|Bluetooth|PowerProfiles|pipewire|Mpris|UPower|Process failed to start|wl_display|GlobalShortcut|global_shortcuts");
        items = itemsComponent.createObject(root);
    }

    function test_anEntrySplitsAtItsFirstColon() {
        setUp();
        const cases = [["device:AA:BB:CC:DD:EE:FF", "device", "AA:BB:CC:DD:EE:FF"], ["item:wifi", "item", "wifi"], ["category:power", "category", "power"], ["", "", ""]];
        for (const [entry, kind, id] of cases) {
            compare(items.entryKind(entry), kind, `the kind of "${entry}"`);
            compare(items.entryId(entry), id, `the id of "${entry}"`);
        }
    }

    function test_aDeviceThatIsNotPairedIsAnEmptySlot() {
        setUp();
        compare(items.describe("device:AA:BB:CC:DD:EE:FF").kind, "empty");
    }
}
