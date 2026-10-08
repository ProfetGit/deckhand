# Flatpak (draft, untested)

`io.github.ProfetGit.Deckhand.yml` is a starting point, written without `flatpak-builder` available, so it has never been built. The hidapi/libusb checksums and the PyQt base app version need checking when it is first built.

Known limits inside the sandbox, even once it builds:
- Actions that run host programs (Run Command, Type Text via `wl-copy`, Screenshot via Spectacle, Open App, mute via `pactl`, Toggle Monitor via `kscreen-doctor`) cannot see the host's tools. They would need `flatpak-spawn --host`, which requires `--talk-name=org.freedesktop.Flatpak` and is not accepted on Flathub.
- The udev rules for the deck and `/dev/uinput` still have to be installed on the host.

For that reason the native packages (Arch `PKGBUILD`, `pipx`) are the recommended install.
