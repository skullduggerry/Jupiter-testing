# Jupiter-testing: agent guide

The linters and tests of Jupiter-dotfiles (a Hyprland and Quickshell desktop) and Jupiter-installer (which installs Arch or NixOS with it), and the one command that checks any of the three. The two repos are next to this one (`../Jupiter-dotfiles`, `../Jupiter-installer`) or wherever `JUPITER_DOTFILES` and `JUPITER_INSTALLER` point. The dotfiles are the live session: a test never changes them, nor anything outside a temporary folder.

Read the tested repo's `AGENTS.md` before changing anything there: its conventions are this repo's too. Before writing a security test, or one that needs the harness's PAM, greetd, Nextcloud, root or VM stand-ins, read [docs/harness.md](docs/harness.md).

## Git

Commit and push straight to `main`, here and in Jupiter-dotfiles and Jupiter-installer: no branches or pull requests unless asked. CI checks each repo by its own `.github/workflows/check.yml`, on Arch and on NixOS: Jupiter-dotfiles' and Jupiter-installer's that repo alone, this one's all three with its tools as pushed, the tests the others skip included.

## Sources of truth, in order

1. The code under test and its repo's `AGENTS.md`.
2. This repo's harness (`harness/`) and conventions.
3. Python's `unittest` documentation, greetd-ipc(7), pam_exec(8) and the other manual pages of what a stand-in replaces.

## Map

