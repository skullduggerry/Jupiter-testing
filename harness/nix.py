"""The installer's NixOS modules (nixos/) evaluated by Nix, for the tests
to read what a machine's configuration comes to: its PAM stacks, greetd's
settings, the firewall, the file systems.

The modules are evaluated as the flake does (nixos/, a host's
hardware-configuration.nix and its settings), with nixpkgs from
JUPITER_NIXPKGS (a nixpkgs checkout or channel tarball, unpacked), or else
the one Nix finds as <nixpkgs> on its path, and lanzaboote's options stood
in for, as fetching it needs GitHub. Nothing is built: evaluating is enough
to read the configuration. Without Nix, or without nixpkgs, the tests that
need it are skipped, saying which.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from functools import cache
from pathlib import Path
from typing import Any

from . import DOTFILES, INSTALLER

LANZABOOTE = """\
# lanzaboote's options alone, where its module cannot be fetched.
{ lib, ... }:
{
  options.boot.lanzaboote = {
    enable = lib.mkEnableOption "lanzaboote";
    pkiBundle = lib.mkOption { type = lib.types.nullOr lib.types.str; default = null; };
  };
}
"""
# The repos as the flake sees them (no .git); settings from a file, as JSON.
EVALUATE = """\
{ nixpkgs, installer, dotfiles, host, settings, stub }:
let
  source = path: builtins.path {
    inherit path; name = "source";
    filter = p: _: baseNameOf p != ".git";
  };
  repo = source installer;
in
import (nixpkgs + "/nixos/lib/eval-config.nix") {
  system = null;
  modules = [
    stub
    (repo + "/nixos")
    (repo + "/hosts/${host}/hardware-configuration.nix")
    {
      jupiter.settings = builtins.fromJSON (builtins.readFile settings);
      jupiter.dotfiles = source dotfiles;
    }
  ];
}
"""


@cache
def nixpkgs() -> Path | None:
    """nixpkgs to evaluate with, or None."""
    given = os.environ.get("JUPITER_NIXPKGS")
    if given:
        return Path(given)
    if not shutil.which("nix-instantiate"):
        return None
    found = subprocess.run(
        ["nix-instantiate", "--find-file", "nixpkgs"],
        capture_output=True,
        text=True,
        check=False,
    )
    path = Path(found.stdout.strip())
    if found.returncode or not (path / "nixos/lib/eval-config.nix").exists():
        return None
    return path


def skip_without_nix() -> None:
    """Skip the test calling it where Nix or nixpkgs is missing."""
    if not shutil.which("nix-instantiate"):
        raise unittest.SkipTest("needs Nix (nix-instantiate)")
    if nixpkgs() is None:
        raise unittest.SkipTest(
            "needs nixpkgs: set JUPITER_NIXPKGS to a checkout, or give Nix "
            "one as <nixpkgs>"
        )


def example() -> dict[str, Any]:
    """hosts/example's settings."""
    settings: dict[str, Any] = json.loads(
        (INSTALLER / "hosts/example/settings.json").read_text()
    )
    return settings


def evaluate(expression: str, settings: dict[str, Any] | None = None) -> Any:
    """An expression over `config` (hosts/example's configuration, or one
    with these settings), evaluated strictly to JSON. Raises
    subprocess.CalledProcessError, with Nix's message, if it fails."""
    skip_without_nix()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "evaluate.nix").write_text(EVALUATE)
        (folder / "lanzaboote.nix").write_text(LANZABOOTE)
        (folder / "settings.json").write_text(
            json.dumps(settings if settings is not None else example())
        )
        arguments = {
            "nixpkgs": nixpkgs(),
            "installer": INSTALLER,
            "dotfiles": DOTFILES,
            "settings": folder / "settings.json",
            "stub": folder / "lanzaboote.nix",
        }
        given = " ".join(
            f"{name} = {path};" for name, path in arguments.items()
        )
        text = (
            f"let config = (import {folder}/evaluate.nix "
            f'{{ {given} host = "example"; }}).config; in {expression}'
        )
        result = subprocess.run(
            [
                "nix-instantiate", "--read-write-mode", "--eval", "--strict",
                "--json", "-E", text,
            ],
            capture_output=True,
            text=True,
            check=False,
        )  # fmt: skip
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode, "nix-instantiate", result.stdout, result.stderr
        )
    return json.loads(result.stdout)
