#!/usr/bin/env bash
# This repo's checks: formatting, linters, then the suites (scripts/test.sh).
#
#     scripts/check.sh            check everything, non-zero exit on failure
#     scripts/check.sh --fix      format, and apply the linters' safe fixes, first
#     scripts/check.sh --staged   only the files git has staged (pre-commit)
#
# Formatters: qmlformat, ruff and shfmt, set up in pyproject.toml and
# .editorconfig, as Jupiter-dotfiles has them. Linters: qmllint (the QML
# tests staged as harness/qml.py stages them, against Jupiter-dotfiles'
# corrected Quickshell types), ruff, mypy (strict, Jupiter-installer's own
# types included) and shellcheck. See "Running" in .github/PROJECT_STRUCTURE.md.
set -uo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd) || exit 2
cd "$repo" || exit 2
# The QML is Qt 6; /usr/bin/qmlformat and qmllint are Qt 5's and misparse it.
PATH=/usr/lib/qt6/bin:$PATH
dotfiles=$(realpath -m "${JUPITER_DOTFILES:-$repo/../Jupiter-dotfiles}")
installer=$(realpath -m "${JUPITER_INSTALLER:-$repo/../Jupiter-installer}")

fix=0
staged=0
for arg in "$@"; do
    case $arg in
        --fix) fix=1 ;;
        --staged) staged=1 ;;
        *)
            echo "unknown option: $arg" >&2
            exit 2
            ;;
    esac
done

# Each tool, and the package it comes in.
declare -A packages=(
    ["/usr/lib/qt6/bin/qmlformat"]=qt6-declarative ["ruff"]=ruff ["mypy"]=mypy
    ["shellcheck"]=shellcheck ["shfmt"]=shfmt
)
missing=()
for tool in "${!packages[@]}"; do
    command -v "$tool" >/dev/null || missing+=("${packages[$tool]}")
done
if ((${#missing[@]})); then
    echo "Some tools are missing. Install them with:" >&2
    echo "    sudo pacman -S --needed $(printf '%s\n' "${missing[@]}" | sort -u | xargs)" >&2
    exit 2
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

failures=0
fail() {
    echo "  FAIL  $*"
    failures=$((failures + 1))
}
ok() { echo "  ok    $*"; }
section() {
    echo
    echo "== $1"
    section_start=$failures
}
# Says ok if the section failed nothing.
passed() { ((failures == section_start)) && ok "$@"; }
# Fails with a tool's output, its first lines.
failed() {
    fail "$1"
    head -40 "$tmp/out" | sed 's/^/        /'
}

# The files matching git pathspecs, new ones included, or with --staged the
# staged ones. Links (the fixtures share files) are checked as what they
# point to.
files() {
    if ((staged)); then
        git diff --cached --name-only --diff-filter=ACMR -- "$@"
    else
        git ls-files --cached --others --exclude-standard -- "$@"
    fi | while read -r f; do
        [[ -f $f && ! -L $f ]] && printf '%s\n' "$f"
    done
}
mapfile -t qml < <(files '*.qml')
mapfile -t python < <(files '*.py')
mapfile -t shell < <(files '*.sh' '.githooks/*')

# With --staged, a file is only fixed and staged again when it has no unstaged
# changes, which `git add` would stage along with the fix.
fixable() { ((fix)) && { ((! staged)) || git diff --quiet -- "$1"; }; }
fixed() {
    echo "  fixed $1"
    ((staged)) && git add -- "$1"
}

# A file as its formatter would write it.
# shellcheck disable=SC2094 # its name only tells them which settings apply
formatted() {
    case $1 in
        *.qml) qmlformat "$1" ;;
        *.py) ruff format --quiet --stdin-filename "$1" - <"$1" ;;
        *) shfmt "$1" ;;
    esac
}

section "formatting (qmlformat, ruff, shfmt)"
for f in "${qml[@]}" "${python[@]}" "${shell[@]}"; do
    if ! out=$(formatted "$f" 2>"$tmp/out"); then
        failed "$f does not parse"
    elif [[ $out != "$(<"$f")" ]]; then
        if fixable "$f"; then
            printf '%s\n' "$out" >"$f" && fixed "$f"
        elif ((fix)); then
            fail "$f is not formatted and has unstaged changes: format it, then stage it"
        else
            fail "$f is not formatted (run scripts/check.sh --fix)"
        fi
    fi
