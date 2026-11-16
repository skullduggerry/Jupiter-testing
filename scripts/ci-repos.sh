#!/usr/bin/env bash
# Lay out every Jupiter repo next to each other for CI, each by what it is:
#
#     scripts/ci-repos.sh CHECKOUT BRANCH
#
# CHECKOUT is the repo the push was to, checked out in the current folder; it
# is renamed after what it holds (Jupiter-dotfiles, Jupiter-installer for
# Arch, Jupiter-nixos, Jupiter-testing), and the others are cloned beside it,
# so check.sh finds all four where it looks. Each comes from BRANCH where its
# repo has a branch of that name holding that kind, else from the default
# branch: work spread over the repos on one branch is checked together, and
# both installers are always there. A clone is told by its files, never by
# its repo's name: while NixOS is a branch of Jupiter-installer, that branch
# cannot stand in for the Arch installer, nor main for NixOS.
#
# NixOS comes from Jupiter-nixos where that repo exists, else from the
# branch of Jupiter-installer named by NIXOS_BRANCH. JUPITER_GITHUB (the
# repos' owner on GitHub) stands in for GitHub in the tests.
set -euo pipefail

checkout=${1:?usage: ci-repos.sh CHECKOUT BRANCH}
branch=${2:?usage: ci-repos.sh CHECKOUT BRANCH}
github=${JUPITER_GITHUB:-https://github.com/skullduggerry}
# Until Jupiter-nixos exists: the branch of Jupiter-installer it lives on.
nixos_branch=${NIXOS_BRANCH:-ccr-a6d5cab5-1nuyph}
export GIT_TERMINAL_PROMPT=0

# What a clone holds, by what only that kind has (check.sh's kind_of).
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

# Whether a repo has a branch, without cloning it; a repo that does not
# exist has none.
has_branch() {
    git ls-remote --exit-code --heads "$github/$1.git" "$2" >/dev/null 2>&1
}

# Clone the first of REPO@REF... (REF empty: the default branch) that holds
# KIND into Jupiter-KIND; fail naming them all if none does.
fetch() {
    local kind=$1 dir=Jupiter-$1 candidate repo ref tried=()
    shift
    for candidate; do
        repo=${candidate%@*} ref=${candidate#*@}
        if [[ -n $ref ]] && ! has_branch "$repo" "$ref"; then
            continue
        fi
        tried+=("$candidate")
        rm -rf "$dir.part"
        git clone --quiet --depth 1 ${ref:+--branch "$ref"} \
            "$github/$repo.git" "$dir.part" 2>/dev/null || continue
        if [[ $(kind_of "$dir.part" || true) == "$kind" ]]; then
            mv "$dir.part" "$dir"
            echo "$dir: $repo@${ref:-$(git -C "$dir" rev-parse --abbrev-ref HEAD)} $(git -C "$dir" rev-parse --short HEAD)"
            return
        fi
    done
    rm -rf "$dir.part"
    echo "ci-repos.sh: found no $kind in: $* (cloned: ${tried[*]:-none})" >&2
    exit 2
}

kind=$(kind_of "$checkout") || {
    echo "ci-repos.sh: $checkout is no Jupiter repo" >&2
    exit 2
}
if [[ $checkout != "Jupiter-$kind" ]]; then
    mv "$checkout" "Jupiter-$kind"
fi
echo "Jupiter-$kind: the push, $branch $(git -C "Jupiter-$kind" rev-parse --short HEAD)"

[[ -d Jupiter-dotfiles ]] ||
    fetch dotfiles "Jupiter-dotfiles@$branch" "Jupiter-dotfiles@"
[[ -d Jupiter-testing ]] ||
    fetch testing "Jupiter-testing@$branch" "Jupiter-testing@"
[[ -d Jupiter-installer ]] ||
    fetch installer "Jupiter-installer@$branch" "Jupiter-installer@"
[[ -d Jupiter-nixos ]] ||
    fetch nixos "Jupiter-nixos@$branch" "Jupiter-nixos@" \
        "Jupiter-installer@$branch" "Jupiter-installer@$nixos_branch"
