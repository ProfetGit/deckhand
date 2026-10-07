"""Evdev key tables and a uinput virtual keyboard (works on Wayland, no root needed with ACL)."""
import fcntl
import os
import struct
import threading
import time

MODS = {"ctrl": 29, "shift": 42, "alt": 56, "meta": 125}
MOD_LABEL = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "meta": "Super"}
MOD_ORDER = ["ctrl", "alt", "shift", "meta"]

_ROWS = [
    ("QWERTYUIOP", 16),
    ("ASDFGHJKL", 30),
    ("ZXCVBNM", 44),
]
LABELS = {}
for _row, _start in _ROWS:
    for _i, _c in enumerate(_row):
        LABELS[_start + _i] = _c
for _i, _c in enumerate("1234567890"):
    LABELS[2 + _i] = _c
for _i in range(10):
    LABELS[59 + _i] = f"F{_i + 1}"
LABELS[87] = "F11"
LABELS[88] = "F12"
for _i in range(12):
    LABELS[183 + _i] = f"F{13 + _i}"
LABELS.update({
    1: "Esc", 12: "-", 13: "=", 14: "Backspace", 15: "Tab", 26: "[", 27: "]", 28: "Enter",
    39: ";", 40: "'", 41: "`", 43: "\\", 51: ",", 52: ".", 53: "/", 57: "Space", 86: "<",
    102: "Home", 103: "Up", 104: "PgUp", 105: "Left", 106: "Right", 107: "End", 108: "Down",
    109: "PgDn", 110: "Insert", 111: "Delete", 99: "PrtSc", 70: "ScrLk", 119: "Pause", 58: "CapsLock",
    69: "NumLock", 96: "Num Enter", 98: "Num /", 55: "Num *", 74: "Num -", 78: "Num +", 83: "Num .",
    82: "Num 0", 79: "Num 1", 80: "Num 2", 81: "Num 3", 75: "Num 4", 76: "Num 5", 77: "Num 6",
    71: "Num 7", 72: "Num 8", 73: "Num 9", 127: "Menu",
    163: "Next Track", 165: "Prev Track", 164: "Play/Pause", 166: "Stop", 113: "Mute",
    114: "Vol-", 115: "Vol+", 248: "Mic Mute",
})
CODES_BY_LABEL = {v: k for k, v in LABELS.items()}

KEY_PLAYPAUSE, KEY_NEXT, KEY_PREV, KEY_STOP = 164, 163, 165, 166
KEY_MUTE, KEY_VOLDOWN, KEY_VOLUP = 113, 114, 115
KEY_V = 47


def hotkey_label(hk):
    if not hk or not hk.get("code"):
        return ""
    parts = [MOD_LABEL[m] for m in MOD_ORDER if m in hk.get("mods", [])]
    parts.append(hk.get("label") or LABELS.get(hk["code"], f"#{hk['code']}"))
    return " + ".join(parts)


UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_SETUP = 0x405C5503
UI_DEV_CREATE = 0x5501
EV_SYN, EV_KEY = 0, 1


class Keyboard:
    def __init__(self):
        self.fd = None
        self.lock = threading.Lock()

    def _open(self):
        if self.fd is not None:
            return
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        for code in range(1, 256):
            fcntl.ioctl(fd, UI_SET_KEYBIT, code)
        setup = struct.pack("<HHHH80sI", 0x06, 0x0FD9, 0xDECC, 1, b"Deckhand virtual keyboard", 0)
        fcntl.ioctl(fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        time.sleep(0.25)
        self.fd = fd

    def _emit(self, code, value):
        os.write(self.fd, struct.pack("llHHi", 0, 0, EV_KEY, code, value))
        os.write(self.fd, struct.pack("llHHi", 0, 0, EV_SYN, 0, 0))

    def tap(self, codes, mods=()):
        """Press modifiers then keys, release in reverse."""
        with self.lock:
            self._open()
            seq = [MODS[m] for m in MOD_ORDER if m in mods] + list(codes)
            for c in seq:
                self._emit(c, 1)
                time.sleep(0.012)
            time.sleep(0.02)
            for c in reversed(seq):
                self._emit(c, 0)
                time.sleep(0.012)

    def hotkey(self, hk):
        if hk and hk.get("code"):
            self.tap([hk["code"]], hk.get("mods", []))

    def available(self):
        return os.access("/dev/uinput", os.W_OK)


keyboard = Keyboard()
