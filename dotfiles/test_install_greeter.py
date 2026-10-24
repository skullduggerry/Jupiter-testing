"""Staging test for scripts/install-greeter.sh.

Runs the real script into a temporary destination (a staging install, so
/etc/pam.d is left alone) and checks that the tree greetd would run is
self-contained: the `greeter` user cannot read $HOME, so a symlink left in
it -- etc/greetd/monitors.lua is one in the repo -- would dangle at boot and
take the greeter's compositor config down with it. Monitor rules the
Settings app kept are baked into the copy, applied after the config's own as
in the session, and so are the keyboard layouts it kept, over the system's
(/etc/vconsole.conf). The desktop's theme goes beside the greeter, which its
compositor names, and the Lock Screen choices installed with it record which
theme that was. What it may and may not copy out of the owner's home is
security/test_login_screen.py's.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from harness import DOTFILES, environment, temporary

SCRIPT = DOTFILES / "scripts/install-greeter.sh"
# The smallest files `file` takes for images.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde"
)
PALETTE = '{"background": "#fffbef", "foreground": "#5c6a72"}\n'


class InstallGreeter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)
        # The script takes the wallpaper from the saved hyprpaper config
        # under XDG_STATE_HOME, so the test brings its own instead of yours.
        self.state = self.tmp / "state"
        (self.state / "quickshell").mkdir(parents=True)
        self.wallpaper = self.tmp / "wallpaper.jpg"
        self.wallpaper.write_bytes(JPEG)
        (self.state / "quickshell/hyprpaper.conf").write_text(
            f"wallpaper {{\n    monitor =\n    path = {self.wallpaper}\n}}\n"
        )
        # The desktop's theme: wallust's palette and the shell's Appearance.
        self.cache = self.tmp / "cache"
        (self.cache / "wallust").mkdir(parents=True)
        (self.cache / "wallust/quickshell.json").write_text(PALETTE)
        (self.state / "wallust").mkdir()
        (self.state / "wallust/theme").write_text(
            "Everforest-Light-Hard\nall\n"
        )
        (self.state / "quickshell/appearance.json").write_text(
            json.dumps({"blur": True, "accent": "green", "swoosh": False})
        )
        # As Jupiter-installer writes it for a German console keymap.
        self.vconsole = self.tmp / "vconsole.conf"
        self.vconsole.write_text(
            "KEYMAP=de-latin1\nXKBLAYOUT=de\nXKBMODEL=pc105\n"
            "XKBOPTIONS=terminate:ctrl_alt_bksp\n"
        )

    def install(self, name: str) -> Path:
        dest = self.tmp / name
        run = subprocess.run(
            ["bash", str(SCRIPT), str(dest)],
            capture_output=True,
            text=True,
            env=environment(
                XDG_STATE_HOME=str(self.state), XDG_CACHE_HOME=str(self.cache)
            ),
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.stderr = run.stderr
        return dest

    def lua(self, script: str) -> str:
        result = subprocess.run(
            ["lua", "-e", script],
            capture_output=True,
            text=True,
            env=environment(HOME=None),
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def layouts(self, dest: Path) -> str:
        """The staged compositor config under plain lua, with a stub `hl`
        and vconsole read as /etc/vconsole.conf: the layouts it ends on."""
        return self.lua(
            "local layouts\nhl = { monitor = function() end, on = function() end,\n"
            "  config = function(values) if values.input then layouts = values.input.kb_layout end end }\n"
            "local open = io.open\n"
            f'io.open = function(path, ...) return open(path == "/etc/vconsole.conf" and "{self.vconsole}" or path, ...) end\n'
            f'package.path = "{dest}/?.lua;" .. package.path\n'
            f'dofile("{dest / "hyprland.lua"}")\nprint(layouts)\n'
        )

    def verifies(self, dest: Path) -> None:
        # Hyprland's own parser on the staged copy: `require` resolves inside
        # the staged tree rather than through the repo.
        if not shutil.which("Hyprland"):
            return
        verify = subprocess.run(
            ["Hyprland", "--verify-config", "-c", str(dest / "hyprland.lua")],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (verify.stdout + verify.stderr).strip()
        self.assertIn("config ok", output)

    def test_a_self_contained_tree(self) -> None:
        dest = self.install("greetd")
        links = [
            str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_symlink()
        ]
        self.assertEqual(links, [])
        for name, own in (
            ("monitors.lua", ".config/hypr/modules/monitors.lua"),
            ("vconsole.lua", ".config/hypr/modules/vconsole.lua"),
        ):
            self.assertEqual(
                (dest / name).read_bytes(), (DOTFILES / own).read_bytes()
            )
        config = (dest / "hyprland.lua").read_text()
        self.assertIn('require("monitors")', config)
        self.assertIn(f"{dest}/quickshell/shell.qml", config)
        self.assertNotIn("/etc/greetd", config, "staged paths")
        for name in (
            "shell.qml",
            "qmldir",
            "greeter-env.py",
            "style/qmldir",
            "style/Colors.qml",
            "style/Style.qml",
            "style/Theme.qml",
        ):
            self.assertTrue((dest / "quickshell" / name).is_file(), name)
        self.verifies(dest)

    @unittest.skipUnless(shutil.which("lua"), "needs lua")
    def test_the_systems_keyboard_layout(self) -> None:
        self.assertEqual(self.layouts(self.install("greetd")), "de")

    def test_the_wallpaper_and_the_theme(self) -> None:
        dest = self.install("greetd")
        self.assertEqual(
            (dest / "quickshell/wallpaper.jpg").read_bytes(),
            self.wallpaper.read_bytes(),
        )
        theme = dest / "quickshell/theme"
        self.assertEqual((theme / "palette.json").read_text(), PALETTE)
        self.assertTrue(
            (theme / "theme").read_text().startswith("Everforest-Light-Hard")
        )
        self.assertTrue(
            json.loads((theme / "appearance.json").read_text())["blur"]
        )
        self.assertIn(
            f"LOCKSCREEN_THEME={theme}", (dest / "hyprland.lua").read_text()
        )
        installed = json.loads(
            (dest / "quickshell/lockscreen.json").read_text()
        )
        self.assertEqual(installed["installedTheme"], "Everforest-Light-Hard")
        self.assertEqual(
            installed["installedAppearance"], {"blur": True, "accent": "green"}
        )

    @unittest.skipUnless(shutil.which("lua"), "needs lua")
    def test_kept_monitors_and_layouts_come_last(self) -> None:
        (self.state / "quickshell/monitors.lua").write_text(
            'return {\n\t{ output = "desc:Test Monitor 1", mode = "1920x1080@60", '
            'position = "0x0", scale = 1.25, transform = 0 },\n}\n'
        )
        (self.state / "quickshell/keyboard.lua").write_text(
            '-- Written by the shell.\nreturn { kb_layout = "us,de", kb_variant = ",nodeadkeys" }\n'
        )
        dest = self.install("greetd-kept")
        text = (dest / "monitors.lua").read_bytes()
        own = (DOTFILES / ".config/hypr/modules/monitors.lua").read_bytes()
        self.assertTrue(text.startswith(own))
        self.assertIn(b"desc:Test Monitor 1", text[len(own) :])
        self.assertEqual(
            self.lua(
                "local last\nhl = { monitor = function(rule) last = rule.output end }\n"
                f'dofile("{dest / "monitors.lua"}")\nprint(last)\n'
            ),
            "desc:Test Monitor 1",
        )
        self.assertEqual(self.layouts(dest), "us,de")
        self.verifies(dest)

    def test_a_fresh_install_has_no_wallpaper_yet(self) -> None:
        self.wallpaper.unlink()
        dest = self.install("greetd-fresh")
        self.assertFalse((dest / "quickshell/wallpaper.jpg").exists())

    def test_the_lock_screen_tabs_choices(self) -> None:
        # An image of its own for the login screen, then none, each with the
        # choices installed beside it and the image they came from, which
        # that page compares with its own.
        image = self.tmp / "login.png"
        image.write_bytes(PNG)
        look = self.state / "quickshell/lockscreen.json"
        look.write_text(
            json.dumps(
                {
                    "loginBackground": "image",
                    "loginImage": str(image),
                    "dim": 0.3,
                }
            )
        )
        dest = self.install("greetd-look")
        self.assertEqual(
            (dest / "quickshell/wallpaper.jpg").read_bytes(),
            image.read_bytes(),
        )
        installed = json.loads(
            (dest / "quickshell/lockscreen.json").read_text()
        )
        self.assertEqual(installed["dim"], 0.3)
        self.assertEqual(installed["installedImage"], str(image))
        self.assertIn(
            f"LOCKSCREEN_STYLE={dest}/quickshell/lockscreen.json",
            (dest / "hyprland.lua").read_text(),
        )

        look.write_text(json.dumps({"loginBackground": "plain"}))
        # An install from before Quickshell's own greetd client left its
        # helper.
        (dest / "quickshell/greetd-auth.py").write_text("")
        self.install("greetd-look")
        self.assertFalse((dest / "quickshell/wallpaper.jpg").exists())
        self.assertFalse((dest / "quickshell/greetd-auth.py").exists())


if __name__ == "__main__":
    unittest.main()
