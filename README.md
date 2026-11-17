# Jupiter-testing

The linters and tests of [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles) and [Jupiter-installer](https://github.com/skullduggerry/Jupiter-installer) (on Arch and on NixOS), and the one command that runs them for any of the three repos.

Part of Jupiter: [Jupiter-installer](https://github.com/skullduggerry/Jupiter-installer) sets up [Jupiter-dotfiles](https://github.com/skullduggerry/Jupiter-dotfiles), and this repo checks both, and itself.

## Installing

Clone the three repos next to each other:

```bash
git clone https://github.com/skullduggerry/Jupiter-dotfiles.git
git clone https://github.com/skullduggerry/Jupiter-installer.git
git clone https://github.com/skullduggerry/Jupiter-testing.git
```

or point `JUPITER_DOTFILES` and `JUPITER_INSTALLER` at wherever they are. The installer's NixOS evaluation tests need Nix and a nixpkgs (`JUPITER_NIXPKGS`, or Nix's `<nixpkgs>`), and are skipped without them. The tools are in Jupiter-installer's `packages/pacman.txt`, which its phase 3 installs; a missing one is named with its package.

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

| Suite | What it checks |
|---|---|
| `dotfiles/` | Every helper script of the dotfiles against stand-in commands, and the shell's QML logic inside Quickshell |
| `dotfiles/security/` | The lock and login screens, the Nextcloud app password, text from outside |
| `installer/` | Every phase, on Arch and on NixOS (`test_nixos_*`), against stand-in commands and a temporary `/mnt` or home; which system it is on; the `check` command; the NixOS modules evaluated by Nix |
| `installer/security/` | Who phase 1 makes a user with which rights, and what the installer fetches and opens; on NixOS also the passphrase and passwords kept out of the configuration, and the PAM stacks, finger and firewall the flake declares |
| `testing/` | This repo's own tooling: the QML runner, the parallel runner, `lint.sh` and `check.sh` |

## CI

Jupiter-dotfiles and Jupiter-installer each check their own pushes and pull requests with this repo's tools, on both systems the installer supports, by a `.github/workflows/check.yml` of their own: the repo's linters and suites in an Arch container, and on Nix the dotfiles' Hyprland config and QML suites on NixOS's Hyprland and Quickshell, or the installer's flake evaluated and built. Daily on main too. This repo's Actions run no checks, and only mirror it to Codeberg: a change here is checked by `./check.sh check all` and the pre-push hook before it is pushed, and by the other repos' next runs. `scripts/ci-repos.sh` lays the repos out; [docs/harness.md](docs/harness.md#ci) says how.

## Documentation

- [Development](https://github.com/skullduggerry/Jupiter-dotfiles/wiki/Development) in the wiki shared by the three repos: the checks, the suites, writing a test.
- [AGENTS.md](AGENTS.md): the map, the conventions and the pitfalls, for coding agents (Claude Code reads it through `CLAUDE.md`).
- [docs/harness.md](docs/harness.md): the stand-ins, CI, the security model and how a security test proves itself.
