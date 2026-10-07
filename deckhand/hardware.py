"""Stream Deck USB driver (HID via libhidapi, no Python deps) and hotplug manager."""
import ctypes
import ctypes.util
import os
import threading
import time
from dataclasses import dataclass

VID = 0x0FD9


@dataclass(frozen=True)
class Model:
    name: str
    cols: int
    rows: int
    px: int

    @property
    def keys(self):
        return self.cols * self.rows


MODELS = {
    0x006D: Model("Stream Deck", 5, 3, 72),
    0x0080: Model("Stream Deck MK.2", 5, 3, 72),
    0x00A5: Model("Stream Deck MK.2", 5, 3, 72),
    0x006C: Model("Stream Deck XL", 8, 4, 96),
    0x008F: Model("Stream Deck XL", 8, 4, 96),
}


class _Info(ctypes.Structure):
    pass


_Info._fields_ = [
    ("path", ctypes.c_char_p),
    ("vendor_id", ctypes.c_ushort),
    ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p),
    ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p),
    ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort),
    ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int),
    ("next", ctypes.POINTER(_Info)),
]

_lib = None


def _hid():
    global _lib
    if _lib is None:
        lib = None
        for name in ("libhidapi-libusb.so.0", "libhidapi-hidraw.so.0"):
            try:
                lib = ctypes.CDLL(name)
                break
            except OSError:
                continue
        if lib is None:
            raise RuntimeError("libhidapi not found (install hidapi)")
        lib.hid_init()
        lib.hid_enumerate.restype = ctypes.POINTER(_Info)
        lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
        lib.hid_free_enumeration.argtypes = [ctypes.POINTER(_Info)]
        lib.hid_open_path.restype = ctypes.c_void_p
        lib.hid_open_path.argtypes = [ctypes.c_char_p]
        lib.hid_close.argtypes = [ctypes.c_void_p]
        lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.hid_read_timeout.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
        lib.hid_send_feature_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.hid_get_feature_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        _lib = lib
    return _lib


def enumerate_devices():
    lib = _hid()
    out = []
    head = lib.hid_enumerate(VID, 0)
    node = head
    while node:
        i = node.contents
        if i.product_id in MODELS and i.interface_number in (0, -1):
            out.append((i.path, i.product_id, i.serial_number or ""))
        node = i.next
    if head:
        lib.hid_free_enumeration(head)
    return out


class Device:
    REPORT = 1024
    HEADER = 8

    def __init__(self, path, pid, serial):
        self.lib = _hid()
        self.path = path
        self.pid = pid
        self.model = MODELS[pid]
        self.serial = serial
        self.dev = self.lib.hid_open_path(path)
        if not self.dev:
            raise OSError("cannot open device (in use by another app?)")
        self.lock = threading.Lock()
        self.alive = True

    def close(self):
        with self.lock:
            if self.dev:
                self.lib.hid_close(self.dev)
                self.dev = None
        self.alive = False

    def _feature(self, data):
        data = bytes(data).ljust(32, b"\0")
        with self.lock:
            if self.dev:
                self.lib.hid_send_feature_report(self.dev, data, len(data))

    def set_brightness(self, percent):
        self._feature([0x03, 0x08, max(0, min(100, int(percent)))])

    def reset(self):
        self._feature([0x03, 0x02])

    def _read_feature(self, rid, tries=1):
        for _ in range(tries):
            buf = ctypes.create_string_buffer(32)
            buf[0] = rid
            with self.lock:
                n = self.lib.hid_get_feature_report(self.dev, buf, 32) if self.dev else -1
            if n > 2:
                text = buf.raw[2:n] if rid == 6 else buf.raw[6:n]
                text = text.split(b"\0")[0].decode(errors="ignore")
                if text.isprintable() and text:
                    return text
            time.sleep(0.12)
        return ""

    def firmware(self):
        """One attempt only: a freshly reset deck can take ~1s per feature request, so never call this
        on the connect path (Preferences reads it on a background thread)."""
        v = self._read_feature(5)
        return v if v[:1].isdigit() and "." in v else ""

    def serial_number(self):
        return self._read_feature(6) or self.serial

    def set_key_image(self, key, jpeg):
        payload = self.REPORT - self.HEADER
        page = 0
        pos = 0
        total = len(jpeg)
        with self.lock:
            if not self.dev:
                return
            while pos < total:
                chunk = jpeg[pos:pos + payload]
                last = 1 if pos + len(chunk) >= total else 0
                hdr = bytes([0x02, 0x07, key, last, len(chunk) & 0xFF, len(chunk) >> 8, page & 0xFF, page >> 8])
                r = self.lib.hid_write(self.dev, hdr + chunk.ljust(payload, b"\0"), self.REPORT)
                if r < 0:
                    raise OSError("write failed")
                pos += len(chunk)
                page += 1

    def read_keys(self, timeout_ms=100):
        buf = ctypes.create_string_buffer(512)
        n = self.lib.hid_read_timeout(self.dev, buf, 512, timeout_ms) if self.dev else -1
        if n < 0:
            raise OSError("read failed")
        if n == 0 or buf[0] != b"\x01":
            return None
        return [bool(b) for b in buf.raw[4:4 + self.model.keys]]


