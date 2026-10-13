#!/usr/bin/env bash
# Wrap PyInstaller's dist/omr-data-collector/ in an AppImage: one file that runs
# on most Linux desktops (build on the oldest glibc you support; CI uses Ubuntu
# 22.04). Run from the repository root after PyInstaller:
#
#   packaging/linux/build_appimage.sh <version>
#
# Writes dist/OMR-Data-Collector-<version>-Linux-x86_64.AppImage.
set -euo pipefail

version=$1
tools=build/appimage-tools
appdir=build/AppDir
out="dist/OMR-Data-Collector-${version}-Linux-x86_64.AppImage"

# Pinned and checked, so a changed download can't slip into a release.
fetch() {
    local url=$1 sha256=$2 file
    file="$tools/$(basename "$url")"
    if [ ! -f "$file" ]; then
        curl --fail --location --silent --show-error --output "$file.part" "$url"
        mv "$file.part" "$file"
    fi
    echo "$sha256  $file" | sha256sum --check --quiet
    chmod +x "$file"
}
mkdir -p "$tools"
fetch https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
    ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
fetch https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64 \
    2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d

rm -rf "$appdir"
mkdir -p "$appdir/usr/lib" "$appdir/usr/share/applications"
cp -a dist/omr-data-collector "$appdir/usr/lib/omr-data-collector"
cp packaging/linux/omr-data-collector.desktop "$appdir/"
cp packaging/linux/omr-data-collector.desktop "$appdir/usr/share/applications/"
cp packaging/icons/png/256.png "$appdir/omr-data-collector.png"
for png in packaging/icons/png/*.png; do
    size=$(basename "$png" .png)
    mkdir -p "$appdir/usr/share/icons/hicolor/${size}x${size}/apps"
    cp "$png" "$appdir/usr/share/icons/hicolor/${size}x${size}/apps/omr-data-collector.png"
done
cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
here=$(dirname "$(readlink -f "$0")")
exec "$here/usr/lib/omr-data-collector/omr-data-collector" "$@"
APPRUN
chmod +x "$appdir/AppRun"

# The tool is itself an AppImage; extracting it to run needs no FUSE.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$tools/appimagetool-x86_64.AppImage" \
    --no-appstream --runtime-file "$tools/runtime-x86_64" "$appdir" "$out"
echo "$out"
