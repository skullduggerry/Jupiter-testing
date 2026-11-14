#!/usr/bin/env bash
# Install Jupiter in a VM and check what a person would see, end to end:
#
#     scripts/vm.sh               every scenario in vm/test_install.py
#     scripts/vm.sh -k Before      the scenarios matching a pattern
#
# Needs qemu-system-x86, swtpm, edk2-ovmf, /dev/kvm and the Arch ISO at
# ~/.cache/jupiter-testing/archlinux-x86_64.iso (or JUPITER_ISO); the tests
# are skipped, naming what is missing, without them. Each install is kept in
# ~/.cache/jupiter-testing/vm until the installer changes. Not part of
# check.sh: an install takes minutes. See "The VM" in
# .github/PROJECT_STRUCTURE.md.
set -euo pipefail

testing=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$testing"
exec python3 -m unittest -v vm.test_install "$@"
