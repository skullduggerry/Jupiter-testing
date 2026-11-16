# Jupiter-testing

The linters and tests of [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles), [Jupiter-installer](https://github.com/skullduggerry/Jupiter-installer) (Arch) and Jupiter-nixos (NixOS, new: for now a branch of Jupiter-installer), and the one command that runs them for any of the repos.

Part of Jupiter: [Jupiter-installer](https://github.com/skullduggerry/Jupiter-installer) sets up [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles), and this repo checks both, and itself.

## Installing

Clone the three repos next to each other:

```bash
git clone https://github.com/skullduggerry/Jupiter-dotfiles.git
git clone https://github.com/skullduggerry/Jupiter-installer.git
git clone https://github.com/skullduggerry/Jupiter-testing.git
```

or point `JUPITER_DOTFILES` and `JUPITER_INSTALLER` at wherever they are. Jupiter-nixos is checked where it is cloned, at `../Jupiter-nixos` or `JUPITER_NIXOS` (while it is a branch: `git -C Jupiter-installer worktree add ../Jupiter-nixos <branch>`). Its evaluation tests need Nix and a nixpkgs (`JUPITER_NIXPKGS`, or Nix's `<nixpkgs>`), and are skipped without them. The tools are in Jupiter-installer's `packages/pacman.txt`, which its phase 3 installs; a missing one is named with its package.

## Usage

```bash
./check.sh                       # the repo you are in: formatting, linters, then its suites
./check.sh check all             # every repo (Jupiter-nixos where it is cloned)
./check.sh lint dotfiles         # or test: one half, one repo or a clone's path (--fix formats first)
./check.sh test --security       # the security suites alone (-k Lock: tests by name)
scripts/install-hooks.sh         # once: before each push, lint that repo and test every repo
```

Jupiter-dotfiles and Jupiter-installer have a `check.sh` of their own that takes the same arguments and hands them to this one.

## Suites

Everything runs against stand-ins in temporary folders: nothing on the machine changes, and nothing reaches the network but loopback. Each test runs in a process of its own, as many at once as there are CPUs.

| Suite | What it checks |
|---|---|
| `dotfiles/` | Every helper script of the dotfiles against stand-in commands, and the shell's QML logic inside Quickshell |
| `dotfiles/security/` | The lock and login screens, the Nextcloud app password, text from outside |
| `installer/` | Every phase against stand-in commands and a temporary `/mnt` or home, and the `check` command |
| `installer/security/` | Who phase 1 makes a user with which rights, and what the installer fetches and opens |
| `nixos/` | Jupiter-nixos: phase 1 against stand-in commands and a temporary `/mnt`, phases 2 and 3 in a throwaway home, and the flake's modules evaluated by Nix |
| `nixos/security/` | The disk passphrase and passwords in phase 1 (never in the configuration, which lands in the store), and the PAM stacks, finger and firewall the flake declares |
| `testing/` | This repo's own tooling: the QML runner, the parallel runner, `lint.sh` and `check.sh` |

## CI

Every push and pull request to any Jupiter repo is checked against both setups, Arch and NixOS, by the same `.github/workflows/check.yml`: the pushed repo's linters and every repo's suites in an Arch container, and on Nix the flake evaluated with the pushed dotfiles, its login helpers built, and the dotfiles' Hyprland config and QML suites run on NixOS's Hyprland and Quickshell. Daily on main too. `scripts/ci-repos.sh` lays the repos out, both installers always among them; `.github/PROJECT_STRUCTURE.md` says how.

## Documentation

- [Development](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Development) in the wiki shared by the three repos: the checks, the suites, writing a test.
- `.github/`: the harness, the security model and the conventions (`PROJECT_STRUCTURE.md`, and `llm.md` for coding agents).
