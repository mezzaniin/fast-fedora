#!/bin/bash
# Installiert FAST systemweit (braucht root).  Deinstallieren: sudo ./install.sh --uninstall
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PREFIX=/usr
SHARE=$PREFIX/share/fast
LIBEXEC=$PREFIX/libexec/fast

if [[ $EUID -ne 0 ]]; then
    exec sudo "$0" "$@"
fi

if [[ ${1:-} == "--uninstall" ]]; then
    rm -rf "$SHARE" "$LIBEXEC"
    rm -f "$PREFIX/bin/fast" \
          "$PREFIX/share/polkit-1/actions/de.pattiit.fast.policy" \
          "$PREFIX/share/applications/de.pattiit.Fast.desktop"
    echo "FAST wurde entfernt."
    exit 0
fi

# Abhängigkeiten (auf Fedora Workstation meist schon vorhanden)
dnf5 install -y --setopt=install_weak_deps=False \
    python3-gobject gtk4 libadwaita polkit >/dev/null

rm -rf "$SHARE"
install -d "$SHARE" "$LIBEXEC"
cp -r fast "$SHARE/"
find "$SHARE" -name __pycache__ -prune -exec rm -rf {} +
install -m 0755 bin/fast "$PREFIX/bin/fast"
install -m 0755 -o root -g root helper/fast-helper "$LIBEXEC/fast-helper"
install -m 0644 data/de.pattiit.fast.policy "$PREFIX/share/polkit-1/actions/"
install -m 0644 data/de.pattiit.Fast.desktop "$PREFIX/share/applications/"
command -v restorecon >/dev/null && restorecon -R "$SHARE" "$LIBEXEC" "$PREFIX/bin/fast" || true
command -v update-desktop-database >/dev/null && update-desktop-database -q || true

echo "FAST ist installiert. Start über das App-Menü oder mit: fast"
