# Flatpak

`io.github.ProfetGit.Deckhand.yml` builds with flatpak-builder (org.kde.Platform 6.11, `com.riverbankcomputing.PyQt.BaseApp`, libusb and hidapi from source).

Tested: the build succeeds, appstream composes, inside the sandbox `deckhand mcp status` runs, libhidapi loads, QtSvg/QtNetwork/QtDBus import and the app starts (offscreen).
Not tested: talking to a real deck, tray, KWin profile switching, Now Playing from the sandbox.

Known limits inside the sandbox:
- Actions that run host programs (Run Command, Type Text via `wl-copy`, Screenshot via Spectacle, Open App, mute via `pactl`, Toggle Monitor via `kscreen-doctor`) cannot see the host's tools. They would need `flatpak-spawn --host`, which requires `--talk-name=org.freedesktop.Flatpak` and is not accepted on Flathub.
- The udev rules for the deck and `/dev/uinput` still have to be installed on the host.

For that reason the native packages (Arch `PKGBUILD`, `pipx`) are the recommended install.
