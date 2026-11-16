#!/usr/bin/env bash
# Lint and test the Jupiter repos. Every repo has a check.sh of this name
# that takes these arguments: Jupiter-dotfiles' and Jupiter-installer's hand
# them to this one.
#
#     ./check.sh [check|lint|test] [all|dotfiles|installer|nixos|testing|PATH ...]
#                [--fix] [--staged] [--security] [-k PATTERN]
#
#     ./check.sh                 the repo you are in (all three outside them)
#     ./check.sh check all       dotfiles, installer, testing (and nixos, if cloned)
#     ./check.sh lint dotfiles   formatting and linters only, one repo
#     ./check.sh test            the suites only
#     ./check.sh --fix           format, and apply the safe fixes, first
#     ./check.sh ~/src/dots      a clone by its path, whichever repo it is
#     --staged                   lint only what git has staged
#     --security, -k PATTERN     the security suites, the tests by name
#
# The repos are found next to this one, or at JUPITER_DOTFILES,
# JUPITER_INSTALLER and JUPITER_NIXOS. Each repo is linted by
# scripts/lint.sh, with its own settings, then scripts/test.sh runs the
# suites of all of them at once. See
# "Running" in .github/PROJECT_STRUCTURE.md.
set -uo pipefail

testing=$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")" && pwd) || exit 2
dotfiles=$(realpath -m "${JUPITER_DOTFILES:-$testing/../Jupiter-dotfiles}")
installer=$(realpath -m "${JUPITER_INSTALLER:-$testing/../Jupiter-installer}")
nixos=$(realpath -m "${JUPITER_NIXOS:-$testing/../Jupiter-nixos}")

usage() {
    sed -n '6,17s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
}

# Which repo a clone is, by what only it has.
kind_of() {
    if [[ -f $1/.config/quickshell/shell.qml ]]; then
        echo dotfiles
    elif [[ -f $1/flake.nix && -f $1/jupiter_nixos/__main__.py ]]; then
        echo nixos
    elif [[ -f $1/jupiter/__main__.py ]]; then
        echo installer
    elif [[ -f $1/harness/qml.py ]]; then
        echo testing
    else
        return 1
    fi
}

# A clone by its path: the repo it is, checked where it is.
take() {
    local kind
    kind=$(kind_of "$1") || return 1
    case $kind in
        dotfiles) dotfiles=$1 ;;
        installer) installer=$1 ;;
        nixos) nixos=$1 ;;
        testing) [[ $1 == "$testing" ]] || {
            echo "check.sh: $1 is another clone of Jupiter-testing: run its own check.sh" >&2
            exit 2
        } ;;
    esac
    kinds+=("$kind")
}

arguments=("$@")
# All of them: Jupiter-nixos where it is cloned, as it is new.
everything=(dotfiles installer testing)
[[ -d $nixos ]] && everything+=(nixos)
lint=1
test=1
lint_args=()
test_args=()
kinds=()
case ${1-} in
    check) shift ;;
    lint)
        test=0
        shift
        ;;
    test)
        lint=0
        shift
        ;;
esac
while (($#)); do
    case $1 in
        -h | --help)
            usage
            exit 0
            ;;
        --fix | --staged) lint_args+=("$1") ;;
        --security) test_args+=("$1") ;;
        -k)
            [[ -n ${2-} ]] || {
                echo "check.sh: -k needs a pattern" >&2
                exit 2
            }
            test_args+=(-k "$2")
            shift
            ;;
        all) kinds+=("${everything[@]}") ;;
        dotfiles | installer | nixos | testing) kinds+=("$1") ;;
        -*)
            echo "check.sh: unknown option: $1 (see --help)" >&2
            exit 2
            ;;
        *)
            if ! path=$(realpath -e "$1" 2>/dev/null) || ! take "$path"; then
                echo "check.sh: unknown repo: $1 (dotfiles, installer, nixos, testing, all, or a clone's path)" >&2
                exit 2
            fi
            ;;
    esac
    shift
done
if ((! ${#kinds[@]})); then
    # The repo you are in, wherever its clone is; all three outside them.
    if top=$(git rev-parse --show-toplevel 2>/dev/null) && kind_of "$top" >/dev/null; then
        if [[ $(kind_of "$top") == testing && $top != "$testing" && -x $top/check.sh ]]; then
            exec "$top/check.sh" "${arguments[@]}"
        fi
        take "$top"
    else
        kinds=("${everything[@]}")
    fi
fi
mapfile -t kinds < <(printf '%s\n' "${kinds[@]}" | sort -u)
export JUPITER_DOTFILES=$dotfiles JUPITER_INSTALLER=$installer JUPITER_NIXOS=$nixos
declare -A repos=([dotfiles]=$dotfiles [installer]=$installer [nixos]=$nixos [testing]=$testing)
for kind in "${kinds[@]}"; do
    if [[ ! -d ${repos[$kind]} ]]; then
        echo "check.sh: no Jupiter-$kind at ${repos[$kind]}: clone it next to Jupiter-testing, or set JUPITER_${kind^^}" >&2
        exit 2
    fi
done

failed=()
if ((lint)); then
    for kind in "${kinds[@]}"; do
        "$testing/scripts/lint.sh" "$kind" "${repos[$kind]}" "${lint_args[@]}"
        case $? in
            0) ;;
            1) failed+=("lint $kind") ;;
            *) exit 2 ;; # a tool is missing, which it said
        esac
    done
fi
if ((test)); then
    "$testing/scripts/test.sh" "${kinds[@]}" "${test_args[@]}"
    case $? in
        0) ;;
        1) failed+=("tests") ;;
        *) exit 2 ;;
    esac
fi

echo
if ((${#failed[@]})); then
    echo "FAILED: $(printf '%s, ' "${failed[@]}" | sed 's/, $//')"
    exit 1
fi
echo "all checks passed: ${kinds[*]}"
