"""The language servers the dotfiles' nvim enables (.config/nvim/init.lua's
`servers`), each installed on both systems: by arch/packages/ on Arch, by
nixos/packages.nix or desktop.nix on NixOS. Read from the sources: nvim
would only skip a server it cannot find."""

import re
import unittest

from jupiter.arch.common import packages

from harness import DOTFILES, INSTALLER

# Each server, by the package that brings its command on Arch and on NixOS.
SERVERS = {
    # quickshell depends on qt6-declarative, which links qmlls6.
    "qmlls": ("quickshell", "kdePackages.qtdeclarative"),
    "lua_ls": ("lua-language-server", "lua-language-server"),
    "ruff": ("ruff", "ruff"),
    "pyright": ("pyright", "pyright"),
    "bashls": ("bash-language-server", "bash-language-server"),
    "jsonls": ("vscode-json-languageserver", "vscode-langservers-extracted"),
    "cssls": ("vscode-css-languageserver", "vscode-langservers-extracted"),
    "yamlls": ("yaml-language-server", "yaml-language-server"),
    "taplo": ("taplo-cli", "taplo"),
    "nixd": ("nixd", "nixd"),
}


class LanguageServers(unittest.TestCase):
    def enabled(self) -> list[str]:
        init = (DOTFILES / ".config/nvim/init.lua").read_text()
        found = re.search(r"(?ms)^local servers = \{\n(.*?)^\}", init)
        assert found, "init.lua has no `local servers = { ... }` list"
        return re.findall(r'(?m)^\t"(\w+)",', found[1])

    def test_each_enabled_server_has_its_packages(self) -> None:
        self.assertEqual(sorted(self.enabled()), sorted(SERVERS))

    def test_arch_installs_each(self) -> None:
        arch = set(packages("core.txt") + packages("pacman.txt"))
        for server, (package, _) in SERVERS.items():
            with self.subTest(server):
                self.assertTrue(
                    package in arch, f"no {package} for {server} on Arch"
                )

    def test_nixos_installs_each(self) -> None:
        # One package to a line, as nixfmt writes systemPackages.
        nixos = {
            line.strip()
            for name in ("packages.nix", "desktop.nix")
            for line in (INSTALLER / "nixos" / name).read_text().splitlines()
        }
        for server, (_, package) in SERVERS.items():
            with self.subTest(server):
                self.assertTrue(
                    package in nixos, f"no {package} for {server} on NixOS"
                )
