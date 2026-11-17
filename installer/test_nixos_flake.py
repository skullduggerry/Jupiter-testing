"""The installer's NixOS modules (nixos/), evaluated by Nix for
hosts/example and for settings phase 1 could write: a whole system comes
of them, and it is the one the settings describe (harness/nix.py evaluates;
skipped without Nix and nixpkgs).
"""

import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any

from harness import DOTFILES
from harness.nix import evaluate, example, skip_without_nix
from installer.test_nixos_phase1 import Declining, Encrypting

TOPLEVEL = "config.system.build.toplevel.drvPath"


def unencrypted() -> dict[str, Any]:
    settings = example()
    return settings | {
        "root": settings["root"] | {"luks": None},
        "data": [],
        "gpus": ["nvidia"],
    }


class System(unittest.TestCase):
    def test_a_whole_system_comes_of_each_kind_of_settings(self) -> None:
        for name, settings in (
            ("example", example()),
            ("unencrypted, NVIDIA's only", unencrypted()),
            (
                "bound to the TPM",
                example() | {"tpm": True, "volumeKey": "ab" * 32},
            ),
        ):
            with self.subTest(name):
                path = evaluate(TOPLEVEL, settings)
                self.assertRegex(path, r"^/nix/store/.*-nixos-system-example-")

    def test_the_settings_are_checked(self) -> None:
        # Before the subtests, which would take a skip for a pass.
        skip_without_nix()
        for field, value in (
            ("hostname", "Bad Host!"),
            ("user", "root:x"),
            (
                "data",
                [
                    {
                        "name": "d",
                        "mount": "/../etc",
                        "luks": "x",
                        "filesystem": "y",
                    }
                ],
            ),
            ("volumeKey", "not a hash"),
            ("gpus", ["voodoo"]),
        ):
            with (
                self.subTest(field=field),
                self.assertRaises(subprocess.CalledProcessError) as failed,
            ):
                evaluate(TOPLEVEL, example() | {field: value})
            self.assertIn(f"jupiter.settings.{field}", failed.exception.stderr)


class Disks(unittest.TestCase):
    def test_the_root_by_its_opened_volume(self) -> None:
        mounts = evaluate(
            '{ root = config.fileSystems."/"; nix = config.fileSystems."/nix";'
            ' data = config.fileSystems."/data"; }'
        )
        self.assertEqual(mounts["root"]["device"], "/dev/mapper/root")
        self.assertIn("subvol=@", mounts["root"]["options"])
        self.assertIn("subvol=@nix", mounts["nix"]["options"])
        filesystem = example()["data"][0]["filesystem"]
        self.assertEqual(
            mounts["data"]["device"], f"/dev/disk/by-uuid/{filesystem}"
        )
        self.assertIn("nofail", mounts["data"]["options"])

    def test_unencrypted_by_the_file_systems_uuid(self) -> None:
        settings = unencrypted()
        found = evaluate(
            '{ device = config.fileSystems."/".device;'
            "  luks = config.boot.initrd.luks.devices;"
            "  lanzaboote = config.boot.lanzaboote.enable;"
            "  systemdBoot = config.boot.loader.systemd-boot.enable; }",
            settings,
        )
        self.assertEqual(
            found,
            {
                "device": f"/dev/disk/by-uuid/{settings['root']['filesystem']}",
                "luks": {},
                "lanzaboote": False,
                "systemdBoot": True,
            },
        )

    def test_the_root_volumes_crypttab_options(self) -> None:
        options = "config.boot.initrd.luks.devices.root.crypttabExtraOpts"
        self.assertEqual(evaluate(options), ["tpm2-measure-pcr=yes"])
        key = "ab" * 32
        self.assertEqual(
            evaluate(options, example() | {"tpm": True, "volumeKey": key}),
            [
                "tpm2-measure-pcr=yes",
                "tpm2-device=auto",
                f"fixate-volume-key={key}",
            ],
        )

    def test_data_disks_open_with_their_key_files(self) -> None:
        disk = example()["data"][0]
        self.assertEqual(
            evaluate("config.environment.etc.crypttab.text"),
            f"data UUID={disk['luks']} /etc/cryptsetup-keys.d/data.key "
            "discard,nofail,x-systemd.device-timeout=10s\n",
        )

    def test_encrypted_boots_through_lanzaboote(self) -> None:
        self.assertEqual(
            evaluate(
                "[ config.boot.lanzaboote.enable"
                "  config.boot.lanzaboote.pkiBundle"
                "  config.boot.loader.systemd-boot.enable ]"
            ),
            [True, "/var/lib/sbctl", False],
        )


