"""The PAM stacks, the finger and the firewall the installer declares on NixOS,
evaluated by Nix for hosts/example (harness/nix.py; skipped without Nix).

On Arch the dotfiles' etc/pam.d/greetd is installed as it is, and
dotfiles/security/test_login_screen.py runs it. Here login.nix adapts it to
NixOS, and these tests hold the adaptation to that: the same lines, only
modules and helpers by store path; the local-login stack it includes as
Arch's, without a keyring or a finger and never `sufficient`; no keyring in
`login`, which the lock screen checks the password with; a finger in sudo
and polkit only, and in the lock screen's reader (jupiter-fingerprint, the
dotfiles' pam/fingerprint.conf); KDE Connect's ports open to the local networks alone. The
pam_exec helpers are built and run, as greetd's PAM would, with no PATH.
"""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from harness import DOTFILES, executable
from harness.nix import evaluate, skip_without_nix

# The lock screen's reader, which login.nix declares from this file.
FINGERPRINT = DOTFILES / ".config/quickshell/pam/fingerprint.conf"
STORE = re.compile(r"/nix/store/[a-z0-9]{32}-[^/\s]+")
# login.nix's pam_exec helpers, built from etc/greetd/<name>.
HELPER = re.compile(r"/nix/store/[a-z0-9]{32}-jupiter-([a-z-]+)\b")
# Linux-PAM's own modules, which NixOS finds by name: the only ones the
# stacks may name without a path.
LINUX_PAM = {
    "pam_deny.so",
    "pam_echo.so",
    "pam_exec.so",
    "pam_faillock.so",
    "pam_nologin.so",
    "pam_securetty.so",
}


def services() -> dict[str, str]:
    """Every PAM stack of the example, by service."""
    found: dict[str, str] = evaluate(
        "builtins.mapAttrs (_: s: s.text) config.security.pam.services"
    )
    return found


def rules(text: str, kind: str) -> list[list[str]]:
    """A stack's lines of one kind (auth, session...), as words."""
    lines = [line.split("#", 1)[0].split() for line in text.splitlines()]
    return [line for line in lines if line and line[0].lstrip("-") == kind]


def module(line: list[str]) -> str:
    """A rule's module: after its control, bracketed or not."""
    words = " ".join(line[1:])
    if words.startswith("["):
        return words.split("]", 1)[1].split()[0]
    return line[2]


class Greetd(unittest.TestCase):
    def test_the_dotfiles_lines_with_modules_by_store_path(self) -> None:
        stacks = services()
        for name, file in (
            ("greetd", DOTFILES / "etc/pam.d/greetd"),
            ("greetd-greeter", DOTFILES / "etc/pam.d/greetd-greeter"),
            ("jupiter-fingerprint", FINGERPRINT),
        ):
            with self.subTest(name):
                ours = file.read_text()
                # Back to the dotfiles' words: the same file, line for line.
                back = HELPER.sub(r"/etc/greetd/\1", stacks[name])
                back = re.sub(STORE.pattern + "/lib/security/", "", back)
                back = back.replace(
                    "jupiter-local-login", "system-local-login"
                )
                self.assertEqual(back, ours)

    def test_every_module_is_found(self) -> None:
        stacks = services()
        for name in (
            "greetd",
            "greetd-greeter",
            "jupiter-local-login",
            "jupiter-fingerprint",
        ):
            for kind in ("auth", "account", "session", "password"):
                for line in rules(stacks[name], kind):
                    if line[1] in ("include", "substack"):
                        # A stack NixOS does not have (Arch's
                        # system-local-login) fails every login.
                        with self.subTest(service=name, includes=line[2]):
                            self.assertIn(line[2], stacks)
                        continue
                    found = module(line)
                    with self.subTest(service=name, module=found):
                        self.assertTrue(
                            STORE.match(found) or found in LINUX_PAM,
                            f"{name} names {found} where NixOS's PAM finds none",
                        )

    def test_the_helpers_by_store_path(self) -> None:
        greetd = services()["greetd"]
        self.assertNotIn("/etc/greetd/", greetd)
        self.assertEqual(
            sorted(set(HELPER.findall(greetd))),
            ["disk-encrypted", "finger-asked"],
        )

    def test_the_local_login_is_archs_without_keyring_or_finger(self) -> None:
        text = services()["jupiter-local-login"]
        auth = rules(text, "auth")
        modules = [module(line).rsplit("/", 1)[-1] for line in auth]
        self.assertEqual(
            modules,
            [
                "pam_faillock.so",
                "pam_unix.so",
                "pam_faillock.so",
                "pam_faillock.so",
            ],
        )
        self.assertEqual(
            [line[-1] for line in auth if "pam_faillock.so" in module(line)],
            ["preauth", "authfail", "authsucc"],
        )
        # `sufficient` would end greetd's stack at the include.
        self.assertFalse([line for line in auth if line[1] == "sufficient"])
        self.assertNotIn("pam_gnome_keyring", text)
        self.assertNotIn("pam_fprintd", text)
        sessions = " ".join(module(line) for line in rules(text, "session"))
        self.assertIn("pam_env.so", sessions)
        self.assertIn("pam_systemd.so", sessions)


