# Agent instructions

The tests of Jupiter-dotfiles (a Hyprland and Quickshell desktop) and
Jupiter-installer (the Arch installer that sets it up), in a repo of their
own. Read `.github/PROJECT_STRUCTURE.md` (the map, the harness and the
pitfalls) before adding a test, and the tested repo's own `.github/` before
changing anything there: its conventions are this repo's too.

The two repos are next to this one (`../Jupiter-dotfiles`,
`../Jupiter-installer`) or wherever `JUPITER_DOTFILES` and
`JUPITER_INSTALLER` point. The dotfiles are the live session: a test never
changes them, and never anything outside a temporary folder.

## Sources of truth, in order

1. The code under test and its repo's `.github/` docs.
2. This repo's harness (`harness/`) and conventions.
3. Python's `unittest` documentation, greetd-ipc(7), pam_exec(8) and the
   other manual pages of what a stand-in replaces.

## Writing tests

- One `test_<helper>.py` per helper script, beside the others for its repo
  (`dotfiles/`, `installer/`); a `<Name>Test.qml` per QML singleton's logic
  (`dotfiles/qml/`); and anything about logging in, locking, a secret, a
  user's rights or text from outside under that repo's `security/`.
- `unittest` only, as the installer has always been tested: no new
  dependency. A test class sets up a world of stand-ins (`setUp`,
  `harness.temporary()`), a test method checks one behaviour and is named
  after it, and a table of cases goes through `subTest`.
- Run the real code: the helper as the shell starts it, the QML singleton in
  Quickshell, the script under bash. Replace only what reaches the system: a
  command by a stand-in on PATH, the network by a loopback server
  (`harness/nextcloud.py`), PAM by a sandbox (`harness/pam.py`), greetd by
  a socket (`harness/greetd.py`).
- Assert what a person would notice, by value: the files written, the
  commands run with their arguments, the text shown. A failure message says
  what went wrong in the code's terms.
- A security test proves itself: break the code it guards (by hand, or in a
  copy through `JUPITER_DOTFILES`) and watch it fail, as
  PROJECT_STRUCTURE.md's "Mutations" shows. One that passes against the
  broken code tests nothing.
- What a running test cannot show, the sources can (`harness/source.py`):
  name exactly what the test looks for, so a rewrite it no longer
  understands fails rather than passes unseen.
- Comments say why, in a few lines, where the code doesn't. Docstrings say
  what a module or class covers and against which stand-ins.

## Done means

- `scripts/check.sh` passes (`--fix` formats first): formatting, qmllint,
  ruff, strict mypy, shellcheck, then every suite under coverage, each repo
  at its floor and every helper run by a test.
- A fix in a tested repo passes that repo's `scripts/check.sh` too, and for
  the dotfiles the running shell's log shows no new warning after the
  reload (the dotfiles' "Validating").
- Your report says what changed, why, how you verified it, and what you
  could not verify.
