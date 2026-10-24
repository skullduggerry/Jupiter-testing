#!/usr/bin/env bash
# Point git at the tracked hooks in .githooks/ so they sync between machines.
# Run once per clone; .git/hooks is not version controlled, core.hooksPath is.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
git -C "$repo" config core.hooksPath .githooks
chmod +x "$repo"/.githooks/*
echo "hooks installed: $(git -C "$repo" config core.hooksPath)"
echo "  pre-commit  formats staged files, then checks"
echo "  pre-push    full suite, no auto-fix"
