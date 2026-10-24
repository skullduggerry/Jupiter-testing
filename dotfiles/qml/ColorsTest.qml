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
