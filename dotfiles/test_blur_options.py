"""The blur the Settings app keeps, as the installed Hyprland takes it.

style/BlurVariants.qml lists Hyprland's blur variants by number and the
sub-options each reads, with a default and the range its slider offers;
services/HyprBlur.qml writes every one of them to blur.lua, which
.config/hypr/styles/layout.lua applies at each start. Hyprland refuses a key
it does not know and a value outside its own range (a red banner at login),
so each bound and default offered goes through its parser here
(`Hyprland --verify-config`, on layout.lua itself with a blur.lua as
HyprBlur writes it): a release that renames an option or narrows a range
fails this, not a login.

Nothing but the parser runs: no compositor is started.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest

from harness import DOTFILES, QUICKSHELL, temporary

VARIANTS = QUICKSHELL / "style/BlurVariants.qml"
STYLE = QUICKSHELL / "style/Style.qml"
HYPRLAND = shutil.which("Hyprland")
NUMBER = r"(-?[0-9.]+)"
# The colours HyprBlur adds, as style/Colors.qml's hyprland() spells one.
COLOURS = {
    "acrylic.tint": "rgba(ffffff26)",
    "aurora.color1": "rgba(33b1ffff)",
    "aurora.color2": "rgba(ff7eb6ff)",
    "fluid_jar.color": "rgba(33b1ffcc)",
}


def options() -> dict[str, dict[str, float]]:
    """Each sub-option's fallback, least and most, by Hyprland's key."""
    text = VARIANTS.read_text()
    found: dict[str, dict[str, float]] = {}
    blocks = re.split(r'\bkey: "', text)[1:]
    for block in blocks:
        key = block[: block.index('"')]
        values = {}
        for name in ("fallback", "least", "most"):
            match = re.search(rf"\b{name}: {NUMBER},?\n", block)
            assert match, f"{key} has no {name}"
            values[name] = float(match.group(1))
        found[key] = values
    return found


def variants() -> dict[str, int]:
    """Each variant's number, by name."""
    text = VARIANTS.read_text()
    return {
        name: int(value)
        for name, value in re.findall(
            r'name: "(\w+)",\n\s*value: ([0-9]+),', text
        )
    }


def sizes() -> tuple[int, int]:
    """The least and the most blur size the Settings app offers."""
    block = STYLE.read_text().split("component BlurStyle", 1)[1]
    least = re.search(r"property int least: ([0-9]+)", block)
    most = re.search(r"property int most: ([0-9]+)", block)
    assert least and most, "Style.blur has a least and a most"
    return int(least.group(1)), int(most.group(1))


def table(variant: int, size: int, values: dict[str, float | str]) -> str:
    """A blur table as services/HyprBlur.qml's table() writes it."""
    groups: dict[str, list[str]] = {}
    for key in sorted(values):
        group, name = key.split(".")
        value = values[key]
        text = f'"{value}"' if isinstance(value, str) else f"{value:g}"
        groups.setdefault(group, []).append(f"{name} = {text}")
    parts = [f"variant = {variant}", f"size = {size}"]
    parts += [
        f"{group} = {{ {', '.join(groups[group])} }}"
        for group in sorted(groups)
    ]
    return "{ " + ", ".join(parts) + " }"


@unittest.skipUnless(HYPRLAND, "needs Hyprland")
class BlurOptions(unittest.TestCase):
    def verify(self, blur: str) -> str:
        """What Hyprland's parser says of layout.lua with this blur kept."""
        tmp = temporary(self)
        (tmp / "state/quickshell").mkdir(parents=True)
        (tmp / "state/quickshell/blur.lua").write_text(f"return {blur}\n")
        (tmp / "runtime").mkdir(mode=0o700)
        config = tmp / "hyprland.lua"
        modules = DOTFILES / ".config/hypr"
        config.write_text(
            f'package.path = "{modules}/?.lua;" .. package.path\n'
            'require("styles.layout")\n'
        )
        assert HYPRLAND is not None
        result = subprocess.run(
            [HYPRLAND, "--verify-config", "-c", str(config)],
            env={
                "PATH": "/usr/bin",
                "HOME": str(tmp),
                "XDG_STATE_HOME": str(tmp / "state"),
                "XDG_RUNTIME_DIR": str(tmp / "runtime"),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        return (
            (result.stdout + result.stderr)
            .split("Config parsing result:", 1)[-1]
            .strip()
        )

    def test_the_file_lists_what_is_looked_for(self) -> None:
        self.assertEqual(
            len(options()),
            VARIANTS.read_text().count('key: "'),
            "an option written another way",
        )
        self.assertGreaterEqual(len(options()), 25)
        self.assertEqual(variants()["kawase"], 0)
        self.assertEqual(len(variants()), 11)

    def test_hyprland_takes_every_default_and_bound(self) -> None:
        least, most = sizes()
        for bound, size in (
            ("fallback", least),
            ("least", least),
            ("most", most),
        ):
            with self.subTest(bound=bound):
                values: dict[str, float | str] = {
                    key: spec[bound] for key, spec in options().items()
                }
                values.update(COLOURS)
                self.assertEqual(
                    self.verify(table(0, size, values)),
                    "config ok",
                    f"every option at its {bound}",
                )

    def test_hyprland_has_every_variant(self) -> None:
        for name, value in variants().items():
            with self.subTest(variant=name):
                self.assertEqual(
                    self.verify(table(value, 6, {})), "config ok", name
                )

    def test_a_refused_option_would_be_named(self) -> None:
        """The check itself: Hyprland's parser does refuse what is wrong."""
        for blur, named in (
            (table(0, 6, {"acrylic.clarity": 7}), "acrylic.clarity"),
            (table(0, 6, {"acrylic.thickness": 1}), "acrylic.thickness"),
            (table(11, 6, {}), "decoration.blur.variant"),
            (table(0, 6, {"acrylic.tint": "ffffff"}), "acrylic.tint"),
        ):
            with self.subTest(blur=blur):
                self.assertIn(named, self.verify(blur))


if __name__ == "__main__":
    unittest.main()
