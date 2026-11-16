# Project structure

The map of the repo and the rules the code alone does not show. How to
write tests: `.github/llm.md`.

## Repo

| Path | What |
| --- | --- |
| `harness/` | what the suites share: where the repos are, helpers loaded by path, stand-in commands (`__init__.py`), the parallel runner (`run.py`), the QML runner (`qml.py`, with `qml/TestCase.qml` and `qml/shell.qml`), the tests every repo's `check.sh` shares (`forwarding.py`), the PAM sandbox (`pam.py`) and a PAM conversation to run in it (`converse.py`), a stand-in greetd (`greetd.py`), a stand-in Nextcloud (`nextcloud.py`), and reading sources (`source.py`) |
| `dotfiles/` | Jupiter-dotfiles' tests: `test_<helper>.py` per helper script, `test_qml.py` running `qml/*Test.qml` |
| `dotfiles/security/` | the lock screen, the login screen, the Nextcloud account, text from outside; QML tests in `qml/`, their fixtures in `qml/fixtures/` |
| `installer/` | Jupiter-installer's tests: the phases against stand-ins |
| `installer/security/` | who phase 1 makes a user, with which password and rights; root checks, firewall, sources; the disk passphrase, data disks and disks not chosen; the TPM binding; the login keyring; the sudo and polkit stacks with a finger |
| `nixos/` | Jupiter-nixos' tests: phase 1 against stand-ins (the disks are `harness/disks.py`, shared with `installer/`), phases 2 and 3, the TPM step, `desktop-entries.py`, and the flake's modules evaluated by Nix (`harness/nix.py`) |
| `nixos/security/` | the passphrase and passwords in phase 1, disks not chosen, key files; the login keyring; the PAM stacks the flake declares (greetd's from the dotfiles, the local login it includes, `login`, sudo and polkit), the finger, the firewall, the pam_exec helpers built and run |
| `testing/` | this repo's own tooling, each part made to fail: the QML runner, the parallel runner, `lint.sh`, `check.sh`, the VM rig |
| `vm/` | the installer end to end in a VM (`scripts/vm.sh`, not part of `check.sh`): the rig (`rig.py`), installing with phases 1 and 2 (`install.py`) and the scenarios (`test_install.py`) |
| `check.sh` | the one command, which every repo's `check.sh` hands over to: each repo's lint, then the suites |
| `scripts/` | `lint.sh` (one repo's formatting and linters), `test.sh` (the suites under coverage), `install-hooks.sh`, and the dotfiles' lint helpers: `quickshell-types.py` (Quickshell's type information, corrected for qmllint) and `pasted-glyphs.py` |
| `.githooks/` | pre-push (format, lint, suites; stops if formatting changed anything), which `install-hooks.sh` points all three clones at; they check whichever repo they run in |
| `pyproject.toml`, `.editorconfig` | ruff, mypy (strict) and coverage for this repo; the tested repos keep their own, which `lint.sh` reads there |

Each test module also runs alone: `python3 -m unittest dotfiles.test_shelf`.

Jupiter-nixos is found at `../Jupiter-nixos` or `JUPITER_NIXOS`, and is one
of `all` (and of the default outside the repos) only where it is cloned, as
it is new. Its repo is told from the Arch installer's by its `flake.nix` and
`jupiter_nixos/`; the Python package has a name of its own so that both
installers' tests load in one process (`harness/run.py` collects them all).
`harness/nix.py` evaluates its modules as the flake does, for
`hosts/example` or settings a test gives, with nixpkgs from
`JUPITER_NIXPKGS` or Nix's `<nixpkgs>` and lanzaboote's options stood in for;
nothing is built but the pam_exec helpers, which
`nixos/security/test_login_stacks.py` runs.

## Running

```bash
./check.sh                       # the repo you are in, or all three outside them
./check.sh check all             # every repo: lint.sh for each, then test.sh for all
./check.sh lint dotfiles         # formatting and linters only, one repo or a clone's path
./check.sh test                  # the suites only
./check.sh --fix                 # format and apply the safe lint fixes first
./check.sh --staged              # lint the staged files only
./check.sh test --security       # the security suites alone, no coverage floor
./check.sh test -k Restore       # the tests matching a pattern, as unittest's -k
python3 -m unittest dotfiles.security.test_lock_screen -k Restore
python3 -m harness.qml dotfiles/security/qml/LockPasswordTest.qml
scripts/install-hooks.sh         # once per clone: hooks for all three repos
```

Jupiter-dotfiles and Jupiter-installer have a `check.sh` of their own (and
the installer's `bootstrap.sh check|lint|test` runs its): each finds this
repo next to it or at `JUPITER_TESTING`, cloning it there if it is missing,
and hands it its arguments with its own clone as its repo. What they share
is tested once, in `harness/forwarding.py`.

`scripts/vm.sh [-k PATTERN]` installs Jupiter in a VM and runs the
scenarios of `vm/test_install.py` (see "The VM").

`lint.sh KIND PATH` runs the tools inside PATH, so each repo is held to its
own `pyproject.toml`, `.editorconfig` and `.luarc.json`. The slow parts run
side by side: every formatter over its files, qmllint in as many parts as
there are CPUs, lua-language-server in the background from the start.

`test.sh` hands every module of the chosen repos to `harness/run.py` at once,
which runs each test in a process of its own, as many at once as there are
CPUs, the slowest first by the last run's times
(`~/.cache/jupiter-testing/durations.json`). A process per test keeps tests
apart as running a module at a time did: a singleton, a loaded helper or an
environment change reaches no other test. Every Python process measures
itself under coverage of both repos (coverage's `.pth` reads
`COVERAGE_PROCESS_START`; `sigterm` saves a helper the test stops), and every
bash script a test starts is noted (`BASH_ENV`). It fails on a helper of the
repo no test runs, and on a repo whose Python lines the suites run less of
than its floor (`floors` in `test.sh`). It names any package it is missing,
among them python-dateutil, which the calendar helper imports.

## The harness

**Stand-ins.** A command a helper would reach the system with is a script
on a PATH of the test's own (`harness.executable()`), which records how it
was called and answers as the real one would. Environments are built from
scratch or from `harness.environment()`, which drops the XDG folders of
whoever runs the tests; a helper never sees the real session bus, keyring or
home.

**QML** (`harness/qml.py`). Each file runs in a Quickshell of its own,
offscreen, in a throwaway home, staged under `/tmp` (the IPC socket's path
must stay short): the file beside `TestCase.qml` and `shell.qml`, a copy of
the shell as `../shell/`, and the login screen as installed (with `style/`)
as `../greeter/`. What a file runs with comes from `fixtures/<its name>/`:
`pam.d/` (the sandbox's stacks), `greetd.json` (a stand-in greetd's
scenario), `theme/`, `runtime/` (Hyprland's runtime folder, and a signature),
`bin/` (its PATH), `share/` (its `XDG_DATA_DIRS`: the desktop entries
it sees), and anything else beside the test (a stand-in
`pam/fingerprint.conf`, `greeter-env.py`). A fixture shared by several files
is a link into a folder of its own (`fixtures/lock/`). Text files get
`@FIXTURES@`, `@SECRET@` and `@PYTHON@` filled in. A file fails on a FAIL,
on any warning Quickshell logs that `ignoreWarning()` did not expect, and on
any line that shows `harness.SECRET`.

**PAM** (`harness/pam.py`). The lock screen checks the password with the
system's own `login` stack. In a user namespace the test binds its stacks
over `/etc/pam.d` and maps itself back to its own uid, so the real
`LockService` runs the whole conversation unprivileged: `pam_exec` with
`expose_authtok` checks a password, `pam_stress` asks a second question,
`pam_deny` refuses as a wrong password does. pam_wrapper's idea
(cwrap.org), with util-linux alone. Where user namespaces are off, those
files are skipped, and the skip names why.

A stack can also be run as greetd's worker runs it, without Quickshell:
`harness/converse.py SERVICE USER` (libpam through ctypes) answers each
question from a JSON list on stdin and prints what PAM said and returned.
`dotfiles/security/test_login_screen.Conversations` runs etc/pam.d/greetd
that way, and `installer/security/test_finger_stacks.py` sudo's and polkit's
as phase 4 leaves them, pam_fprintd replaced by a stand-in reader (pam_exec)
or by a module that is not there.

**greetd** (`harness/greetd.py`). The greetd-ipc(7) protocol on a socket in
`GREETD_SOCK`, scripted by user name, and every request written to
`GREETD_LOG` for the test to read back. `start_session` is recorded and
never answered: Quickshell quits once a session started, so each file
with a successful login logs in once, last.

**Nextcloud** (`harness/nextcloud.py`). CalDAV and Login Flow v2 on
127.0.0.1, which the helpers take as loopback, recording every request with
its Authorization; any path can redirect or answer something else. `Elsewhere`
records whatever reaches another origin; one on 127.0.0.2 stands for plain
http on another host, since the helpers do not take that address for
loopback. What reaches either must be nothing.

**Root** (`dotfiles/security/test_login_screen.py`). The Lock Screen tab
runs root's copy of `install-greeter.sh` (which `install-system.sh` puts in
`/usr/local/lib/jupiter/greeter`) through pkexec, with `--from` the owner's
clone. The test makes that copy, then runs it as root of a user namespace
with subordinate ids (`unshare --map-auto`, newuidmap), a fake
`/etc/passwd` naming the owner, her home and clone hers and a folder root's,
and stand-ins bound over `/etc/greetd` and `/etc/pam.d`: what she cannot
read must not reach the installed tree, and what runs as root must be
root's copy, whatever her clone says.

**The VM** (`vm/`). QEMU with KVM, OVMF with Secure Boot on a fresh copy of
its variables (Setup Mode: no keys), swtpm for a TPM 2.0, and the Arch ISO's
kernel started directly with the serial console on, which `rig.Machine`
reads and types on (`expect`, `send`, `login`, `sh`). Disks are sparse raw
images, so the host compares one byte for byte and `clone()` copies a
machine at no cost on Btrfs. The VM reaches the host at 10.0.2.2, where
`rig.Mirror` serves the installer's working tree as a tarball and stands in
for an Arch mirror: the databases fetched once a day, the packages from the
host's cache or fetched once into `~/.cache/jupiter-testing/packages`.
`install.installed()` answers phase 1 on the console and keeps the
powered-off machine in `~/.cache/jupiter-testing/vm/<name>-<key>`, the key
being the installer's files and the answers, so a scenario starts from a
clone of it and only a changed installer installs again. A failing
scenario's clone stays, with `serial-<n>.log` per boot. Skipped, naming
what is missing, without qemu, swtpm, KVM, OVMF or the ISO.

## The security model

What the security suites hold the code to, and where:

- **Lock screen**: only PAM's success unlocks, from the password or a finger;
  no IPC, shortcut or other file unlocks; the password goes through
  `/etc/pam.d/login`; while PAM checks it the lock says so and Enter again
  answers nothing; a second question waits for its own answer; a shell
  restarted while locked locks at once; while locked Hyprland runs no bind
  but the media keys', and the tablet's pad, which goes around Hyprland,
  presses nothing. (`test_lock_screen.py`, `qml/Lock*Test.qml`,
  `qml/TabletLockTest.qml`)
- **Login screen**: no attempt without a password, except where
  greeter-env.py found a reader the one the greeter begins as it opens and
  Enter on an empty field, which answer the password's question with
  nothing; only that empty answer reaches pam_fprintd, whose success alone
  ends the stack and whose failure ends the login uncounted; a typed
  password never reaches the reader, and one entered while it scans goes
  after it, as a login of its own; on an encrypted disk (disk-encrypted)
  it never reaches gnome-keyring, which would encrypt the plain login
  keyring with it; without finger-asked the
  password works, without pam_fprintd an empty answer fails; a wrong one
  starts nothing, PAM's words are shown, a question waits for its answer and another
  user ends it, only a listed session starts, as its argv; only people with a
  login shell are offered, by name alone; greetd runs the greeter as
  `greeter`, whose compositor runs nothing else; the PAM stacks let no one in
  unasked; Apply runs root's copy of the installer, which takes greetd's
  config and the PAM stacks from that copy whatever the clone says, reads the
  clone and the owner's files as the owner, installs no file that is no
  image, and nothing anyone else can write.
  (`test_login_screen.py`, `qml/Greeter*Test.qml`)
- **Nextcloud**: the app password goes to the configured server only, over
  https or loopback, never through a redirect, an href or a principal that
  points elsewhere, never in argv, stdout or an error; the browser is sent to
  https only; the keyring gets the password on stdin; a task is marked done
  only at an address in a calendar of that server. (`test_nextcloud.py`,
  `qml/CalendarAddressTest.qml`)
- **Text from outside**: each `Text` on a surface showing it sets its format,
  and the notification body, the one StyledText, has no image.
  (`test_outside_text.py`, `qml/NotificationBodyTest.qml`)
- **Users** (installer): no taken, reserved or malformed name; passwords as
  typed, on chpasswd's stdin; one administrator, through wheel and a valid
  sudo rule only root reads; the ESP root's; phases 3 and 4 refuse root; what
  it fetches over https; the firewall opened to local networks only.
  (`installer/security/test_user_management.py`)
- **Disks** (installer): the disk passphrase as typed, on cryptsetup's stdin
  alone, never in argv, a file or the output; a disk not chosen (one with a
  partition table or file system, one in use) never named by a command; a
  data disk only after its own yes, at a folder of its own, opened by a
  random key file only root reads, never written over.
  (`installer/security/test_disks.py`)
- **TPM** (installer): no enrolment without a TPM 2.0, Secure Boot on with
  the system's own keys, and this boot started from the signed kernel
  image; bound to PCR 7 and PCR 15 zero, nothing else; the recovery key
  passes through the step's own hands never; a header backup the user's
  alone. (`installer/security/test_tpm_binding.py`; end to end in the VM:
  `vm/test_install.Tpm`)
- **Keyring** (installer): on an unencrypted root, no keyring made and none
  re-keyed; on an encrypted one, a login keyring made 0600 in a 0700 folder;
  one there never written over or deleted; an encrypted one re-keyed only
  when asked, from the desktop, through gnome-keyring's own dialog (no
  password passes through the installer), a copy kept, and left as it was
  when the dialog is dismissed. (`installer/security/test_keyring.py`)
- **sudo and polkit** (installer): with phase 4's finger line first, a
  finger or the password lets you in and nothing else, with or without
  pam_fprintd. (`installer/security/test_finger_stacks.py`)
- **NixOS** (Jupiter-nixos): no password or passphrase in an argument or a
  file phase 1 writes (settings.json would reach the world-readable store),
  passwords on chpasswd's stdin inside the new system; greetd's stacks the
  dotfiles' line for line, with modules and helpers by store path, every
  include a stack that exists; the local login they include counted by
  pam_faillock, never `sufficient`, without keyring or finger; `login` gives
  gnome-keyring nothing; a finger in sudo and polkit only; KDE Connect's
  ports from the local networks only; finger-asked asks for a finger on an
  empty answer only, with no PATH. (`nixos/security/`)

## Mutations

A security test is only worth what it catches. To prove one, break the code
it guards in a copy and run the test against the copy:

```bash
mut=$(mktemp -d) && cp -r ../Jupiter-dotfiles/{.config,etc,scripts} "$mut"
sed -i 's/if (result === PamResult.Success) {/if (true) {/' \
    "$mut/.config/quickshell/services/LockService.qml"
JUPITER_DOTFILES=$mut python3 -m harness.qml dotfiles/security/qml/LockPasswordTest.qml
```

It must fail. Each suite here was written that way: every guard in
LockService, GreeterService, the Nextcloud helpers, install-greeter.sh,
greeter-env.py, etc/pam.d/greetd, phase 1 and phase 4's tpm.py, keyring.py
and finger lines was broken once, and a test failed. The installer's the
same way, through `JUPITER_INSTALLER`. The few that
survive are noted where they are tested (a guard behind another guard).

## Pitfalls

Each of these has already cost a test run.

- The VM: the console reader searches only new text (`SEARCH_BACK`); a
  pattern like `(.*?)marker` over a long output re-searched it all on every
  read and starved the mirror's thread. pacman's progress bars on a
  115200-baud console stall its downloads: the phases run through `tee`.
  The ISO's reflector rewrites the mirror list after boot (masked). Without
  the console's type and size on the kernel command line, systemd waits on
  terminal queries a second or two per boot. cryptsetup flushes what is typed
  before it turns echo off (`answer_secret` waits). Once the keys are
  enrolled the unsigned ISO boots only with Secure Boot off. A Unix socket's
  path must stay under 108 bytes (`sockets()`).
- The VM's boot times: the initramfs's 1.2 s are 0.15 s of TPM measurement
  before the unlock, 0.43 s of unseal and activation, and a 0.34 s pause of
  systemd's own mount-table watcher (a built-in rate limit). Initramfs size,
  compression, preloaded modules and masking measurement units gained
  nothing measurable.

- A wait that passes on an idle machine can fail beside fifteen other tests:
  wait on the event itself (`tryVerify()` on what the stand-in records), and
  slow the stand-in down to prove it (`fixtures/LockCheckingTest/`).
- A helper killed with SIGKILL saves no coverage: stop it with `terminate()`.
- A server's `shutdown()` waits for its loop to look again (`serve_forever`
  polls every half second by default; `harness/nextcloud.py` passes 0.01).

- `FileView` in a test reads with `blockAllReads: true` and `reload()`, or
  `text()` answers from before the write (the dotfiles' Quickshell pitfall).
- A flag that is true for a moment (`LockService.fingerprint` between two
  attempts) cannot be polled: count what the stand-in records instead.
- A test that counts what was sent counts within its own attempt
  (`thisLogin()`), not over the whole log of a file that ran others before.
- Quickshell's greetd client logs the session greetd ends after a failure
  as an unexpected answer, and its error on a refused login as a warning:
  tests that cause either `ignoreWarning()` it.
- A subclass of a TestCase inherits its tests: share a fixture through a
  base class that has none (`installer/test_phase1.Installing`).
- Files chowned to a subordinate uid cannot be removed by the test: the
  namespace that chowned them hands them back before it ends.
- Under zsh, an unquoted `$VAR` holding a command is one word (`${=VAR}`).
- qmllint counts a member read off what `createObject()` returns (a
  `QObject`) as a warning and prints nothing for it, so lint fails with an
  empty report: cast it (`as GlassHighlight`); `qmllint --json -` shows what
  it counted.
- `bootstrap.sh` ends on `</dev/tty`, which a test's process does not have:
  `installer/test_bootstrap.py` gives each run a terminal of its own
  (`pty.fork()`).
- `Hyprland --verify-config` wants an `XDG_RUNTIME_DIR`, and reads the state
  the config loads (`blur.lua`): `dotfiles/test_blur_options.py` gives it
  both in a temporary folder.
