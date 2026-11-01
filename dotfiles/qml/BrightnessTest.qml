import QtQuick
import "../shell/panels"
import "../shell/services"

// The backlight is read every second only while something shows its level
// (Brightness.viewers): a brightness panel counts itself while it is shown,
// once, and stops counting when it goes, shown or not.
TestCase {
    id: root

    readonly property Component panelComponent: Component {
        BrightnessPanel {}
    }

    function test_aPanelCountsWhileShown() {
        // No window to draw in, and no backlight to look for.
        ignoreWarning("not placed in the graphics scene|Process failed to start");
        Brightness.viewers = 0;
        const panel = panelComponent.createObject(root, {
            active: false
        }) as BrightnessPanel;
        compare(Brightness.viewers, 0, "built unseen, as the pagers build every page");
        panel.active = true;
        compare(Brightness.viewers, 1);
        panel.active = true;
        compare(Brightness.viewers, 1, "counted once");
        panel.active = false;
        compare(Brightness.viewers, 0);
        panel.active = true;
        panel.destroy();
        return tryVerify(() => Brightness.viewers === 0, 1000, "a panel destroyed while shown stops counting");
    }
}
