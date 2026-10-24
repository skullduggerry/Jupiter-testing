# Project structure

The map of the repo and the rules the code alone does not show. How to
write tests: `.github/llm.md`.

## Repo

| Path | What |
| --- | --- |
| `harness/` | what the suites share: where the repos are, helpers loaded by path, stand-in commands (`__init__.py`), the QML runner (`qml.py`, with `qml/TestCase.qml` and `qml/shell.qml`), the PAM sandbox (`pam.py`), a stand-in greetd (`greetd.py`), a stand-in Nextcloud (`nextcloud.py`), and reading sources (`source.py`) |
| `dotfiles/` | Jupiter-dotfiles' tests: `test_<helper>.py` per helper script, `test_qml.py` running `qml/*Test.qml` |
| `dotfiles/security/` | the lock screen, the login screen, the Nextcloud account, text from outside; QML tests in `qml/`, their fixtures in `qml/fixtures/` |
| `installer/` | Jupiter-installer's tests: the phases against stand-ins |
| `installer/security/` | who phase 1 makes a user, with which password and rights; root checks, firewall, sources |
| `scripts/` | `check.sh` (lint, then the suites), `test.sh` (the suites under coverage), `install-hooks.sh` |
| `pyproject.toml`, `.editorconfig` | ruff, mypy (strict) and coverage, as the tested repos set theirs |

Each test module also runs alone: `python3 -m unittest dotfiles.test_shelf`.

## Running

```bash
scripts/check.sh                 # formatting, qmllint, ruff, mypy, shellcheck, then test.sh
scripts/check.sh --fix           # format and apply the safe lint fixes first
scripts/test.sh                  # every suite, under coverage, each repo at its floor
scripts/test.sh dotfiles         # one repo's (its own check.sh runs this)
scripts/test.sh --security       # the security suites alone
python3 -m unittest dotfiles.security.test_lock_screen -k Restore
python3 -m harness.qml dotfiles/security/qml/LockPasswordTest.qml
scripts/install-hooks.sh         # once per clone: pre-commit formats, pre-push checks
```

`test.sh` runs every module under coverage of both repos (coverage's `.pth`
reads `COVERAGE_PROCESS_START`, so a helper started as a process measures
itself) and notes every bash script a test starts (`BASH_ENV`). It fails on
a helper of the repo no test runs, and on a repo whose Python lines the
suites run less of than its floor (`floors` in `test.sh`); the tested repos'
own tooling (`check.sh`, `install-hooks.sh`, the dotfiles' lint helpers,
`bootstrap.sh`) is left out. It names any package it is missing, among them
python-dateutil, which the calendar helper imports.

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
`bin/` (its PATH), and anything else beside the test (a stand-in
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

## The security model

What the security suites hold the code to, and where:

- **Lock screen**: only PAM's success unlocks, from the password or a finger;
  no IPC, shortcut or other file unlocks; the password goes through
  `/etc/pam.d/login`; a second question waits for its own answer; a shell
  restarted while locked locks at once; while locked Hyprland runs no bind
  but the media keys', and the tablet's pad, which goes around Hyprland,
  presses nothing. (`test_lock_screen.py`, `qml/Lock*Test.qml`,
  `qml/TabletLockTest.qml`)
- **Login screen**: no attempt without a password, a wrong one starts
  nothing, PAM's words are shown, a question waits for its answer and another
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
greeter-env.py and phase 1 was broken once, and a test failed. The few that
survive are noted where they are tested (a guard behind another guard).

## Pitfalls

Each of these has already cost a test run.

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