KNOWN_NAMES = {
    0x0060: "Stream Deck (original)", 0x0063: "Stream Deck Mini", 0x006C: "Stream Deck XL", 0x006D: "Stream Deck",
    0x0080: "Stream Deck MK.2", 0x0084: "Stream Deck +", 0x0086: "Stream Deck Pedal", 0x008F: "Stream Deck XL",
    0x0090: "Stream Deck Mini MK.2", 0x009A: "Stream Deck Neo", 0x00A5: "Stream Deck MK.2",
}
RIVAL_APPS = ("streamcontroller", "streamdeck-ui", "streamdeck_ui", "opendeck", "deckmaster", "streamdeckd", "elgato")
SYSFS_USB = "/sys/bus/usb/devices"


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def usb_devices():
    """Elgato USB devices that are plugged in, straight from sysfs (works even when we cannot open them)."""
    out = []
    try:
        names = os.listdir(SYSFS_USB)
    except OSError:
        return out
    for n in names:
        base = os.path.join(SYSFS_USB, n)
        if _read(os.path.join(base, "idVendor")).lower() != f"{VID:04x}":
            continue
        try:
            pid = int(_read(os.path.join(base, "idProduct")), 16)
            bus, dev = int(_read(os.path.join(base, "busnum"))), int(_read(os.path.join(base, "devnum")))
        except ValueError:
            continue
        out.append({"sysname": n, "pid": pid, "serial": _read(os.path.join(base, "serial")),
                    "name": KNOWN_NAMES.get(pid, f"Elgato device {VID:04x}:{pid:04x}"), "supported": pid in MODELS,
                    "node": f"/dev/bus/usb/{bus:03d}/{dev:03d}"})
    return sorted(out, key=lambda d: d["sysname"])