done
passed "$((${#qml[@]} + ${#python[@]} + ${#shell[@]})) files"

section "whitespace (.editorconfig)"
# Trailing whitespace, except in Markdown, where two spaces end a line.
trailing() { [[ $1 != *.md ]] && grep -qP '[ \t]+$' "$1"; }
unended() { [[ -n $(tail -c1 "$1") ]]; }
while read -r f; do
    grep -Iq . "$f" || continue # binary or empty
    if fixable "$f" && { trailing "$f" || unended "$f"; }; then
        trailing "$f" && sed -i 's/[ \t]*$//' "$f"
        unended "$f" && printf '\n' >>"$f"
        fixed "$f"
    fi
    trailing "$f" && fail "$f has trailing whitespace"
    unended "$f" && fail "$f has no final newline"
    [[ $f == *.qml ]] && grep -qP '\t' "$f" && fail "$f contains a tab"
done < <(files .)
passed "trailing whitespace, final newline, no tabs in QML"

section "qmllint"
# Every test file beside the harness, the shell and the installed greeter, as
# harness/qml.py stages them, against Quickshell's types as the dotfiles
# correct them. Any warning fails.
if [[ ! -d $dotfiles ]]; then
    fail "no Jupiter-dotfiles at $dotfiles to lint the QML tests against"
elif ((${#qml[@]})); then
    lint=$tmp/lint
    mkdir -p "$lint/tests"
    "$dotfiles/scripts/quickshell-types.py" "$lint/types"
    cp -r "$dotfiles/.config/quickshell" "$lint/shell"
    cp -r "$dotfiles/etc/greetd/quickshell" "$lint/greeter"
    cp -r "$dotfiles/.config/quickshell/style" "$lint/greeter/style"
    cp harness/qml/*.qml "$lint/tests/"
    targets=()
    for f in "${qml[@]}"; do
        [[ $f == harness/qml/* ]] || cp "$f" "$lint/tests/"
        targets+=("$lint/tests/$(basename "$f")")
    done
    if qmllint --bare -I "$lint/types" -I /usr/lib/qt6/qml --max-warnings 0 --unused-imports warning "${targets[@]}" >"$tmp/out" 2>&1; then
        passed "${#targets[@]} files"
    else
        sed -i "s#$lint/tests/##g; s#$lint/##g" "$tmp/out"
        failed "qmllint"
    fi
fi

section "python (ruff, mypy)"
if ((${#python[@]})); then
    if ((fix)); then
        for f in "${python[@]}"; do
            fixable "$f" || continue
            before=$(<"$f")
            ruff check --fix --quiet "$f" >/dev/null
            [[ $(<"$f") != "$before" ]] && fixed "$f"
        done
    fi
    ruff check --quiet --output-format concise "${python[@]}" >"$tmp/out" 2>&1 || failed "ruff"
    # The installer's own types, which its tests import.
    MYPYPATH=$installer mypy --no-error-summary "${python[@]}" >"$tmp/out" 2>&1 || failed "mypy"
fi
passed "${#python[@]} files"

section "shell (shellcheck)"
if ((${#shell[@]})); then
    shellcheck --format=gcc "${shell[@]}" >"$tmp/out" 2>&1 || failed "shellcheck"
fi
passed "${#shell[@]} files"

section "json"
mapfile -t data < <(files '*.json')
python3 - "${data[@]}" >"$tmp/out" <<'EOF' || failed "json that does not parse"
import json, sys
broken = 0
for path in sys.argv[1:]:
    try:
        json.load(open(path))
    except ValueError as error:
        print(f"{path}: {error}")
        broken += 1
sys.exit(broken)
EOF
passed "${#data[@]} files"

echo
if ((failures)); then
    echo "FAILED: $failures problem(s)"
    echo "(the suites run once the checks pass)"
    exit 1
fi
exec scripts/test.sh
