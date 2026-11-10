import QtQuick
import QtQuick.Window
import "../shell/panels"
import "../shell/style"

// The finish of acrylic's glass (panels/GlassHighlight, "Wallpaper" in
// PROJECT_STRUCTURE.md): where Hyprland's lens cannot frame a panel, the rim
// is drawn, and it runs under the panel's content, so it must read as one
// slope into the clear middle. A band that shows as a step, or a line where
// the rim ends, crosses the text over it.
TestCase {
    readonly property Window window: Window {
        width: 500
        height: 400
        visible: true
    }
    readonly property Component pane: Component {
        Item {
            width: 320
            height: 300
        }
    }
    readonly property Component finish: Component {
        GlassHighlight {}
    }

    // The alpha of each band drawn, from the edge in: the outlines in the
    // rim's colour, which the light on the upper edge is not.
    function bands(highlight: GlassHighlight): var {
        const found = [];
        for (const child of highlight.children) {
            if (child.border && child.border.width > 0 && child.border.color.a > 0 && Qt.colorEqual(Colors.withAlpha(child.border.color, 1), Colors.withAlpha(Colors.base.lensBand, 1)))
                found.push({
                    inset: child.x,
                    alpha: child.border.color.a
                });
        }
        return found.sort((first, second) => first.inset - second.inset);
    }

    // The finish of a pane of acrylic, as PopupFrame gives its glass one.
    function acrylic(properties): GlassHighlight {
        Theme.setBlur(true);
        Theme.setBlurVariant("acrylic");
        return finish.createObject(pane.createObject(window.contentItem, properties || {})) as GlassHighlight;
    }

    function test_theRimIsOneSlope() {
        const highlight = acrylic();
        verify(highlight.visible);
        compare(highlight.rim, 48, "as wide as acrylic's bulb");
        const drawn = bands(highlight);
        compare(drawn.length, highlight.bands);
        fuzzyCompare(drawn[0].alpha, Colors.base.lensBand.a, 0.001, "thickest at the edge");
        for (let index = 1; index < drawn.length; index++) {
            verify(drawn[index].alpha <= drawn[index - 1].alpha, `band ${index} is no thicker than the one outside it`);
            verify(drawn[index - 1].alpha - drawn[index].alpha < 0.04, `band ${index} shows as a step: ${drawn[index - 1].alpha} to ${drawn[index].alpha}`);
        }
        verify(drawn[drawn.length - 1].alpha < 0.01, `the rim ends on a line: ${drawn[drawn.length - 1].alpha}`);
        verify(drawn[drawn.length - 1].inset < highlight.rim, "and inside its width");
        for (const child of highlight.children)
            verify(!(child.border && child.border.width > 0 && child.x >= highlight.rim), "nothing is outlined where the rim ends");
    }

    // Hyprland bounds its lens by the glass's smaller side; so is this one.
    function test_aSmallGlassHasANarrowerRim() {
        const highlight = acrylic({
            width: 200,
            height: 42
        });
        fuzzyCompare(highlight.rim, (42 - 2 * Style.border.width) * Style.blur.rimShare, 0.001);
        compare(bands(highlight).length, highlight.bands);
        verify(highlight.bands >= 2);
    }

    // The bar, a lone toast: Hyprland's own lens frames them.
    function test_noRimWhereHyprlandDrawsTheLens() {
        const highlight = acrylic();
        highlight.lensed = true;
        compare(bands(highlight).length, 0);
        verify(highlight.visible, "the light on the upper edge stays");
    }

    function test_nothingOnOtherVariants() {
        const highlight = acrylic();
        Theme.setBlurVariant("frost");
        verify(!highlight.visible);
        Theme.setBlurVariant("acrylic");
        Theme.setBlur(false);
        verify(!highlight.visible, "nor on a Solid surface");
        Theme.setBlur(true);
        Theme.setBlurVariant("kawase");
        return wait(300);
    }
}
