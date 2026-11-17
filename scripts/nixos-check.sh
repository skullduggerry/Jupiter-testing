#!/usr/bin/env bash
# The checks only NixOS can run, on the repos laid out by ci-repos.sh in the
# current folder:
#
#     scripts/nixos-check.sh
#
# The installer's flake evaluated for hosts/example, a whole system, with
# lanzaboote and nixpkgs as its flake.lock has them and the laid-out
# dotfiles (not the lock's); the login screen's pam_exec helpers and root's
# copy of its installer built; the user's home-manager generation built,
# with Stylix's specialisation for each theme the dotfiles pre-build
# (base16/), as apply.sh activates them; the dotfiles' Hyprland configs verified by
# NixOS's Hyprland; their QML suites run in NixOS's Quickshell. Every check
# runs even after one fails, and each failure is named. CI's nixos job runs
# this, and Jupiter-installer's update of flake.lock runs it on the new lock
# before pushing it.
set -uo pipefail

root=$PWD
failed=()

flake() {
    (cd "$root/Jupiter-installer" &&
        nix "$@" --no-write-lock-file \
            --override-input dotfiles "path:$root/Jupiter-dotfiles")
}
host=path:.#nixosConfigurations.example

echo "== the system, evaluated"
if ! flake eval --raw "$host.config.system.build.toplevel.drvPath"; then
    echo "FAIL  hosts/example does not evaluate" >&2
    exit 1
fi
echo

echo "== the login screen's helpers, built"
flake build --no-link --print-out-paths \
    "$host.config.system.build.jupiter.fingerAsked" \
    "$host.config.system.build.jupiter.diskEncrypted" \
    "$host.config.system.build.jupiter.greeterRoot" ||
    failed+=("the login screen's helpers do not build")

echo "== the theme's home-manager generation, built"
user=$(flake eval --raw "$host.config.jupiter.settings.user")
if generation=$(flake build --no-link --print-out-paths \
    "$host.config.home-manager.users.$user.home.activationPackage"); then
    for scheme in "$root"/Jupiter-dotfiles/.config/wallust/base16/*.json; do
        theme=$(basename "$scheme" .json)
        [[ -x $generation/specialisation/$theme/activate ]] ||
            failed+=("the $theme theme has no specialisation for apply.sh")
    done
else
    failed+=("the theme's home-manager generation does not build")
fi

for name in hyprland quickshell python3; do
    path=$(flake build --no-link --print-out-paths "$host.pkgs.$name.out") || {
        echo "FAIL  $name does not build" >&2
        exit 1
    }
    declare "$name=$path"
done

echo "== Hyprland's config check, with NixOS's Hyprland"
# shellcheck disable=SC2154 # declared in the loop above
"$hyprland/bin/Hyprland" --version | head -1
for config in .config/hypr/hyprland.lua etc/greetd/hyprland.lua; do
    out=$(XDG_RUNTIME_DIR=$(mktemp -d) "$hyprland/bin/Hyprland" --verify-config \
        -c "$root/Jupiter-dotfiles/$config" 2>&1)
    if printf '%s\n' "$out" | grep -q 'config ok'; then
        echo "ok    $config"
    else
        printf '%s\n' "$out" | grep -iE 'error|unknown' >&2
        failed+=("$config does not verify with NixOS's Hyprland")
    fi
done

echo "== the dotfiles' QML suites, in NixOS's Quickshell"
# shellcheck disable=SC2154 # declared in the loop above
"$quickshell/bin/qs" --version
# shellcheck disable=SC2154
(cd "$root/Jupiter-testing" &&
    PATH="$quickshell/bin:$PATH" "$python3/bin/python3" -m harness.run \
        dotfiles/test_qml.py dotfiles/security/test_lock_screen.py) ||
    failed+=("the QML suites fail in NixOS's Quickshell")

echo
if ((${#failed[@]})); then
    printf 'FAIL  %s\n' "${failed[@]}" >&2
    exit 1
fi
echo "all NixOS checks passed"
