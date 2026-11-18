#!/usr/bin/env bash
# One repo's formatting and linters, by that repo's own settings.
#
#     scripts/lint.sh KIND PATH            KIND is dotfiles, installer or testing
#     scripts/lint.sh KIND PATH --fix      format, and apply the safe fixes, first
#     scripts/lint.sh KIND PATH --staged   only the files git has staged
#
# check.sh runs this for each repo it checks, then the suites. The
# tools run inside PATH, so they read its pyproject.toml, .editorconfig and
# .luarc.json, which editors read too. Formatters: qmlformat, ruff, shfmt and
# stylua, and nixfmt for the installer's NixOS side. Linters: qmllint (against Quickshell's types as
# scripts/quickshell-types.py corrects them), ruff, mypy, shellcheck and, for
# the dotfiles, lua-language-server and Hyprland's own config check, with the
# project's rules besides (qmldirs, popup names, glyphs), and statix and
# deadnix for Nix.
set -uo pipefail

testing=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd) || exit 2
kind=${1-}
repo=$(realpath -e "${2-}" 2>/dev/null) || {
    echo "usage: lint.sh dotfiles|installer|testing PATH [--fix] [--staged]" >&2
    exit 2
}
shift 2
[[ $kind == @(dotfiles|installer|testing) ]] || {
    echo "lint.sh: unknown repo kind: $kind" >&2
    exit 2
}
cd "$repo" || exit 2
# The QML is Qt 6; /usr/bin/qmlformat and qmllint are Qt 5's (qt5-declarative)
# and misparse it.
PATH=/usr/lib/qt6/bin:$PATH
dotfiles=$(realpath -m "${JUPITER_DOTFILES:-$testing/../Jupiter-dotfiles}")
installer=$(realpath -m "${JUPITER_INSTALLER:-$testing/../Jupiter-installer}")
[[ $kind == dotfiles ]] && dotfiles=$repo
[[ $kind == installer ]] && installer=$repo

fix=0
staged=0
for arg in "$@"; do
    case $arg in
        --fix) fix=1 ;;
        --staged) staged=1 ;;
        *)
            echo "lint.sh: unknown option: $arg" >&2
            exit 2
            ;;
    esac
done

# Each tool, and the package it comes in.
declare -A packages=(["ruff"]=ruff ["mypy"]=mypy ["shellcheck"]=shellcheck ["shfmt"]=shfmt)
case $kind in
    dotfiles)
        packages+=(
            ["/usr/lib/qt6/bin/qmlformat"]=qt6-declarative ["Hyprland"]=hyprland
            ["luac"]=lua ["stylua"]=stylua ["lua-language-server"]=lua-language-server
            ["zsh"]=zsh
        )
        ;;
    testing) packages+=(["/usr/lib/qt6/bin/qmlformat"]=qt6-declarative) ;;
esac
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
    echo "== $kind: $1"
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
# staged ones. Links are checked as what they point to.
files() {
    if ((staged)); then
        git diff --cached --name-only --diff-filter=ACMR -- "$@"
    else
        git ls-files --cached --others --exclude-standard -- "$@"
    fi | while read -r f; do
        [[ -f $f && ! -L $f ]] && printf '%s\n' "$f"
    done
}
qml=()
lua=()
nix=()
data_spec=('*.json' '*.toml')
case $kind in
    dotfiles)
        mapfile -t qml < <(files '*.qml')
        mapfile -t shell < <(files '*.sh' '.config/uwsm/env')
        mapfile -t lua < <(files '*.lua' ':!.config/wallust/templates/*')
        data_spec+=(':!.config/wallust/templates/*')
        ;;
    installer)
        mapfile -t shell < <(files '*.sh')
        mapfile -t nix < <(files '*.nix')
        ;;
    testing)
        mapfile -t qml < <(files '*.qml')
        mapfile -t shell < <(files '*.sh' '.githooks/*')
        ;;
