import QtQuick
import "../shell/style"

// The blur variants the Settings app offers (style/BlurVariants), and the
// choices Theme keeps of them in appearance.json.
TestCase {
    // Hyprland 0.57's decoration:blur:variant map, as `hyprctl descriptions`
    // gives it: a variant offered under another number would show another.
    function test_hyprlandsVariantsByNumber() {
        const hyprland = {
            kawase: 0,
            frost: 1,
            ripple: 2,
            drops: 3,
            water: 4,
            fluid_jar: 5,
            prism: 6,
            heat_shimmer: 7,
            acrylic: 8,
            aurora: 9,
            haze: 10
        };
        compare(BlurVariants.variants.length, Object.keys(hyprland).length);
        for (let index = 0; index < BlurVariants.variants.length; index++) {
            const variant = BlurVariants.variants[index];
            compare(variant.value, hyprland[variant.name], variant.name);
        }
    }

    function test_anUnknownNameIsKawase() {
        compare(BlurVariants.find("acrylic").value, 8);
        compare(BlurVariants.find("glass").name, "kawase", "a variant this Hyprland lacks");
    }

    // A default outside its slider would put the knob off the track.
    function test_defaultsWithinTheirRange() {
        for (let index = 0; index < BlurVariants.variants.length; index++) {
            const options = BlurVariants.variants[index].options;
            for (let option = 0; option < options.length; option++) {
                const spec = options[option];
                verify(spec.least <= spec.fallback && spec.fallback <= spec.most, spec.key);
                verify(spec.step > 0 && spec.step <= spec.most - spec.least, spec.key);
            }
        }
    }

    // Every option is written, picked or not, so a value set back to its
    // default reaches the running Hyprland too.
    function test_effectiveFillsInDefaults() {
        const values = BlurVariants.effective({
            "acrylic.clarity": 0.9
        });
        compare(values["acrylic.clarity"], 0.9);
        compare(values["acrylic.bulb"], 48);
        compare(values["glass.size"], 40, "the glass relief several variants share");
        compare(BlurVariants.effective(undefined)["acrylic.clarity"], 0.35);
    }

    // A value kept from a wider range (acrylic's refraction went up to 48)
    // reaches Hyprland held to the one offered now.
    function test_effectiveHoldsKeptValuesToTheirRange() {
        const values = BlurVariants.effective({
            "acrylic.refraction": 45,
            "acrylic.bulb": 1
        });
        compare(values["acrylic.refraction"], 12);
        compare(values["acrylic.bulb"], 4);
    }

    function test_optionsPickedAndReset() {
        Theme.setBlurVariant("prism");
        compare(Theme.blurVariant, "prism");
        Theme.setBlurOption("glass.refraction", 4);
        Theme.setBlurOption("glass.size", 80);
        Theme.setBlurOption("haze.intensity", 0.5);
        compare(Theme.blurOptions["glass.size"], 80);
        Theme.resetBlurOptions(["glass.refraction", "glass.size", "glass.roughness"]);
        compare(Object.keys(Theme.blurOptions), ["haze.intensity"], "another variant's option is kept");
        // Theme writes appearance.json once the choices settle.
        return wait(300);
    }
}
