import QtQuick
import "../shell/style"

// Colors' formulas over the palette (the dotfiles' CLAUDE.md, "Theming"): the
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

    // Muted text over glass: as designed where it reads there, and toward
    // the text colour as far as it takes where the tint may not rise for it
    // (Static over a bright wallpaper), where raising it would not be seen
    // (Solid), or where nothing was measured.
    function test_mutedTextReadsOverThinGlass() {
        usePalette("#101010", "#e0e0e0", {});
        Theme.setBlur(true);
        Theme.setAdaptiveTint(false);
        Theme.setTint(false, 0.3);
        const designed = Colors.mix("#101010", "#e0e0e0", Colors.mutedShare);
        compare(Colors.text.muted, designed, "no wallpaper measured yet");
        Theme.setBackdrop("DP-1", "#101418", "#000000");
        compare(Colors.text.muted, designed, "a dark wallpaper under light text");
        Theme.setBackdrop("DP-1", "#f4f4f4", "#000000");
        const behind = Colors.mix("#f4f4f4", "#101010", Colors.base.opacity);
        verify(Colors.contrast(Colors.text.muted, behind) > Colors.contrast(designed, behind), `${Colors.text.muted} reads better than ${designed} over ${behind}`);
        compare(Colors.text.muted, Colors.text.base, "all the way, where even that falls short");
        compare(Colors.base.opacity, 0.3, "and the tint stays where Static keeps it");
        Theme.setTint(false, 0.6);
        Theme.setBackdrop("DP-1", "#909090", "#000000");
        const share = Colors.mutedOver("#909090");
        verify(share > Colors.mutedShare && share < 1, `only as far as it takes: ${share}`);
        verify(Colors.contrast(Colors.text.muted, Colors.mix("#909090", "#101010", 0.6)) >= Colors.mutedTarget());
        verify(Colors.contrast(designed, Colors.mix("#909090", "#101010", 0.6)) < Colors.mutedTarget(), "which the designed one would not");
        Theme.setBlur(false);
        compare(Colors.text.muted, designed, "a Solid surface hides the wallpaper");
        Theme.setBlur(true);
        Theme.clearBackdrop("DP-1");
        Theme.setAdaptiveTint(true);
        return wait(300);
    }

    // Adaptive raises the tint for muted text as it is designed, not as it
    // was raised for the tint before: the two would chase each other.
    function test_adaptiveGlassGoesByTheDesignedMutedText() {
        usePalette("#101010", "#e0e0e0", {});
        Theme.setBlur(true);
        Theme.setAdaptiveTint(true);
        Theme.setTint(false, 0.3);
        Theme.setBackdrop("DP-1", "#808080", "#000000");
        const designed = Colors.mix("#101010", "#e0e0e0", Colors.mutedShare);
        const opacity = Colors.base.opacity;
        verify(opacity > 0.3 && opacity < Colors.base.glassCeiling, `raised, short of the ceiling: ${opacity}`);
        compare(Colors.text.muted, designed, "the tint did the work");
        Theme.clearBackdrop("DP-1");
        return wait(300);
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
        compare(Colors.base.glassTint, Colors.withAlpha("#e0e0e0", Colors.glassAbsorption), "a lit rim, not a smoked one");
        usePalette("#fafafa", "#202020", {});
        compare(Colors.base.glassTint, Colors.withAlpha("#fafafa", Colors.glassAbsorption), "the lighter colour in light themes");
        Theme.setBlurVariant("prism");
        verify(Colors.base.clear && !Colors.base.specular, "clear, with a flat border");
        Theme.setBlurVariant("aurora");
        compare(Colors.base.variant.value, 9);
        Theme.setBlur(false);
        verify(!Colors.base.clear, "Solid has no material");
        compare(Colors.base.variant.value, 0, "and Hyprland is on Kawase: nothing animated behind a surface that shows none of it");
        compare(Theme.blurVariant, "aurora", "the pick is kept for Blur");
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
