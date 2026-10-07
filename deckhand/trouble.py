"""What to tell (and offer) the user for each way the Stream Deck can be unavailable.

States come from hardware.scan(): scanning, ok, none, busy, denied, unsupported, nolib, error.
Offline is a first-class mode: the editor, profiles and agents keep working; keys are pushed to the
deck the moment it appears.
"""
from .errors import LOG_FILE

UDEV_RULE_CMD = (
    "printf '%s\\n' 'SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"0fd9\", TAG+=\"uaccess\"' "
    "'KERNEL==\"hidraw*\", ATTRS{idVendor}==\"0fd9\", TAG+=\"uaccess\"' "
    "| sudo tee /etc/udev/rules.d/70-deckhand-streamdeck.rules >/dev/null "
    "&& sudo udevadm control --reload-rules && sudo udevadm trigger"
)
UINPUT_RULE_CMD = (
    "echo 'KERNEL==\"uinput\", SUBSYSTEM==\"misc\", TAG+=\"uaccess\", OPTIONS+=\"static_node=uinput\"' "
    "| sudo tee /etc/udev/rules.d/70-deckhand-uinput.rules >/dev/null "
    "&& sudo udevadm control --reload-rules && sudo udevadm trigger"
)
HIDAPI_CMD = "sudo pacman -S hidapi"

SCANNING = {"state": "scanning", "title": "Looking for your Stream Deck…", "detail": "", "devices": [], "culprits": [], "scans": 0}


def guide(info):
    """{summary, steps[list[str]], command|None, level} for a status info dict."""
    st = info.get("state", "scanning")
    names = ", ".join(c["name"] for c in info.get("culprits", []))
    if st == "ok":
        return {"summary": f"{info.get('title', 'Stream Deck')} connected.", "steps": [], "command": None, "level": "ok"}
    if st == "scanning":
        return {"summary": "Looking for your Stream Deck…", "steps": [], "command": None, "level": "info"}
    if st == "none":
        return {"level": "info", "command": "lsusb | grep -i elgato",
                "summary": "No Stream Deck detected. Plug it in and Deckhand connects by itself. You can keep editing meanwhile.",
                "steps": ["Plug the Stream Deck straight into a USB port on the computer (not an unpowered hub).",
                          "Use a data cable: some cables only charge.",
                          "Run the command below. If nothing is listed, Linux does not see the device at all: try another port or cable.",
                          "Once it is listed, Deckhand connects within a couple of seconds, or press Retry."]}
    if st == "busy":
        who = names or "Another program"
        extra = []
        if any(c["name"] == "StreamController" for c in info.get("culprits", [])):
            extra = ["To stop StreamController from starting at login, remove ~/.config/autostart/StreamController.desktop."]
        return {"level": "warn", "command": None,
                "summary": f"{who} is using your Stream Deck. Close it and Deckhand connects automatically. You can keep editing meanwhile.",
                "steps": [f"Close {who}. Only one program can control the deck at a time.",
                          "If it keeps coming back, check its tray icon or autostart settings.", *extra]}
    if st == "denied":
        return {"level": "warn", "command": UDEV_RULE_CMD,
                "summary": "Linux is not letting Deckhand use the Stream Deck (USB permissions). One command fixes it.",
                "steps": ["Run the command below in a terminal. It adds a rule that gives you access to the deck.",
                          "Unplug the Stream Deck and plug it back in.",
                          "Deckhand connects by itself afterwards."]}
    if st == "unsupported":
        return {"level": "warn", "command": None,
                "summary": f"{info.get('detail') or 'This device is not supported yet.'}",
                "steps": ["Supported today: Stream Deck (original V2 and MK.2, 15 keys) and Stream Deck XL (32 keys).",
                          "The Stream Deck +, Pedal, Neo and Mini use different protocols that are not implemented yet."]}
    if st == "nolib":
        return {"level": "error", "command": HIDAPI_CMD,
                "summary": "Deckhand needs the hidapi library to talk to USB devices and it is not installed.",
                "steps": ["Run the command below, then press Retry."]}
    return {"level": "error", "command": None,
            "summary": f"{info.get('title', 'Something went wrong')}. {info.get('detail', '')}".strip(),
            "steps": ["Unplug the Stream Deck, wait a few seconds and plug it back in.",
                      f"If it keeps happening, the details are in {LOG_FILE}."]}
