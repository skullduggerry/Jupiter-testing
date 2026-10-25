#!/usr/bin/env bash
# Point git in every Jupiter clone at the hooks in this repo's .githooks/,
# which check whichever repo they run in. Run once per clone of this repo;
# .git/hooks is not version controlled, core.hooksPath is. The other repos
# are found next to this one, or at JUPITER_DOTFILES and JUPITER_INSTALLER.
set -euo pipefail
testing=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
chmod +x "$testing"/.githooks/*
for repo in "$testing" "${JUPITER_DOTFILES:-$testing/../Jupiter-dotfiles}" \
    "${JUPITER_INSTALLER:-$testing/../Jupiter-installer}"; do
    if [[ -d $repo/.git ]]; then
        git -C "$repo" config core.hooksPath "$testing/.githooks"
        echo "hooks installed in $(realpath "$repo")"
    else
        echo "no clone at $repo, skipped"
    fi
done
echo "  pre-commit  formats staged files, then checks that repo"
echo "  pre-push    checks that repo, no auto-fix"