def find_rivals():
    """Other programs that typically hold the deck: [{pid, name}]."""
    me = os.getpid()
    found = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return found
    for p in pids:
        if int(p) == me:
            continue
        try:
            with open(f"/proc/{p}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode(errors="ignore").lower()
        except OSError:
            continue
        if "-m deckhand" in cmd or "deckhand/__main__" in cmd:
            if " mcp" not in cmd and not any(f["pid"] == int(p) for f in found):
                found.append({"pid": int(p), "name": "another Deckhand window"})
            continue
        if "deckhand" in cmd:
            continue
        for token in RIVAL_APPS:
            if token in cmd.split(" ")[0] or (token in cmd and "python" in cmd[:60]):
                name = {"streamcontroller": "StreamController", "streamdeck-ui": "streamdeck-ui", "streamdeck_ui": "streamdeck-ui",
                        "opendeck": "OpenDeck", "elgato": "the Elgato software"}.get(token, token)
                if not any(f["pid"] == int(p) for f in found):
                    found.append({"pid": int(p), "name": name})
                break
    return found


def _info(state, title, detail="", **kw):
    return {"state": state, "title": title, "detail": detail, "devices": [], "culprits": [], "target": None, **kw}


def scan(preferred_serial=""):
    """Work out the deck situation and why it is (not) usable. Never raises."""
    try:
        try:
            _hid()
        except RuntimeError as e:
            return _info("nolib", "USB support is missing", str(e))
        usb = usb_devices()
        devices = [{"name": d["name"], "serial": d["serial"], "supported": d["supported"]} for d in usb]
        if not usb:
            return _info("none", "No Stream Deck found", "Nothing from Elgato is plugged in.", devices=devices)
        sup = [d for d in usb if d["supported"]]
        if not sup:
            names = ", ".join(sorted({d["name"] for d in usb}))
            return _info("unsupported", "This Stream Deck is not supported yet", f"Found {names}. Deckhand supports the Stream Deck "
                         "(original V2 / MK.2) and the XL.", devices=devices)
        pick = next((d for d in sup if preferred_serial and d["serial"] == preferred_serial), sup[0])
        if not os.access(pick["node"], os.R_OK | os.W_OK):
            return _info("denied", "Deckhand is not allowed to use the Stream Deck", f"No permission for {pick['node']}.", devices=devices, pick=pick)
        # Open by sysfs path ("3-2.1:1.0"). hid_enumerate() would read string descriptors from every
        # USB device and can stall for many seconds while a deck is busy or re-enumerating.
        iface = next((n for n in sorted(os.listdir(SYSFS_USB)) if n.startswith(pick["sysname"] + ":")), None)
        if not iface:
            return _info("error", "The Stream Deck is plugged in but cannot be read", "Try unplugging and re-plugging it.", devices=devices, pick=pick)
        info = _info("found", pick["name"], "", devices=devices, pick=pick)
        info["target"] = (iface.encode(), pick["pid"], pick["serial"])
        return info
    except Exception as e:
        return _info("error", "Looking for the Stream Deck failed", f"{e.__class__.__name__}: {e}")


class Manager:
    """Owns the connection: finds the deck, reconnects, and reports key presses.

    Status callbacks receive one info dict (see _info); callbacks run on the worker thread.
    Whatever happens, this thread keeps scanning: no deck, a busy deck, a permission problem or an
    unexpected exception are all just states, never the end of the loop.
    """

    def __init__(self, on_connect, on_disconnect, on_key, on_status):
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_key = on_key
        self.on_status = on_status
        self.dev = None
        self.preferred = ""
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._drop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(2)
        if self.dev:
            try:
                self.dev.close()
            except Exception:
                pass

    def retry(self):
        """Scan again right now (the Retry button)."""
        self._wake.set()

    def reconnect(self):
        """Drop the current connection and pick the device again (after choosing another deck)."""
        self._drop.set()
        self._wake.set()

    def _sleep(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()

    def _run(self):
        last = None
        misses = 0
        t0 = time.monotonic()
        while not self._stop.is_set():
            info = scan(self.preferred)
            dev = None
            if info["target"]:
                try:
                    dev = Device(*info["target"])
                except Exception as e:
                    rivals = find_rivals()
                    if rivals:
                        names = ", ".join(r["name"] for r in rivals)
                        info = _info("busy", f"{names} is using the Stream Deck", "Only one program can control the deck at a time.",
                                     devices=info["devices"], culprits=rivals)
                    elif not os.access(info["pick"]["node"], os.R_OK | os.W_OK):
                        info = _info("denied", "Deckhand is not allowed to use the Stream Deck", f"No permission for {info['pick']['node']}.",
                                     devices=info["devices"])
                    else:
                        info = _info("busy", "The Stream Deck is busy", f"Could not open it ({e}). Another program may be using it.",
                                     devices=info["devices"])
            if dev is None:
                misses += 1
                info["scans"] = misses
                key = (info["state"], info["title"], info["detail"])
                if key != last:
                    last = key
                    self.on_status(info)
                self._sleep(1.5 if time.monotonic() - t0 < 90 else 4.0)
                continue
            misses = 0
            self.dev = dev
            ok = _info("ok", dev.model.name, "", devices=info["devices"], scans=0)
            last = (ok["state"], ok["title"], ok["detail"])
            self.on_status(ok)
            self._drop.clear()
            try:
                self.on_connect(dev)
                prev = [False] * dev.model.keys
                while not self._stop.is_set() and not self._drop.is_set():
                    states = dev.read_keys(60)
                    if states is None:
                        continue
                    for i, (a, b) in enumerate(zip(prev, states)):
                        if a != b:
                            self.on_key(i, b)
                    prev = states
            except Exception:
                pass
            finally:
                self.dev = None
                try:
                    dev.close()
                except Exception:
                    pass
                self.on_disconnect()
            t0 = time.monotonic()
            last = None
            self._sleep(0.6)