esac
mapfile -t python < <(files '*.py')

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
        *.lua) stylua --stdin-filepath "$1" - <"$1" ;;
        *.nix) nixfmt --filename "$1" <"$1" ;;
        *) shfmt "$1" ;;
    esac
}

jobs=$(nproc)
# lua-language-server takes a while over the whole tree, so it starts now
# and its section waits for it.
if ((${#lua[@]})); then
    lua-language-server --check="$repo" --checklevel=Information --check_format=json \
        --logpath="$tmp/luals" >/dev/null 2>&1 &
    luals=$!
fi

section "formatting (qmlformat, ruff, shfmt, stylua, nixfmt)"
# nixfmt is optional here, as Arch has no package of it; CI has it (from Nix).
if ((${#nix[@]})) && ! command -v nixfmt >/dev/null; then
    echo "  skip  nixfmt is not installed: ${#nix[@]} Nix files not checked (nix profile install nixpkgs#nixfmt)"
    nix=()
fi
# Every file through its formatter, as many at once as there are CPUs; then
# whatever differs is fixed or reported, in order.
export -f formatted
# With none to format (a commit of documents alone), printf alone would
# still print one empty name.
names() { (($#)) && printf '%s\0' "$@"; }
# shellcheck disable=SC2016 # expanded by the bash each part runs in
names "${qml[@]}" "${python[@]}" "${shell[@]}" "${lua[@]}" "${nix[@]}" |
    xargs -0 -r -P "$jobs" -n 8 bash -c '
        for f; do
            # The dots keep trailing newlines, which $( ) strips: blank
            # lines at the end count as a difference.
            if ! out=$(formatted "$f" 2>/dev/null && printf .); then
                echo "unparsed $f"
            elif [[ $out != "$(cat -- "$f" && printf .)" ]]; then
                echo "unformatted $f"
            fi
        done' _ | sort -k2 >"$tmp/formatting"
while read -r state f; do
    if [[ $state == unparsed ]]; then
        formatted "$f" >/dev/null 2>"$tmp/out"
        failed "$f does not parse"
    elif fixable "$f"; then
        out=$(formatted "$f") && printf '%s\n' "$out" >"$f" && fixed "$f"
    elif ((fix)); then
        fail "$f is not formatted and has unstaged changes: format it, then stage it"
    else
        fail "$f is not formatted (run with --fix)"
    fi
done <"$tmp/formatting"
passed "$((${#qml[@]} + ${#python[@]} + ${#shell[@]} + ${#lua[@]} + ${#nix[@]})) files"

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

if ((${#qml[@]})); then
    section "qmllint"
    # Against Quickshell's type information with its packaging slips fixed,
    # and any warning fails. The login screen is linted as installed, beside
    # a copy of style/, and the QML tests as harness/qml.py stages them.
    # Paths are absolute: Qt 6.12's qmllint matches a file against its qmldir
    # by absolute path, and warns about every singleton given a relative one.
    lint=$tmp/lint
    mkdir "$lint"
    if [[ ! -d $dotfiles/.config/quickshell ]]; then
        fail "no Jupiter-dotfiles at $dotfiles to lint against: clone it next to Jupiter-testing, or set JUPITER_DOTFILES"
    elif ! "$testing/scripts/quickshell-types.py" "$lint/types" 2>"$tmp/out"; then
        failed "scripts/quickshell-types.py"
    else
        cp -r "$dotfiles/etc/greetd/quickshell" "$lint/greeter"
        cp -r "$dotfiles/.config/quickshell/style" "$lint/greeter/style"
        targets=()
        if [[ $kind == dotfiles ]]; then
            for f in "${qml[@]}"; do
                if [[ $f == etc/greetd/quickshell/* ]]; then
                    targets+=("$lint/greeter/${f#etc/greetd/quickshell/}")
                else
                    targets+=("$repo/$f")
                fi
            done
        else
            mkdir "$lint/tests"
            cp -r "$dotfiles/.config/quickshell" "$lint/shell"
            cp harness/qml/*.qml "$lint/tests/"
            for f in "${qml[@]}"; do
                [[ $f == harness/qml/* ]] || cp "$f" "$lint/tests/"
                targets+=("$lint/tests/$(basename "$f")")
            done
        fi
        # In as many parts as there are CPUs, each writing its own report.
        mkdir "$tmp/qmllint"
        # shellcheck disable=SC2016 # expanded by the bash each part runs in
        if printf '%s\0' "${targets[@]}" |
            xargs -0 -P "$jobs" -n $(((${#targets[@]} + jobs - 1) / jobs)) bash -c '
                report=$(mktemp -p "$0")
                qmllint --bare -I "$1" -I /usr/lib/qt6/qml --max-warnings 0 \
                    --unused-imports warning "${@:2}" >"$report" 2>&1' \
                "$tmp/qmllint" "$lint/types"; then
            passed "${#targets[@]} files"
        else
            cat "$tmp/qmllint"/* >"$tmp/out"
            sed -i "s#$repo/##g; s#$lint/greeter#etc/greetd/quickshell#g; s#$lint/tests/##g; s#$lint/##g" "$tmp/out"
            failed "qmllint"
        fi
    fi
fi

if [[ $kind == dotfiles ]]; then
    section "qmldir completeness"
    while read -r dir; do
        for f in "$dir"/*.qml; do
            [[ -e $f ]] || continue
            name=$(basename "$f" .qml)
            [[ $name == shell ]] && continue
            grep -q "[[:space:]]$name\.qml\$" "$dir/qmldir" || fail "$name.qml missing from $dir/qmldir"
        done
    done < <(find .config/quickshell etc/greetd -name qmldir -printf '%h\n' 2>/dev/null)
    passed "every qml declared in its qmldir"

    section "popup namespaces (hyprland blur rule)"
    # .config/hypr/styles/layout.lua blurs ^quickshell:.*-popup$ only. A popup
    # named anything else silently renders unblurred.
    while read -r line; do
        suffix=${line#*namespaceSuffix: \"}
        suffix=${suffix%\"*}
        [[ $suffix == *-popup ]] || fail "namespaceSuffix '$suffix' will not match the blur rule"
    done < <(grep -rh 'namespaceSuffix: "' .config/quickshell --include='*.qml')
    passed "all popup namespaces end in -popup"

    section "pasted glyphs"
    if pasted=$("$testing/scripts/pasted-glyphs.py" "$repo"); then
        passed "every glyph is a \\u{...} escape"
    else
        fail "pasted glyphs, write them as \\u{...}: ${pasted//$'\n'/ }"
    fi

    section "icon family (lucide)"
    # One icon set: every glyph is one of icons/Icons.qml's, in its font. A
    # Nerd Font escape (U+F0000 and up) is the old set, and would draw in the
    # text font.
    if nerd=$(grep -rln '\\u{F[0-9A-Fa-f]\{4\}}' .config/quickshell etc/greetd --include='*.qml'); then
        fail "Nerd Font glyphs, use icons/Icons.qml: ${nerd//$'\n'/ }"
    else
        passed "no Nerd Font glyphs"
    fi
fi

section "python (ruff, mypy)"
if ((${#python[@]})); then
    if ((fix)); then
        for f in "${python[@]}"; do
            fixable "$f" || continue
            before=$(<"$f")
            # A fix (an import taken out) can leave it to be formatted again.
            ruff check --fix --quiet "$f" >/dev/null && ruff format --quiet "$f"
            [[ $(<"$f") != "$before" ]] && fixed "$f"
        done
    fi
    ruff check --quiet --output-format concise "${python[@]}" >"$tmp/out" 2>&1 || failed "ruff"
    # The tests import the installers, and check their types with theirs.
    mypypath=
    [[ $kind == testing ]] && mypypath=$installer
    MYPYPATH=$mypypath mypy --no-error-summary "${python[@]}" >"$tmp/out" 2>&1 || failed "mypy"
fi
passed "${#python[@]} files"

if ((${#lua[@]})); then
    section "lua (luac, lua-language-server)"
    for f in "${lua[@]}"; do
        luac -p -- "$f" 2>"$tmp/out" || failed "$f does not parse"
    done
    # The whole tree, as a module's callers matter to it: started above.
    wait "$luals"
    python3 - "$tmp/luals/check.json" "$repo" >"$tmp/out" <<'EOF' || failed "lua-language-server"
import json, sys, urllib.parse
problems = json.load(open(sys.argv[1]))
for uri, diagnostics in (problems or {}).items():
    path = urllib.parse.unquote(uri.removeprefix("file://")).removeprefix(sys.argv[2] + "/")
    for problem in diagnostics:
        line = problem["range"]["start"]["line"] + 1
        message = problem["message"].splitlines()[0]
        print(f"{path}:{line}: {message} [{problem['code']}]")
sys.exit(1 if problems else 0)
EOF
    passed "${#lua[@]} files"
fi

section "shell (shellcheck)"
if ((${#shell[@]})); then
    shellcheck --format=gcc "${shell[@]}" >"$tmp/out" 2>&1 || failed "shellcheck"
fi
if [[ $kind == dotfiles ]]; then
    while read -r f; do
        zsh -n "$f" 2>"$tmp/out" || failed "$f does not parse"
    done < <(files '.config/.zshrc')
fi
passed "${#shell[@]} files"

section "json and toml"
mapfile -t data < <(files "${data_spec[@]}")
python3 - "${data[@]}" >"$tmp/out" <<'EOF' || failed "json or toml that does not parse"
import json, sys, tomllib
broken = 0
for path in sys.argv[1:]:
    with open(path, "rb") as file:
        try:
            (tomllib.load if path.endswith(".toml") else json.load)(file)
        except ValueError as error:
            print(f"{path}: {error}")
            broken += 1
sys.exit(broken)
EOF
passed "${#data[@]} files"

# The workflows CI runs, the shell in them through shellcheck. Optional here,
# as Arch desktops have no actionlint yet; CI installs it.
mapfile -t workflows < <(files '.github/workflows/*.yml')
if ((${#workflows[@]})); then
    section "workflows (actionlint)"
    if ! command -v actionlint >/dev/null; then
        echo "  skip  actionlint is not installed"
    else
        actionlint "${workflows[@]}" >"$tmp/out" 2>&1 || failed "actionlint"
        passed "${#workflows[@]} files"
    fi
fi

# Nix beyond its formatting: statix's lints (configured by the repo's
# statix.toml) and deadnix's unused bindings. Optional like nixfmt; CI has both.
mapfile -t nixfiles < <(files '*.nix')
if ((${#nixfiles[@]})); then
    section "nix (statix, deadnix)"
    if ! command -v statix >/dev/null || ! command -v deadnix >/dev/null; then
        echo "  skip  statix or deadnix is not installed (nix profile install nixpkgs#statix nixpkgs#deadnix)"
    else
        (cd "$repo" && statix check -o errfmt .) >"$tmp/out" 2>&1 || failed "statix"
        (cd "$repo" && deadnix --fail "${nixfiles[@]}") >"$tmp/out" 2>&1 || failed "deadnix"
        passed "${#nixfiles[@]} files"
    fi
fi

if [[ $kind == dotfiles ]]; then
    section "hyprland configs"
    # Hyprland's own parser, which also rejects unknown rule fields and wrong
    # types; luac and lua-language-server only see the code.
    for config in .config/hypr/hyprland.lua etc/greetd/hyprland.lua; do
        if Hyprland --verify-config -c "$repo/$config" 2>&1 | grep -q 'config ok'; then
            ok "$config"
        else
            fail "$config does not verify"
        fi
    done
fi

echo
if ((failures)); then
    echo "lint $kind: $failures problem(s)"
    exit 1
fi
echo "lint $kind: ok"
