"""Every wallust template renders, for a dark theme and a light one, and
kdeglobals.py merges without losing what KDE apps wrote.

wallust only warns when a template fails to render and still exits 0, so a
broken template would otherwise go unnoticed until the colours were wrong.
Rendered into a temporary directory with -s, so no terminal is touched. The
GTK stylesheets go through GTK's own parsers (PyGObject, which blueman
brings), which skip what they cannot read with no more than a warning in the
app.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tomllib
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from harness import DOTFILES, load, temporary

WALLUST_DIR = DOTFILES / ".config/wallust"
kdeglobals = load(WALLUST_DIR / "kdeglobals.py")
WALLUST = shutil.which(
    "wallust",
    path=os.environ.get("PATH", "")
    + os.pathsep
    + str(Path.home() / ".cargo/bin"),
)
GTK_PARSE = """
import sys, gi
gi.require_version("Gtk", sys.argv[1])
from gi.repository import Gtk
errors = []
provider = Gtk.CssProvider()
provider.connect("parsing-error", lambda p, section, error: errors.append(error.message))
text = sys.stdin.read()
try:
    if hasattr(provider, "load_from_string"):
        provider.load_from_string(text)
    else:
        provider.load_from_data(text.encode())
except Exception:
    pass
print("\\n".join(errors))
"""


def gtk_errors(version: str, text: str) -> list[str] | None:
    """What GTK's parser reports for a stylesheet; None without PyGObject or
    that GTK. No display is needed to parse."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("WAYLAND_DISPLAY", "DISPLAY")
    }
    result = subprocess.run(
        [sys.executable, "-c", GTK_PARSE, version],
        input=text,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def groups(path: Path) -> dict[str, dict[str, str]]:
    return {
        name: kdeglobals.entries(lines)
        for name, lines in kdeglobals.read_groups(path)
        if name
    }


@unittest.skipUnless(WALLUST, "needs wallust")
class Templates(unittest.TestCase):
    def render(
        self, theme: str, root: Path, appearance: str | None = None
    ) -> dict[str, Path]:
        config = root / theme
        shutil.copytree(WALLUST_DIR / "templates", config / "templates")
        if appearance is not None:
            (config / "templates/appearance.jinja").write_text(appearance)
        templates = tomllib.loads((WALLUST_DIR / "wallust.toml").read_text())[
            "templates"
        ]
        lines = ["[templates]"]
        for name, entry in templates.items():
            lines.append(
                f"{name} = {{ src = '{entry['src']}', target = '{config / 'out' / name}' }}"
            )
        (config / "wallust.toml").write_text("\n".join(lines) + "\n")
        assert WALLUST is not None
        result = subprocess.run(
            [WALLUST, "-d", str(config), "-q", "-s", "theme", theme],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual((result.returncode, result.stderr.strip()), (0, ""))
        return {name: config / "out" / name for name in templates}

    def test_dark_and_light(self) -> None:
        root = temporary(self)
        for theme, scheme, icons in (
            ("Oxocarbon-Dark", "dark", "breeze-dark"),
            ("Catppuccin-Latte", "light", "breeze"),
        ):
            with self.subTest(theme):
                self.check(theme, scheme, icons, self.render(theme, root))

    def test_a_font_name_is_a_name_not_template(self) -> None:
        # The Settings app offers the system's families: whatever a font
        # calls itself reaches the apps as text, in one field of their lines.
        name = '{{ 7*7 }} {% raw %}, "x"\\'
        appearance = subprocess.run(
            [
                sys.executable,
                str(WALLUST_DIR / "appearance.py"),
                "/nonexistent",
            ],
            env=dict(os.environ, APPEARANCE_FONT=name),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        out = self.render("Oxocarbon-Dark", temporary(self), appearance)
        self.assertIn(
            'general="{{ 7*7 }} {% raw %}   x \\,10,',
            out["qt6ct"].read_text(),
        )

    def check(
        self, theme: str, scheme: str, icons: str, out: dict[str, Path]
    ) -> None:
        for name, path in out.items():
            self.assertTrue(path.exists(), f"{name} was not rendered")
            text = path.read_text()
            self.assertNotIn("{{", text, f"{name} kept template syntax")
            self.assertNotIn("{%", text, f"{name} kept template syntax")
        ElementTree.parse(out["kvantum-svg"])
        # Windows and dialogs at appearance.jinja's default glass.
        self.assertEqual(
            re.findall(
                r'class="tint"[^>]*?opacity:([0-9.]+)',
                out["kvantum-svg"].read_text(),
            ),
            ["0.60"] * 4,
        )
        self.assertEqual(
            out["color-scheme"].read_text().strip(), f"prefer-{scheme}"
        )
        kde = groups(out["kdeglobals"])
        self.assertEqual(kde["Icons"]["Theme"], icons)
        self.assertEqual(kde["UiSettings"]["ColorScheme"], "Wallust")
        for value in kde["Colors:View"].values():
            parts = value.split(",")
            self.assertTrue(
                len(parts) == 3
                and all(p.isdigit() and int(p) <= 255 for p in parts),
                f"[Colors:View] has a value that is not R,G,B: {value}",
            )
        self.assertIn(f"icon_theme={icons}\n", out["qt6ct"].read_text())
        variant = "adw-gtk3" if scheme == "light" else "adw-gtk3-dark"
        for name, version in (("gtk3", "3.0"), ("gtk4-theme", "4.0")):
            self.assertEqual(
                re.findall(
                    r'@import url\("file:///usr/share/themes/([^/]+)/gtk-(\d\.\d)/gtk\.css"\);',
                    out[name].read_text(),
                ),
                [(variant, version)],
            )
        # Windows' glass at appearance.jinja's default, and GTK 3's title bars'.
        for name, count in (("gtk3", 2), ("gtk4", 1)):
            self.assertEqual(
                re.findall(
                    r"alpha\(#[0-9A-Fa-f]{6}, ([0-9.]+)\); /\* glass \*/",
                    out[name].read_text(),
                ),
                ["0.60"] * count,
            )
        # The repo's own CSS, not adw-gtk3's, which may not be installed here.
        for name, version in (("gtk3", "3.0"), ("gtk4", "4.0")):
            errors = gtk_errors(
                version, re.sub(r"(?m)^@import .*$", "", out[name].read_text())
            )
            self.assertFalse(
                errors, f"GTK {version} cannot read {name}: {errors}"
            )


class Merge(unittest.TestCase):
    def test_kdeglobals_keeps_what_apps_wrote(self) -> None:
        root = temporary(self)
        rendered = root / "rendered"
        target = root / "kdeglobals"
        rendered.write_text(
            "[KDE]\nwidgetStyle=kvantum\n\n[Icons]\nTheme=breeze\n\n[Colors:View]\nBackgroundNormal=1,2,3\n"
        )
        target.write_text(
            "# Generated by wallust\n[KDE]\nwidgetStyle[$i]=breeze\nwidgetStyle=kvantum\nSingleClick=true\n\n"
            "[KFileDialog Settings]\nShow hidden files=true\n\n[Colors:View]\nBackgroundNormal=9,9,9\n"
        )
        kdeglobals.merge(rendered, target)
        merged = groups(target)
        self.assertEqual(
            merged["KDE"],
            {
                "widgetStyle[$i]": "breeze",
                "widgetStyle": "kvantum",
                "SingleClick": "true",
            },
            "a key with a suffix is another key",
        )
        self.assertEqual(
            merged["KFileDialog Settings"],
            {"Show hidden files": "true"},
            "an app's own group",
        )
        self.assertEqual(merged["Colors:View"], {"BackgroundNormal": "1,2,3"})
        self.assertEqual(
            merged["Icons"], {"Theme": "breeze"}, "a group the file lacked"
        )
        self.assertNotIn("#", target.read_text(), "a comment survived")
        text = target.read_text()
        kdeglobals.merge(rendered, target)
        self.assertEqual(
            target.read_text(), text, "merging again changes nothing"
        )


if __name__ == "__main__":
    unittest.main()
