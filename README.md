# Jupiter-testing

The linters and tests of [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles) and [Jupiter-installer](https://github.com/skullduggerry/Jupiter-installer) (on Arch and on NixOS), and the one command that runs them for any of the three repos.

Part of Jupiter: [Jupiter-installer](https://github.com/skullduggerry/Jupiter-installer) sets up [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles), and this repo checks both, and itself.

## Setup

Clone the three repos next to each other:

```bash
git clone https://github.com/skullduggerry/Jupiter-dotfiles.git
git clone https://github.com/skullduggerry/Jupiter-installer.git
git clone https://github.com/skullduggerry/Jupiter-testing.git
```

or point `JUPITER_DOTFILES` and `JUPITER_INSTALLER` at wherever they are. The installer's NixOS evaluation tests need Nix and a nixpkgs (`JUPITER_NIXPKGS`, or Nix's `<nixpkgs>`), and are skipped without them. The tools are in Jupiter-installer's `arch/packages/pacman.txt`, which its phase 3 installs; a missing one is named with its package.

## Usage

```bash
./check.sh                       # the repo you are in: formatting, linters, then its suites
./check.sh check all             # all three repos
./check.sh lint dotfiles         # or test: one half, one repo or a clone's path (--fix formats first)
./check.sh test --security       # the security suites alone (-k Lock: tests by name)
scripts/install-hooks.sh         # once: before each push, lint that repo and test every repo
```

Jupiter-dotfiles and Jupiter-installer have a `check.sh` of their own that takes the same arguments and hands them to this one.

## Suites

Everything runs against stand-ins in temporary folders: nothing on the machine changes, and nothing reaches the network but loopback. Each test runs in a process of its own, as many at once as there are CPUs.

| Suite | Tests |
|---|---|
| `dotfiles/` | Every helper script of the dotfiles against stand-in commands, and the shell's QML logic inside Quickshell |
| `dotfiles/security/` | The lock and login screens, the Nextcloud app password, text from outside |
| `installer/` | Every phase, on Arch and on NixOS (`test_nixos_*`), against stand-in commands and a temporary `/mnt` or home; which system it is on; the `check` command; the NixOS modules evaluated by Nix |
| `installer/security/` | Who phase 1 makes a user with which rights, and what the installer fetches and opens; on NixOS also the passphrase and passwords kept out of the configuration, and the PAM stacks, finger and firewall the flake declares |
| `testing/` | This repo's own tooling: the QML runner, the parallel runner, `lint.sh`, `check.sh` and the VM rig |
| `vm/` | The installer end to end in a VM: QEMU with OVMF (Secure Boot) and swtpm, from the Arch ISO. Not part of `check.sh`: run `scripts/vm.sh` (CI runs it weekly) |

## CI

Each repo's `.github/workflows/check.yml` runs on every push and pull request, and daily on main, with two jobs: lint and test in an Arch container, and the NixOS checks on Nix. Jupiter-dotfiles and Jupiter-installer check themselves; this repo checks all three as pushed, since a change to its tools can break any of them, including the tests the other two skip (they need a desktop's daemons or user namespaces with capabilities). The log names every test still skipped and why. `vm.yml` runs the VM suite weekly. Details: [docs/harness.md](docs/harness.md#ci).

## Documentation

- [Development](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Development) in the wiki shared by the three repos: the checks, the suites, writing a test.
- [CLAUDE.md](CLAUDE.md): the map, the conventions and the pitfalls, for coding agents.
- [docs/harness.md](docs/harness.md): the stand-ins, CI, the security model and how a security test proves itself.