| Path | What |
| --- | --- |
| `harness/` | what the suites share: where the repos are, helpers loaded by path, stand-in commands (`__init__.py`); the parallel runner (`run.py`); the QML runner (`qml.py`, `qml/TestCase.qml`, `qml/shell.qml`); the tests every repo's `check.sh` shares (`forwarding.py`); the PAM sandbox (`pam.py`) and a conversation to run in it (`converse.py`); stand-in greetd (`greetd.py`) and Nextcloud (`nextcloud.py`); reading sources (`source.py`); the NixOS modules evaluated by Nix (`nix.py`); the disks shared by both phase 1s (`disks.py`) |
| `dotfiles/` | Jupiter-dotfiles' tests: `test_<helper>.py` per helper script, `test_qml.py` running `qml/*Test.qml` (fixtures in `qml/fixtures/`) |
| `dotfiles/security/` | the lock and login screens, the Nextcloud account, text from outside |
| `installer/` | Jupiter-installer's tests: the phases against stand-ins on Arch and NixOS (`test_nixos_*`), which system it is on (`test_distro.py`, `fixtures/*-os-release`), the flake (`test_nixos_flake.py`) |
| `installer/security/` | users and rights, disks and passphrases, the TPM binding, the keyring, sudo and polkit with a finger; on NixOS what the flake declares |
| `testing/` | this repo's own tooling, each part made to fail: both runners, `lint.sh`, `check.sh`, CI's layout, the VM rig, the docs' references (`test_docs.py`) |
| `vm/` | the installer end to end in a VM (`scripts/vm.sh`, not part of `check.sh`; CI's `vm.yml` runs it weekly) |
| `check.sh` | the one command, which every repo's `check.sh` hands over to |
| `scripts/` | `lint.sh` (one repo's formatters and linters), `test.sh` (the suites under coverage), `install-hooks.sh`, `ci-repos.sh` (CI's layout of the repos), `nixos-check.sh` (CI's NixOS checks), the dotfiles' lint helpers `quickshell-types.py` and `pasted-glyphs.py` |
| `.githooks/` | pre-push: format and lint the pushed repo, then every repo's suites |
| `pyproject.toml`, `.editorconfig` | ruff, mypy (strict) and coverage here; the tested repos keep their own, which `lint.sh` reads there |

Each test module also runs alone: `python3 -m unittest dotfiles.test_shelf`, or one QML file with `python3 -m harness.qml dotfiles/qml/ColorsTest.qml`.

## Writing tests

- One `test_<helper>.py` per helper script, beside the others for its repo; a `<Name>Test.qml` per QML singleton's logic (`dotfiles/qml/`); anything about logging in, locking, a secret, a user's rights or text from outside under that repo's `security/`.
- `unittest` only: no new dependency. Each test runs in a process of its own beside the others (`harness/run.py`): it shares nothing but the files it was given, and waits on nothing it could check sooner. A class sets up a world of stand-ins (`setUp`, `harness.temporary()`), a method checks one behaviour and is named after it, a table of cases goes through `subTest`.
- Run the real code: the helper as the shell starts it, the QML singleton in Quickshell, the script under bash, the installer as `python3 -m jupiter`. Replace only what reaches the system: a command by a stand-in on PATH, the network by a loopback server, PAM by a sandbox, greetd by a socket.
- The installer's tests set `JUPITER_OS_RELEASE` to Arch's os-release unless they say NixOS, so both systems' phases run on any machine. NixOS evaluations need Nix and a nixpkgs (`JUPITER_NIXPKGS`) and skip without them.
- Assert what a person would notice, by value: the files written, the commands run with their arguments, the text shown. A failure message says what went wrong in the code's terms.
- A security test proves itself: break the code it guards and watch it fail ([docs/harness.md](docs/harness.md#mutations)).
- What a running test cannot show, the sources can (`harness/source.py`): name exactly what the test looks for, so a rewrite it no longer understands fails rather than passes unseen.
- A known bug whose fix waits for approval is an `@unittest.expectedFailure` with a comment saying why; the fix makes it pass, which fails the run until the marker comes off.
- Comments say why, where the code doesn't. Docstrings say what a module or class covers and against which stand-ins.

## Pitfalls

Each of these has already cost a test run.

- A wait that passes on an idle machine can fail beside fifteen other tests: wait on the event itself (`tryVerify()` on what the stand-in records), and slow the stand-in down to prove it (`fixtures/LockCheckingTest/`).
- `FileView` in a test reads with `blockAllReads: true` and `reload()`, or `text()` answers from before the write.
- A flag that is true for a moment (`LockService.fingerprint` between two attempts) cannot be polled: count what the stand-in records instead.
- A test that counts what was sent counts within its own attempt (`thisLogin()`), not over the whole log of a file that ran others before.
- Quickshell's greetd client logs the session greetd ends after a failure as an unexpected answer, and its error on a refused login as a warning: tests that cause either `ignoreWarning()` it.
- qmllint counts a member read off what `createObject()` returns (a `QObject`) as a warning and prints nothing for it, so lint fails with an empty report: cast it (`as GlassHighlight`); `qmllint --json -` shows what it counted.
- A subclass of a TestCase inherits its tests: share a fixture through a base class that has none (`installer/test_phase1.Installing`).
- A stand-in PATH hides real tools: what a test needs from the machine is found before it patches PATH (`harness.nix.NIX_INSTANTIATE`).
- A helper killed with SIGKILL saves no coverage: stop it with `terminate()`.
- A server's `shutdown()` waits for its loop to look again (`serve_forever` polls every half second by default; `harness/nextcloud.py` passes 0.01).
- Files chowned to a subordinate uid cannot be removed by the test: the namespace that chowned them hands them back before it ends.
- `bootstrap.sh` ends on `</dev/tty`, which a test's process does not have: `installer/test_bootstrap.py` gives each run a terminal of its own (`pty.fork()`).
- `Hyprland --verify-config` wants an `XDG_RUNTIME_DIR` and reads the state the config loads (`blur.lua`): `dotfiles/test_blur_options.py` gives it both in a temporary folder.
- The installer refuses root for phases 3 and 4 (2 to 4 on NixOS): run its suites as a user.
- Under zsh, an unquoted `$VAR` holding a command is one word (`${=VAR}`).

## Done means

- `./check.sh check all` passes (`--fix` formats first): each repo's formatting and linters, then every suite under coverage, each tested repo at its floor (dotfiles 90 %, installer 95 %) and every helper run by a test. A change to the tooling has its test in `testing/`.
- A fix in a tested repo passes that repo's `./check.sh` too, and for the dotfiles the running shell's log shows no new warning after the reload.
- Report what changed, why, how it was verified, and what could not be.
