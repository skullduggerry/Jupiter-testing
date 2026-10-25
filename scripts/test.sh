#!/usr/bin/env bash
# The suites, under coverage of the repos they test.
#
#     scripts/test.sh                  every repo's, the tested ones at their floors
#     scripts/test.sh dotfiles         one repo's (dotfiles, installer or testing)
#     scripts/test.sh --security       the security suites alone, no coverage floor
#     scripts/test.sh dotfiles -k Lock the tests matching a pattern (no floor)
#
# The repos are found next to this one, or at JUPITER_DOTFILES and
# JUPITER_INSTALLER; testing/ holds the harness's own tests. harness/run.py
# runs every test in a process of its own, as many at once as there are
# CPUs. Every Python process a test starts measures itself (coverage's .pth
# file reads COVERAGE_PROCESS_START), and every bash script notes that it ran
# (BASH_ENV): a helper no test runs fails, and so does a repo whose lines the
# suites run less of than its floor. check.sh lints first and then
# runs this; see "Running" in .github/PROJECT_STRUCTURE.md.
set -uo pipefail

testing=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd) || exit 2
cd "$testing" || exit 2
JUPITER_DOTFILES=$(realpath "${JUPITER_DOTFILES:-$testing/../Jupiter-dotfiles}" 2>/dev/null)
JUPITER_INSTALLER=$(realpath "${JUPITER_INSTALLER:-$testing/../Jupiter-installer}" 2>/dev/null)
export JUPITER_DOTFILES JUPITER_INSTALLER

# Each tested repo's floor: the share of its Python lines the suites run.
declare -A floors=([dotfiles]=90 [installer]=95)

targets=()
security=0
run_args=()
while (($#)); do
    case $1 in
        dotfiles | installer | testing) targets+=("$1") ;;
        --security) security=1 ;;
        -k)
            run_args+=(-k "${2-}")
            shift
            ;;
        *)
            echo "test.sh: unknown argument: $1" >&2
            exit 2
            ;;
    esac
    shift
done
((${#targets[@]})) || targets=(dotfiles installer testing)
floor=$((! security && ! ${#run_args[@]}))

declare -A repos=([dotfiles]=$JUPITER_DOTFILES [installer]=$JUPITER_INSTALLER [testing]=$testing)
for target in "${targets[@]}"; do
    if [[ ! -d ${repos[$target]} ]]; then
        echo "test.sh: no Jupiter-$target next to this repo; clone it there or set JUPITER_${target^^}" >&2
        exit 2
    fi
done

# Each tool, and the package it comes in; python-dateutil is the calendar
# helper's, and the rest are what the stand-ins run on.
declare -A packages=(
    ["coverage"]=python-coverage ["qs"]=quickshell ["lua"]=lua ["unshare"]=util-linux
    ["file"]=file ["setpriv"]=util-linux
)
missing=()
for tool in "${!packages[@]}"; do
    command -v "$tool" >/dev/null || missing+=("${packages[$tool]}")
done
python3 -c 'import dateutil' 2>/dev/null || missing+=(python-dateutil)
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

mkdir "$tmp/coverage"
cat >"$tmp/ran.bash" <<'EOF'
[[ -z ${CHECK_RAN-} ]] || { [[ $0 == /* ]] && printf '%s\n' "$0" || printf '%s\n' "$PWD/$0"; } >>"$CHECK_RAN"
EOF
touch "$tmp/ran"

start=$SECONDS
# One run over every repo's modules, so the CPUs never wait for one repo's
# slowest test before the next repo's start.
modules=()
for target in "${targets[@]}"; do
    folder=$target
    ((security)) && folder=$target/security
    [[ -d $folder ]] && mapfile -t -O "${#modules[@]}" modules < <(find "$folder" -name 'test_*.py' | sort)
done
heading=
((security)) && heading=", security only"
COVERAGE_PROCESS_START=$testing/pyproject.toml COVERAGE_FILE=$tmp/coverage/data \
    BASH_ENV=$tmp/ran.bash CHECK_RAN=$tmp/ran \
    python3 -m harness.run --heading "$heading" "${run_args[@]}" "${modules[@]}" ||
    failures=$((failures + 1))

if ((floor)); then
    export COVERAGE_FILE=$tmp/coverage/data
    coverage combine --quiet --rcfile=pyproject.toml "$tmp/coverage" 2>/dev/null
    coverage json --quiet --rcfile=pyproject.toml -o "$tmp/coverage.json" \
        --include="$JUPITER_DOTFILES/*,$JUPITER_INSTALLER/*" 2>/dev/null ||
        echo '{"files": {}}' >"$tmp/coverage.json"
    for target in "${targets[@]}"; do
        [[ -n ${floors[$target]-} ]] || continue
        echo
        echo "== coverage: $target"
        repo=${repos[$target]}
        # A helper no test runs is a feature nothing checks: give it a test.
        # The files there are, a deletion not yet committed left out.
        if [[ $target == dotfiles ]]; then
            spec=('*.py' '*.sh')
        else
            spec=('jupiter/*.py' ':!jupiter/__init__.py')
        fi
        mapfile -t helpers < <(git -C "$repo" ls-files --cached --others --exclude-standard -- "${spec[@]}" |
            while read -r f; do [[ -f $repo/$f ]] && printf '%s\n' "$f"; done)
        if python3 - "$tmp/coverage.json" "$tmp/ran" "$repo" "${helpers[@]}" >"$tmp/out" <<'EOF'
import json, os, sys
measured = json.load(open(sys.argv[1]))["files"]
ran = {os.path.realpath(name) for name, data in measured.items() if data["executed_lines"]}
ran.update(os.path.realpath(line) for line in open(sys.argv[2]).read().splitlines())
untested = [helper for helper in sys.argv[4:] if os.path.realpath(os.path.join(sys.argv[3], helper)) not in ran]
print("\n".join(untested))
sys.exit(1 if untested else 0)
EOF
        then
            ok "every helper runs in a test"
        else
            fail "not run by any test:"
            sed 's/^/        /' "$tmp/out"
        fi
        if coverage report --rcfile=pyproject.toml --include="$repo/*" \
            --fail-under="${floors[$target]}" >"$tmp/out" 2>&1; then
            ok "python lines: $(grep '^TOTAL' "$tmp/out" | awk '{print $NF}') (floor ${floors[$target]}%)"
        else
            fail "python line coverage under ${floors[$target]}%"
            sed "s#$repo/##" "$tmp/out" | head -40 | sed 's/^/        /'
        fi
    done
fi

echo
if ((failures)); then
    echo "FAILED: $failures problem(s)"
    exit 1
fi
echo "all tests passed in $((SECONDS - start)) s"
