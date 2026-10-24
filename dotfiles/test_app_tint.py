"""The apps' glass: services/app-tint.sh against a made-up home, and
appearance.py reading back what it recorded.

The script records the tint for kitty and writes it into the elements of
Kvantum's SVG that the template marks as glass (the windows' and dialogs'
backgrounds), leaving every other line alone. The SVG here is made of the
template's own lines, its expressions filled in. appearance.py renders the
same value from the record when a theme is applied, so a theme render and the
script never disagree. The runtime folder has no kitty sockets in it, so no
kitty is contacted.

The GTK stylesheets get it in the lines their templates mark glass, and the
GTK theme is named anew (.config/wallust/gtk-theme.sh) only while it is the
one named. GSettings is a keyfile in the made-up home, never the real dconf.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import unittest

from harness import DOTFILES, QUICKSHELL, temporary

SCRIPT = QUICKSHELL / "services/app-tint.sh"
APPEARANCE = DOTFILES / ".config/wallust/appearance.py"
TEMPLATES = DOTFILES / ".config/wallust/templates"


def macros(text: str) -> dict[str, str]:
    found = {}
    for line in text.splitlines():
        match = re.fullmatch(
            r"\{%- macro (\w+)\(\) -%\}(.*)\{%- endmacro -%\}", line
        )
        if match:
            found[match.group(1)] = match.group(2)
    return found


def glass(text: str) -> list[str]:
    return re.findall(r'class="tint"[^>]*?opacity:([0-9.]+)', text)


def gtk_glass(text: str) -> list[str]:
    return re.findall(
        r"alpha\(#[0-9A-Fa-f]{6}, ([0-9.]+)\); /\* glass \*/", text
    )


def gtk_sheet(name: str) -> tuple[str, int]:
    """A stylesheet made of a template's lines marked glass and a neighbour
    that has an alpha of its own, its expressions filled in."""
    lines = (TEMPLATES / name).read_text().splitlines()
    marked = [line for line in lines if "/* glass */" in line]
    other = [
        line
        for line in lines
        if "alpha(" in line and "/* glass */" not in line
    ][:1]
    text = "\n".join(marked + other).replace("{{ window_opacity() }}", "0.60")
    return re.sub(r"\{\{[^}]*\}\}", "#161616", text) + "\n", len(marked)


class Templates(unittest.TestCase):
    def test_what_the_templates_mark_as_glass(self) -> None:
        template = (TEMPLATES / "Wallust.svg").read_text().splitlines()
        marked = [line for line in template if 'class="tint"' in line]
        self.assertEqual(len(marked), 4, "2 windows, 2 dialogs")
        self.assertEqual(gtk_sheet("gtk.css")[1], 1)
        self.assertEqual(gtk_sheet("gtk-3.0.css")[1], 1)


@unittest.skipUnless(shutil.which("gsettings"), "needs gsettings")
class Tint(unittest.TestCase):
    def setUp(self) -> None:
        template = (TEMPLATES / "Wallust.svg").read_text().splitlines()
        marked = [line for line in template if 'class="tint"' in line]
        # Glass and two unmarked neighbours with an opacity of their own.
        others = [
            line
            for line in template
            if "opacity:" in line and 'class="tint"' not in line
        ][:2]
        svg = "\n".join(marked + others)
        svg = svg.replace("{{ window_opacity() }}", "0.60")
        self.svg = re.sub(r"\{\{[^}]*\}\}", "#161616", svg) + "\n"
        # The GTK 3 theme has gtk.css's glass (windows) and its own (title
        # bars).
        self.gtk4 = gtk_sheet("gtk.css")[0]
        self.gtk3 = gtk_sheet("gtk-3.0.css")[0] + self.gtk4

        root = temporary(self)
        home = root / "home"
        self.state = root / "state/quickshell"
        runtime = root / "runtime"
        self.kvantum = home / ".config/Kvantum/Wallust/Wallust.svg"
        self.kvantum.parent.mkdir(parents=True)
        runtime.mkdir()
        self.kvantum.write_text(self.svg)
        self.themes = home / ".local/share/themes"
        self.gtk3_theme = self.themes / "Wallust/gtk-3.0/gtk.css"
        self.gtk4_sheet = home / ".config/gtk-4.0/gtk.css"
        for path, text in (
            (self.gtk3_theme, self.gtk3),
            (self.gtk4_sheet, self.gtk4),
        ):
            path.parent.mkdir(parents=True)
            path.write_text(text)
        self.env = dict(
            os.environ,
            HOME=str(home),
            XDG_STATE_HOME=str(root / "state"),
            XDG_RUNTIME_DIR=str(runtime),
            XDG_CONFIG_HOME=str(root / "config"),
            GSETTINGS_BACKEND="keyfile",
        )
        self.name_theme("Wallust")

    def name_theme(self, name: str) -> None:
        result = subprocess.run(
            [
                "gsettings",
                "set",
                "org.gnome.desktop.interface",
                "gtk-theme",
                name,
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def gtk_theme(self) -> str:
        return subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

    def rendered(self) -> str | None:
        result = subprocess.run(
            [
                sys.executable,
                str(APPEARANCE),
                str(self.state / "appearance.json"),
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return macros(result.stdout).get("window_opacity")

    def tint(self, value: str) -> None:
        result = subprocess.run(
            [str(SCRIPT), value],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nothing_recorded_renders_the_committed_default(self) -> None:
        committed = macros((TEMPLATES / "appearance.jinja").read_text())
        self.assertEqual(self.rendered(), committed.get("window_opacity"))

    def test_every_run_writes_the_glass_and_names_the_theme_anew(self) -> None:
        for value, named in (
            ("0.38", "'Wallust-2'"),
            ("1.00", "'Wallust'"),
            ("0.25", "'Wallust-2'"),
        ):
            with self.subTest(tint=value):
                self.tint(value)
                record = (self.state / "tint.conf").read_text()
                self.assertIn(f"\nbackground_opacity {value}\n", record)
                self.assertFalse(
                    (self.state / "tint.conf.new").exists(),
                    "the record's temporary file was left behind",
                )
                text = self.kvantum.read_text()
                self.assertEqual(glass(text), [value] * 4)
                self.assertEqual(
                    text.splitlines()[4:],
                    self.svg.splitlines()[4:],
                    "an element not marked as glass changed",
                )
                self.assertEqual(self.rendered(), value)
                for path, sheet in (
                    (self.gtk3_theme, self.gtk3),
                    (self.gtk4_sheet, self.gtk4),
                ):
                    text = path.read_text()
                    self.assertEqual(
                        gtk_glass(text), [value] * len(gtk_glass(sheet))
                    )
                    self.assertEqual(
                        text.splitlines()[-1],
                        sheet.splitlines()[-1],
                        f"a line of {path.name} not marked as glass changed",
                    )
                self.assertEqual(self.gtk_theme(), named)
        self.assertEqual(
            (self.themes / "Wallust-2").resolve(),
            (self.themes / "Wallust").resolve(),
            "Wallust-2 is a link to the theme",
        )

    def test_a_theme_named_by_hand_is_left(self) -> None:
        self.name_theme("Adwaita")
        self.tint("0.50")
        self.assertEqual(self.gtk_theme(), "'Adwaita'")


if __name__ == "__main__":
    unittest.main()