class Elsewhere(unittest.TestCase):
    def test_login_gives_gnome_keyring_nothing(self) -> None:
        login = services()["login"]
        self.assertNotIn("pam_gnome_keyring", login)
        self.assertNotIn("pam_fprintd", login)

    def test_a_finger_in_sudo_and_polkit_only(self) -> None:
        stacks = services()
        for name, text in stacks.items():
            fingers = [
                line
                for line in rules(text, "auth")
                if module(line).endswith("/pam_fprintd.so")
            ]
            with self.subTest(service=name):
                if name in ("sudo", "polkit-1"):
                    self.assertEqual(len(fingers), 1)
                    self.assertEqual(fingers[0][1], "sufficient")
                    self.assertEqual(
                        fingers[0][3:], ["max-tries=3", "timeout=10"]
                    )
                    # First: a finger before the password is asked.
                    first = rules(text, "auth")[0]
                    self.assertEqual(first, fingers[0])
                elif name not in ("greetd", "jupiter-fingerprint"):
                    self.assertEqual(fingers, [])

    def test_kde_connect_from_the_local_networks_only(self) -> None:
        firewall = evaluate(
            "{ inherit (config.networking.firewall) enable allowedTCPPorts"
            "  allowedUDPPorts allowedTCPPortRanges allowedUDPPortRanges"
            "  extraCommands;"
            "  nftables = config.networking.nftables.enable; }"
        )
        self.assertTrue(firewall["enable"])
        # iptables, which Docker writes its own rules beside.
        self.assertFalse(firewall["nftables"])
        for kind in ("TCP", "UDP"):
            for span in firewall[f"allowed{kind}PortRanges"]:
                with self.subTest(kind=kind, span=span):
                    self.assertFalse(span["from"] <= 1714 <= span["to"])
            self.assertFalse(
                [
                    p
                    for p in firewall[f"allowed{kind}Ports"]
                    if 1714 <= p <= 1764
                ]
            )
        # The rules as the firewall's start adds them: its extra commands
        # run by bash, iptables and ip6tables standing in to record them.
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "calls"
            for name in ("iptables", "ip6tables"):
                executable(
                    Path(tmp) / name,
                    f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n',
                )
            subprocess.run(
                ["bash", "-euc", firewall["extraCommands"]],
                env={"PATH": f"{tmp}:/usr/bin:/bin"},
                check=True,
            )
            # Other modules add theirs (Docker's NAT): only the ones
            # naming KDE Connect's ports are this one's.
            added = [
                line
                for line in calls.read_text().splitlines()
                if "1714" in line or "1764" in line
            ]
        accept = "--dport 1714:1764 -j nixos-fw-accept"
        self.assertEqual(
            sorted(added),
            sorted(
                f"{table} -A nixos-fw -p {proto} -s {net} {accept}"
                for proto in ("tcp", "udp")
                for table, net in (
                    ("iptables", "10.0.0.0/8"),
                    ("iptables", "172.16.0.0/12"),
                    ("iptables", "192.168.0.0/16"),
                    ("ip6tables", "fe80::/10"),
                )
            ),
        )


@unittest.skipUnless(shutil.which("nix-build"), "needs Nix (nix-build)")
class Helpers(unittest.TestCase):
    """finger-asked as pam_exec runs it: no PATH, the answer on stdin."""

    def build(self, name: str) -> str:
        skip_without_nix()
        path: str = evaluate(f"config.system.build.jupiter.{name}.drvPath")
        built = subprocess.run(
            ["nix-store", "--realise", path],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()[0]
        return built

    def test_only_an_empty_answer_asks_for_a_finger(self) -> None:
        skip_without_nix()
        helper = self.build("fingerAsked")
        for answer, finger in (
            (b"\0", True),
            (b"", True),
            (b"x\0", False),
            (b"correct horse\0", False),
        ):
            with self.subTest(answer=answer):
                done = subprocess.run(
                    [helper], input=answer, env={}, check=False
                )
                self.assertEqual(done.returncode == 0, finger)

    def test_no_tool_left_under_usr(self) -> None:
        for name in ("fingerAsked", "diskEncrypted"):
            with self.subTest(name):
                with open(self.build(name)) as built:
                    text = built.read()
                self.assertNotIn("/usr/", text)
                self.assertTrue(text.startswith("#!/nix/store/"))


if __name__ == "__main__":
    unittest.main()
