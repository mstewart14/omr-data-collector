# Installers

The `Installers` workflow (`.github/workflows/installers.yml`) builds four
downloads, each on its own system:

| System | Download | Made with |
| --- | --- | --- |
| Windows 10 and 11 (64-bit) | `OMR-Data-Collector-<version>-Windows-Setup.exe` | PyInstaller, then Inno Setup |
| macOS 15 and later, Apple Silicon | `OMR-Data-Collector-<version>-macOS-arm64.dmg` | PyInstaller, then `hdiutil` |
| macOS 15 and later, Intel | `OMR-Data-Collector-<version>-macOS-x86_64.dmg` | PyInstaller, then `hdiutil` |
| Linux, x86-64 | `OMR-Data-Collector-<version>-Linux-x86_64.AppImage` | PyInstaller, then appimagetool |

Each is then installed on a fresh machine, which runs
`omr-data-collector --self-check <report>`. That lays out a one-question form, draws
it filled in and scans it, so a library missing from the bundle fails the build.
On Linux it also opens the app on a virtual X11 display and types into it, since
the self-check runs offscreen and never loads the keyboard libraries.

It runs on pull requests and pushes to `main` that change this folder,
`pyproject.toml` or `uv.lock`, and on demand from the Actions tab (Run workflow).
The downloads are on the run's page as artifacts.

## Making a release

1. Set `version` in `pyproject.toml` (say `0.2.0`), commit and push.
2. Tag that commit and push the tag: `git tag v0.2.0 && git push origin v0.2.0`.
   The tag must match the version, or the build stops.
3. When the workflow finishes, a draft release with the three downloads and notes
   from the commits is waiting under Releases. Check it, then publish it.

## Building one yourself

On the system you're building for, from the repository root:

```bash
uv sync --group packaging
uv run pyinstaller --noconfirm packaging/omr-data-collector.spec
# then one of:
packaging/linux/build_appimage.sh 0.1.0
packaging/macos/build_dmg.sh 0.1.0
iscc /DAppVersion=0.1.0 packaging\windows\omr-data-collector.iss   # Inno Setup 6
```

The results are in `dist/`. `uv sync` without `--group packaging` removes
PyInstaller again.

`omr-data-collector.spec` is the PyInstaller recipe for all three. It bundles the
vendored OMRChecker (as its `src` package), the translations and the icons, and
leaves out pyzbar and easyocr, which OMRChecker only imports for field types our
templates never use. Qt stays as separate library files beside the app, as its
licence (LGPL) asks.

## Unsigned for now

The downloads aren't signed by a registered developer yet, so the first time:

- **Windows** says "Windows protected your PC": choose **More info**, then
  **Run anyway**.
- **macOS** says the app can't be opened because Apple can't check it. Open
  **System Settings > Privacy & Security**, scroll down to the message about
  OMR Data Collector and choose **Open Anyway**.
- **Linux** needs the file marked as a program: `chmod +x` it, or tick "Allow
  executing file as program" in its properties.

Signing needs an Apple Developer account (for signing and notarizing the Mac app)
and a Windows code-signing certificate; both slot into the workflow's build job.

## Notes

- **Linux** is built on Ubuntu 22.04: an AppImage runs on systems with the same
  or newer C library (glibc 2.35), so building on an older system reaches more.
  Qt's GTK theme plugin is left out, because GTK from the build machine clashes
  with the desktop's own; Qt draws its own style instead. `libxkbcommon` is left
  out too, so it comes from the desktop along with `libxkbcommon-x11`: the two
  must be the same version, and a mismatch crashes the app on the first key
  pressed under X11.
- **Macs** get two disk images, each built on its own kind of Mac
  (`macos-latest` for Apple Silicon, `macos-15-intel` for Intel), since OpenCV
  has no single build for both. Both need macOS 15 or later (`MINIMUM_MACOS` in
  the workflow): PySide6 6.11's own libraries are built for it, though its
  wheels are labelled for macOS 13. `packaging/macos/check_minimum_macos.sh`
  reads the oldest macOS each bundled library runs on and fails the build if
  any needs a newer one, so an update can't quietly drop older Macs.
- Pinned downloads (appimagetool, its runtime and Inno Setup) are checked against
  their SHA-256 sums; change the sum with the version.
- **Data** isn't in the install folder: the app keeps it in the system's per-user
  app data folder, so upgrading or uninstalling leaves it alone.
