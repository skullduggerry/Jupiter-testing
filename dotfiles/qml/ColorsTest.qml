import QtQuick
import "../shell/style"

// Colors' formulas over the palette (PROJECT_STRUCTURE.md, "Themes"): the
// palette is set here directly, as a rendered theme would set it.
TestCase {
    function usePalette(background: string, foreground: string, slots) {
        for (let index = 0; index < 16; index++)
            Theme.palette["color" + index] = slots[index] ?? "";
        Theme.palette.background = background;
        Theme.palette.foreground = foreground;
    }

    function test_withoutPaletteTheDesignColours() {
        compare(Colors.palette.background, "#0f0f0f");
        compare(Colors.palette.blue, "#61afef");
        compare(Colors.palette.orange, "#d19a66");
        verify(!Colors.light);
    }

    function test_contrastIsWcags() {
        fuzzyCompare(Colors.contrast("black", "white"), 21, 0.01);
        fuzzyCompare(Colors.contrast("#61afef", "#61afef"), 1, 0.001);
        fuzzyCompare(Colors.contrast("white", "black"), Colors.contrast("black", "white"), 0.001);
    }

    // A slot stands in for its colour only when saturated and off the
    // background; a generated palette of greys keeps the shell's own.
    function test_onlyDistinctSlotsAreTrusted() {
        usePalette("#101010", "#e0e0e0", {
            1: "#ff3030",
            4: "#808080",
            5: "#141018"
        });
        compare(Colors.palette.red, "#ff3030", "saturated and off the background");
        compare(Colors.palette.blue, "#61afef", "grey");
        compare(Colors.palette.purple, "#c678dd", "too close to the background");
    }

    function test_orangeIsBetweenRedAndYellow() {
        usePalette("#101010", "#e0e0e0", {
            1: "#ff0000",
            3: "#ffff00"
        });
        compare(Colors.palette.orange, Colors.mix("#ff0000", "#ffff00", 0.5));
        usePalette("#101010", "#e0e0e0", {
            1: "#ff0000"
        });
        compare(Colors.palette.orange, "#d19a66", "no yellow to mix with");
    }

    function test_lightFollowsTheBackground() {
        usePalette("#fafafa", "#202020", {});
        verify(Colors.light);
        usePalette("#202020", "#fafafa", {});
        verify(!Colors.light);
    }

    // Adaptive glass: as little opacity as lets muted text read over the
    // backdrop, from the floor to the ceiling.
    function test_glassOverABackdrop() {
        usePalette("#101010", "#e0e0e0", {});
        compare(Colors.glassOver("transparent"), Colors.base.glassFloor, "nothing measured yet");
        const dark = Colors.glassOver("#000000");
        const bright = Colors.glassOver("#ffffff");
        verify(dark <= bright, "a bright backdrop under light text needs more");
        verify(bright <= Colors.base.glassCeiling && dark >= Colors.base.glassFloor);
    }

    // The quick menu's wheel fades its rows toward the surface only as far
    // as they still read at AA over it; a theme whose text only just does
    // gets no fading at all.
    function test_fadedTextStillReads() {
        usePalette("#101010", "#e0e0e0", {});
        compare(Colors.faded("#e0e0e0", 0), Colors.mix("#101010", "#e0e0e0", 1), "unfaded");
        const far = Colors.faded("#e0e0e0", 1);
        verify(Colors.contrast(far, "#101010") >= Colors.readableContrast, `${far} reads`);
        verify(Colors.contrast(far, "#101010") < Colors.contrast("#e0e0e0", "#101010"), "and is fainter");
        usePalette("#101010", "#707070", {});
        compare(Colors.fadeFloor, 1, "soft text keeps its colour");
    }

    // The variant's material (BlurVariants, "Wallpaper"): acrylic's own rim
    // takes the place of the flat border, with the light on its upper edge;
    // the tint goes as light as liquid glass wants, over any variant.
    function test_materialFollowsTheVariant() {
        usePalette("#101010", "#e0e0e0", {});
        Theme.setBlur(true);
        Theme.setBlurVariant("kawase");
        verify(!Colors.base.clear && !Colors.base.specular);
        compare(Colors.tintLeast, 0.1);
        compare(Colors.base.edge, Colors.base.border);
        compare(Colors.base.highlight, Qt.rgba(0, 0, 0, 0));
        Theme.setBlurVariant("acrylic");
        verify(Colors.base.clear && Colors.base.specular);
        compare(Colors.tintLeast, 0.1, "no floor of its own");
        verify(Colors.base.edge !== Colors.base.border);
        verify(Colors.base.highlight.a > 0);
        Theme.setBlurVariant("prism");
        verify(Colors.base.clear && !Colors.base.specular, "clear, with a flat border");
        Theme.setBlur(false);
        verify(!Colors.base.clear, "Solid has no material");
        Theme.setBlurVariant("kawase");
        return wait(300);
    }

    // Hyprland's colour options take rgba(rrggbbaa).
    function test_coloursAsHyprlandTakesThem() {
        compare(Colors.hyprland(Qt.rgba(1, 0, 0, 0.5)), "rgba(ff000080)");
        compare(Colors.hyprland("#33b1ff"), "rgba(33b1ffff)");
    }

    // The lock and login screens (the Lock Screen tab's Theme): the desktop's
    // theme over a veil of its background, its glass with Blur on; or light
    // on dark over the wallpaper, as the overlay is.
    function test_lockFollowsTheTheme() {
        usePalette("#fafafa", "#202020", {});
        LockLook.set("followTheme", true);
        compare(Colors.lock.text, Colors.text.base);
        compare(Colors.lock.background, "#fafafa");
        compare(Colors.lock.scrim, Colors.withAlpha("#fafafa", LockLook.dim));
        compare(Colors.lock.field, Colors.base.surface);
        compare(LockLook.glass, Theme.blur);
        LockLook.set("followTheme", false);
        compare(Colors.lock.text, Colors.overlay.text);
        compare(Colors.lock.scrim, Qt.rgba(0, 0, 0, LockLook.dim));
        verify(!LockLook.glass, "glass only where the theme is followed");
        // LockLook writes its file once the choices settle.
        return wait(300);
    }
}
