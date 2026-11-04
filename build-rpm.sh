#!/bin/bash
# Baut ein RPM von FAST (ohne root). Ergebnis liegt in ./dist/
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
VERSION=$(sed -n 's/^Version:\s*//p' fast-fedora.spec)
TOP=$(mktemp -d)
trap 'rm -rf "$TOP"' EXIT
mkdir -p "$TOP"/{SOURCES,SPECS} dist
REF=$(git stash create)  # schließt nicht committete Änderungen ein
git archive --format=tar.gz --prefix="fast-fedora-$VERSION/" \
    -o "$TOP/SOURCES/fast-fedora-$VERSION.tar.gz" "${REF:-HEAD}"
rpmbuild -bb --define "_topdir $TOP" fast-fedora.spec
find "$TOP/RPMS" -name '*.rpm' -exec cp {} dist/ \;
ls -1 dist/*.rpm
echo
echo "Installieren mit:  sudo dnf install ./dist/$(ls -t dist | head -1)"
