# Jupiter Testing

The tests of [Jupiter-dotfiles](https://codeberg.org/skullduggery/Jupiter-dotfiles) and [Jupiter-installer](https://codeberg.org/skullduggery/Jupiter-installer), in a repo of their own. Clone it next to them:

```bash
git clone https://codeberg.org/skullduggery/Jupiter-dotfiles.git
git clone https://codeberg.org/skullduggery/Jupiter-installer.git
git clone <this repo> Jupiter-testing
```

or point `JUPITER_DOTFILES` and `JUPITER_INSTALLER` at wherever they are (and the other two repos' `JUPITER_TESTING` at this one). Each repo's `scripts/check.sh` runs its share of the tests from here.

## Usage

```bash
scripts/check.sh            # lint this repo, then every suite
scripts/test.sh             # every suite, under coverage of both repos
scripts/test.sh dotfiles    # one repo's suites
scripts/test.sh --security  # the security suites alone
python3 -m unittest dotfiles.test_shelf                    # one module
python3 -m harness.qml dotfiles/qml/ColorsTest.qml         # one QML test file
scripts/install-hooks.sh    # once per clone: pre-commit formats, pre-push checks
```

The suites need nothing beyond Python's standard library and what the tested repos need themselves; `test.sh` names any package that is missing. The tools are in Jupiter-installer's `packages/pacman.txt`.

## What runs

Everything runs against stand-ins, in temporary folders: nothing on the machine changes, and nothing reaches the network but loopback.

| Suite | What it checks |
|---|---|
| `dotfiles/test_*.py` | Every helper script of the dotfiles, as the shell starts it, against stand-in commands in a throwaway home: themes, the apps' glass, autostart, displays, the keymap, the tablet, the shelf, screen recording, wallpapers, desktop entries, the calendar's tasks, the login screen's installer. |
| `dotfiles/qml/` | The shell's QML logic inside Quickshell, offscreen: colours, the greeter's style and theme, idle times, keybinds, the quick menu, the launcher. |
| `dotfiles/security/` | The lock screen through stand-in PAM stacks (a wrong password, PAM's messages, a second question, a finger, a crash while locked, the tablet's pad while locked), the login screen against a stand-in greetd, its installer run as root (what it reads as you, and that what runs as root is root's copy), the PAM and greetd configuration, where the Nextcloud app password may go, and text from outside shown as text. |
| `installer/` | Phase 1 from the first question to the last file against a temporary `/mnt`, phases 2 to 4 in a throwaway home, the drivers, the package lists, fingerprints. |
| `installer/security/` | Who phase 1 makes a user, with which password and which rights, and what the installer fetches and opens. |

How the harness works, and how to write a test: `.github/PROJECT_STRUCTURE.md` and `.github/llm.md`.
