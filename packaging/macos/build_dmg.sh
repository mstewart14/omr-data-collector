#!/usr/bin/env bash
# Put PyInstaller's dist/OMR Data Collector.app in a disk image that opens
# showing the app beside an Applications shortcut to drag it onto. Run from the
# repository root after PyInstaller, on a Mac:
#
#   packaging/macos/build_dmg.sh <version>
#
# Writes dist/OMR-Data-Collector-<version>-macOS-<arch>.dmg. The app is only
# signed ad hoc (by PyInstaller), not by a registered developer, so macOS
# asks people to allow it the first time (packaging/README.md).
set -euo pipefail

version=$1
app="dist/OMR Data Collector.app"
staging=build/dmg
out="dist/OMR-Data-Collector-${version}-macOS-$(uname -m).dmg"

rm -rf "$staging" "$out"
mkdir -p "$staging"
cp -R "$app" "$staging/"
ln -s /Applications "$staging/Applications"
hdiutil create -volname "OMR Data Collector" -srcfolder "$staging" \
    -fs HFS+ -format UDZO -ov "$out"
echo "$out"
