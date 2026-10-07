#!/bin/sh
# Per-user install: launcher, desktop entry and icon. No root needed. Re-run any time; remove with --uninstall.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.local/bin/deckhand"
APP="$HOME/.local/share/applications/deckhand.desktop"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/deckhand.svg"

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$BIN" "$APP" "$ICON"
  echo "Removed launcher, desktop entry and icon. Your profiles in ~/.config/deckhand are untouched."
  exit 0
fi

mkdir -p "$(dirname "$BIN")" "$(dirname "$APP")" "$(dirname "$ICON")"
cat > "$BIN" <<LAUNCH
#!/bin/sh
cd "$ROOT" && exec python3 -m deckhand "\$@"
LAUNCH
chmod +x "$BIN"
cp "$ROOT/deckhand/assets/deckhand.svg" "$ICON"
cat > "$APP" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Deckhand
GenericName=Stream Deck Control
Comment=Configure and run your Stream Deck
Exec=$BIN
Icon=deckhand
Terminal=false
Categories=Utility;Settings;
StartupWMClass=deckhand
Keywords=streamdeck;elgato;macro;
DESKTOP
echo "Installed. Start Deckhand from your app menu or run: deckhand"
echo "Make sure ~/.local/bin is on your PATH."