class Desktop(unittest.TestCase):
    def test_the_user_is_an_administrator_without_a_declared_password(
        self,
    ) -> None:
        user = example()["user"]
        found = evaluate(
            f'let u = config.users.users."{user}"; in {{'
            "  groups = u.extraGroups; mutable = config.users.mutableUsers;"
            "  declared = [ u.password u.hashedPassword u.initialPassword"
            "    u.initialHashedPassword u.hashedPasswordFile ];"
            "  shell = u.shell.pname or null; }"
        )
        self.assertEqual(
            found,
            {
                "groups": ["wheel"],
                "mutable": True,
                "declared": [None] * 5,
                "shell": "zsh",
            },
        )

    def test_greetd_runs_the_dotfiles_greeter_by_store_path(self) -> None:
        settings = evaluate("config.services.greetd.settings")
        self.assertRegex(
            settings["default_session"]["command"],
            r"^/nix/store/[^ ]+/bin/Hyprland -c /etc/greetd/hyprland.lua$",
        )
        self.assertEqual(settings["default_session"]["user"], "greeter")

    def test_the_session_units_skip_the_greeter(self) -> None:
        script = (DOTFILES / "scripts/install-system.sh").read_text()
        listed = script.split("not_greeter=(", 1)[1].split(")", 1)[0].split()
        found = evaluate(
            "let units = config.systemd.user.services // "
            "  (builtins.mapAttrs (_: v: v) config.systemd.user.sockets); in "
            "builtins.mapAttrs (_: u: u.unitConfig.ConditionUser or null) units"
        )
        for unit in listed:
            with self.subTest(unit=unit):
                self.assertEqual(
                    found.get(unit.rsplit(".", 1)[0]), "!greeter", unit
                )

    def test_the_paths_the_dotfiles_name_are_linked(self) -> None:
        rules = evaluate("config.systemd.tmpfiles.rules")
        linked = {
            rule.split()[1] for rule in rules if rule.startswith("L+ /usr/")
        }
        for path in (
            "/usr/local/lib/jupiter/greeter",
            "/usr/share/wayland-sessions",
            "/usr/share/X11/xkb",
            "/usr/share/themes",
        ):
            self.assertIn(path, linked)

    @unittest.skipUnless(shutil.which("nix-store"), "needs Nix (nix-store)")
    def test_zshrcs_plugins_are_in_the_profile(self) -> None:
        # .zshrc looks in each XDG_DATA_DIRS folder (the profile's share/)
        # for zsh/plugins/<name>/<name>.zsh or <name>/<name>.zsh: each
        # plugin's file must be in a folder the profile links.
        zshrc = (DOTFILES / ".config/.zshrc").read_text()
        names = zshrc.split("for plugin in ", 1)[1].split(";", 1)[0].split()
        found = evaluate(
            "{ links = config.environment.pathsToLink;"
            "  share = builtins.mapAttrs (_: p: p.drvPath) {"
            + "".join(
                f' "{name}" = builtins.head (builtins.filter'
                f' (p: (p.pname or "") == "{name}")'
                " config.environment.systemPackages);"
                for name in names
            )
            + " }; }"
        )
        for name in names:
            with self.subTest(plugin=name):
                built = subprocess.run(
                    ["nix-store", "--realise", found["share"][name]],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.split()[0]
                # The first in .zshrc's order: some ship both layouts.
                file = next(
                    relative
                    for relative in (
                        f"share/zsh/plugins/{name}/{name}.zsh",
                        f"share/{name}/{name}.zsh",
                    )
                    if Path(built, relative).exists()
                )
                self.assertTrue(
                    any(
                        f"/{file}".startswith(f"{link.rstrip('/')}/")
                        for link in found["links"]
                    ),
                    f"{file} is not in a folder the profile links",
                )


class WhatPhase1Writes(Encrypting):
    """The settings Python's phase 1 writes, as the flake reads them: the
    two halves agree on the format, field by field (an unknown or missing
    field, or a value of the wrong kind, fails the evaluation)."""

    def test_encrypted_with_a_data_disk_and_nvidia(self) -> None:
        skip_without_nix()
        self.install()
        found = evaluate(
            "{ drv = config.system.build.toplevel.drvPath;"
            "  data = builtins.attrNames config.fileSystems;"
            "  luks = config.boot.initrd.luks.devices.root.device; }",
            self.settings(),
        )
        self.assertIn("/data", found["data"])
        root = self.settings()["root"]["luks"]
        self.assertEqual(found["luks"], f"/dev/disk/by-uuid/{root}")


class WhatPhase1WritesUnencrypted(Declining):
    def test_unencrypted(self) -> None:
        skip_without_nix()
        self.install()
        self.assertRegex(
            evaluate(TOPLEVEL, self.settings()), r"-nixos-system-box-"
        )


class KnownIssues(unittest.TestCase):
    """What the review found and a fix waits for (docs/nixos.md, "Known
    issues"): each an expected failure, which once fixed passes and fails
    the run until its marker comes off."""

    @unittest.expectedFailure
    def test_qt_finds_the_systems_plugins(self) -> None:
        # Quickshell's wrapper reaches only its own image plugins (no
        # .webp), and Qt apps no qt6ct or Kvantum, unless NixOS points Qt at
        # the profile's plugins (its qt module).
        plugins = evaluate(
            "config.environment.profileRelativeSessionVariables"
            ".QT_PLUGIN_PATH or []"
        )
        self.assertIn("/lib/qt-6/plugins", plugins)

    @unittest.expectedFailure
    def test_docker_is_not_left_on_iptables_beside_nftables(self) -> None:
        # nixpkgs' networking.nftables.enable: Docker does not work with it
        # "without intervention".
        found = evaluate(
            "{ docker = config.virtualisation.docker.enable;"
            "  nftables = config.networking.nftables.enable;"
            "  backend = config.virtualisation.docker.daemon.settings"
            ".firewall-backend or null; }"
        )
        self.assertFalse(
            found["docker"]
            and found["nftables"]
            and found["backend"] != "nftables",
            found,
        )

    @unittest.expectedFailure
    def test_the_boot_partition_and_the_store_are_kept_in_bounds(self) -> None:
        # A 1 GiB ESP takes a signed image a generation; without a limit and
        # garbage collection it fills, and a rebuild fails.
        found = evaluate(
            "{ limit = config.boot.loader.systemd-boot.configurationLimit;"
            "  gc = config.nix.gc.automatic; }"
        )
        self.assertIsNotNone(found["limit"])
        self.assertTrue(found["gc"])


if __name__ == "__main__":
    unittest.main()
