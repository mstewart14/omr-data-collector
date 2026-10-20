#!/usr/bin/env bash
# Fail if any program or library in the app needs a newer macOS than the one
# the downloads promise. Run on a Mac after PyInstaller:
#
#   packaging/macos/check_minimum_macos.sh "dist/OMR Data Collector.app" 13.0
#
# Each Mach-O file records the oldest macOS it runs on (LC_BUILD_VERSION's
# minos, or LC_VERSION_MIN_MACOSX in older ones). A wheel built for a newer
# macOS than the rest would otherwise make the app quit at start on older Macs.
set -euo pipefail

app=$1
minimum=$2
arch=$(uname -m)
too_new=0

while IFS= read -r -d '' file; do
    file -b "$file" | grep -q "Mach-O" || continue
    needs=$(otool -arch "$arch" -l "$file" 2>/dev/null | awk '
        /LC_BUILD_VERSION/ { build = 1 }
        /LC_VERSION_MIN_MACOSX/ { legacy = 1 }
        build && $1 == "minos" { print $2; exit }
        legacy && $1 == "version" { print $2; exit }
    ')
    [ -n "$needs" ] || continue
    if [ "$(printf '%s\n%s\n' "$minimum" "$needs" | sort -V | tail -n 1)" != "$minimum" ]; then
        echo "needs macOS $needs: ${file#"$app"/}"
        too_new=1
    fi
done < <(find "$app" -type f -print0)

if [ "$too_new" -ne 0 ]; then
    echo "::error::Parts of the app need a newer macOS than $minimum"
    exit 1
fi
echo "Everything in the app runs on macOS $minimum ($arch)."
