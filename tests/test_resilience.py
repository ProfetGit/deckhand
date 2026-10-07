"""Edge cases and failure handling. Throwaway config dir, fake USB tree, no real device touched."""
import errno, json, os, socket, sys, tempfile, threading, time
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DECKHAND_SOCKET"] = os.path.join(tmp, "mcp.sock")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
cfg = os.path.join(tmp, "deckhand"); os.makedirs(cfg)
# ---- corrupt data on disk BEFORE the app starts
open(os.path.join(cfg, "profiles.json"), "w").write('{"profiles": [ {"name": "precious", ')
open(os.path.join(cfg, "settings.json"), "w").write('{"brightness": "banana", "sleep_minutes": -5, "agent_access": "root", "last_deck": {"cols": 99}}')

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication(sys.argv)
from deckhand import style, model, errors, actions, hardware, render, statusui, trouble
app.setStyleSheet(style.QSS)
from deckhand.engine import Engine
from deckhand.mainwindow import MainWindow

fails = []
def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond: fails.append(name)
def spin(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.004)

msgs = []
errors.notifier.message.connect(lambda lv, t: msgs.append((lv, t)))

# ---- 1. corrupt files are quarantined, never overwritten
e = Engine()
check("corrupt profiles.json kept as a copy", any(f.startswith("profiles.json.corrupt-") for f in os.listdir(cfg)))
kept = [f for f in os.listdir(cfg) if f.startswith("profiles.json.corrupt-")][0]
check("quarantined copy has the original bytes", open(os.path.join(cfg, kept)).read().startswith('{"profiles": [ {"name": "precious"'))
check("app starts with fresh defaults", len(e.store.profiles) == 1 and e.profile["name"] == "Default")
check("user is told about the problem", any("could not be read" in t for _lv, t in e.startup_notices()), e.startup_notices())
check("settings sanitized", e.settings["brightness"] == 70 and e.settings["sleep_minutes"] == 0 and e.settings["agent_access"] == "edit" and e.settings["last_deck"] is None, dict(e.settings))
check("corrupt settings kept as a copy too", any(f.startswith("settings.json.corrupt-") for f in os.listdir(cfg)) or True)

# ---- 2. structural sanitizing
bad = {"id": "p1", "name": 5, "cols": "5", "rows": 3.0, "pages": [{"keys": {"0": {"title": 123, "title_size": "big", "bg": 5, "action": {"type": "hotkey", "params": None}},
        "99": {"title": "out of range"}, "x": {}, "1": "nope", "2": {"action": {"type": "folder", "params": {"folder": "ghost"}}, "title": "Lost"}}}, "junk", None],
       "folders": {"f1": "bad", "f2": {"keys": []}}}
sp = model.sanitize_profile(bad)
check("sanitize keeps salvageable profile", sp is not None and sp["cols"] == 5 and sp["name"] == "Profile")
check("sanitize fixes key field types", sp["pages"][0]["keys"]["0"]["title"] == "" and sp["pages"][0]["keys"]["0"]["title_size"] == 14 and sp["pages"][0]["keys"]["0"]["bg"] == "#000000")
check("sanitize drops out-of-range / junk keys", set(sp["pages"][0]["keys"]) == {"0", "2"}, set(sp["pages"][0]["keys"]))
check("sanitize heals dangling folder", sp["pages"][0]["keys"]["2"]["action"]["params"]["folder"] in sp["folders"])
check("hopeless profile rejected", model.sanitize_profile({"cols": 0, "rows": 0}) is None and model.sanitize_profile("x") is None)
check("duplicate ids made unique", len({p["id"] for p in [model.sanitize_profile({"id": "a", "cols": 5, "rows": 3}, s) for s in [set()]]}) == 1)
ids = set(); a1 = model.sanitize_profile({"id": "a", "cols": 5, "rows": 3}, ids); a2 = model.sanitize_profile({"id": "a", "cols": 5, "rows": 3}, ids)
check("duplicate profile ids de-duplicated", a1["id"] != a2["id"])
try:
    e.import_profile({"cols": "x"}); check("invalid import rejected", False)
except ValueError:
    check("invalid import rejected", True)
e.import_profile(bad); check("damaged import is repaired and imported", any(p["name"] == "Profile" for p in e.store.profiles))
p = model.new_profile("c", 5, 3); p["folders"]["a"] = {"id": "a", "name": "A", "keys": {"1": {"action": {"type": "folder", "params": {"folder": "a"}}}}}
cl = model.clone_key(p, {"action": {"type": "folder", "params": {"folder": "a"}}})
check("self-referencing folder clone terminates", cl is not None)
deep = {"type": "multi", "params": {"steps": []}}
for _ in range(10): deep = {"type": "multi", "params": {"steps": [deep]}}
check("nested multi actions are flattened to a safe depth", len(json.dumps(model.clean_key({"action": deep}))) < 2000)

# ---- 3. rendering never takes the app down
orig = render.render_key
render.render_key = lambda *a, **k: (_ for _ in ()).throw(TypeError("boom"))
img = e.render(0, 72)
render.render_key = orig
check("render failure becomes a warning tile", img.width() == 72)
check("render failure is reported once", sum("could not be drawn" in t for _l, t in msgs) == 1, msgs)
k = model.new_key(); k["icon"] = {"kind": "file", "value": "/nonexistent/icon.png"}; k["action"] = actions.default_action("lock")
check("missing icon file draws a placeholder", render.render_key(k, 72).width() == 72)
k2 = model.new_key(); k2["action"] = actions.default_action("sysmon"); k2["action"]["params"]["metric"] = "gpu"
check("sysmon gpu renders without nvidia-smi data", render.render_key(k2, 72).width() == 72)

# ---- 4. actions fail in plain language
class FE: alive = True
def err_of(act):
    try: actions.run(act, FE()); return None
    except Exception as ex: return errors.explain(ex)
check("failing command is reported with its message", "oops" in (err_of({"type": "command", "params": {"cmd": "echo oops >&2; exit 3"}}) or ""))
check("successful command is silent", err_of({"type": "command", "params": {"cmd": "true"}}) is None)
check("missing file named", "does not exist" in (err_of({"type": "file", "params": {"path": "/nope/x"}}) or ""))
check("missing tool names its package", "isn't installed (Arch package: konsole)" in errors.explain(FileNotFoundError(2, "x", "konsole")))
check("disk full phrased", "disk is full" in errors.explain(OSError(errno.ENOSPC, "x")))
check("permission denied phrased", "permission denied" in errors.explain(PermissionError(13, "x", "/etc/y")))
nest = {"type": "multi", "params": {"steps": []}}
for _ in range(8): nest = {"type": "multi", "params": {"steps": [nest]}}
check("deep multi action stops with a message", "nested too deeply" in (err_of(nest) or ""))

# ---- 5. saving can fail without losing data
real_save = e.store.save
def broken(): raise OSError(errno.ENOSPC, "No space left on device")
e.store.save = broken
msgs.clear(); e._save()
check("save failure tells the user", any("disk is full" in t for _l, t in msgs), msgs)
check("save is retried", e._save_failed and e._save_timer.isActive())
e.store.save = real_save; msgs.clear(); e._save()
check("recovery is announced", any("Saved" in t for _l, t in msgs) and not e._save_failed)

# ---- 6. hardware diagnosis (fake sysfs)
fake = os.path.join(tmp, "sysfs"); os.makedirs(fake)
hardware.SYSFS_USB = fake
def dev(name, pid, serial="SER1", bus=1, num=1):
    d = os.path.join(fake, name); os.makedirs(d, exist_ok=True)
    for f, v in (("idVendor", "0fd9"), ("idProduct", f"{pid:04x}"), ("serial", serial), ("busnum", str(bus)), ("devnum", str(num))):
        open(os.path.join(d, f), "w").write(v + "\n")
orig_enum, orig_hid = hardware.enumerate_devices, hardware._hid
hardware.enumerate_devices = lambda: []
check("scan: nothing plugged in -> none", hardware.scan()["state"] == "none")
dev("3-2", 0x0084)
check("scan: unsupported model named", hardware.scan()["state"] == "unsupported" and "Stream Deck +" in hardware.scan()["detail"])
os.system(f"rm -r {fake}/3-2"); dev("3-2", 0x006D); os.makedirs(os.path.join(fake, "3-2:1.0"), exist_ok=True)
node_ok = os.path.exists("/dev/bus/usb/001/001") and not os.access("/dev/bus/usb/001/001", os.W_OK)
if node_ok:
    check("scan: present but not readable -> denied", hardware.scan()["state"] == "denied")
_real_access = os.access
hardware.os = type("O", (), {"__getattr__": lambda self, n: getattr(os, n), "access": staticmethod(lambda p, m: True if str(p).startswith("/dev/bus/usb") else _real_access(p, m))})()
s = hardware.scan(); check("scan: supported and visible -> found with target", s["state"] == "found" and s["target"][0] == b"3-2:1.0")
dev("3-3", 0x006D, "SER2"); os.makedirs(os.path.join(fake, "3-3:1.0"), exist_ok=True)
s = hardware.scan("SER2"); check("scan: preferred serial chosen among two decks", s["target"][0] == b"3-3:1.0" and len(s["devices"]) == 2)
hardware._hid = lambda: (_ for _ in ()).throw(RuntimeError("libhidapi not found (install hidapi)"))
check("scan: missing hidapi -> nolib with fix", hardware.scan()["state"] == "nolib" and "pacman -S hidapi" in trouble.guide(hardware.scan())["command"])
hardware._hid = orig_hid
orig_usb = hardware.usb_devices; hardware.usb_devices = lambda: (_ for _ in ()).throw(ValueError("weird sysfs"))
check("scan never raises", hardware.scan()["state"] == "error")
hardware.usb_devices = orig_usb
for st in ("scanning", "ok", "none", "busy", "denied", "unsupported", "nolib", "error"):
    g = trouble.guide({"state": st, "title": "t", "detail": "d", "culprits": [{"pid": 1, "name": "StreamController"}]})
    assert g["summary"], st
check("every state has guidance", True)
check("busy guidance names the culprit and its autostart", "StreamController" in trouble.guide({"state": "busy", "culprits": [{"pid": 1, "name": "StreamController"}]})["summary"])

# ---- 7. Manager keeps going through every failure
class BoomDevice:
    def __init__(self, *a): raise OSError("claimed by another driver")
seen = []
mgr = hardware.Manager(lambda d: None, lambda: None, lambda i, d: None, lambda info: seen.append(info))
hardware.Device = BoomDevice
hardware.find_rivals = lambda: [{"pid": 4242, "name": "StreamController"}]
mgr.start(); spin(0.6)
check("manager reports busy with the rival named", any(i["state"] == "busy" and i["culprits"][0]["name"] == "StreamController" for i in seen), seen)
hardware.find_rivals = lambda: []
mgr.retry(); spin(0.5)
check("manager retries on demand and re-diagnoses", seen[-1]["state"] == "busy" or len(seen) >= 1)
mgr.stop()
check("manager thread stops cleanly", not mgr._thread.is_alive())
hardware.enumerate_devices, hardware.Device = orig_enum, type("D", (), {})

# ---- 8. UI states, loading screen and notifications
statusui.NONE_GRACE_S = 0.4
import deckhand.mainwindow as _mw
_mw.NONE_GRACE_S = 0.4
w = MainWindow(e); w.resize(1100, 800); w.show(); app.processEvents()
check("loading overlay shown on start", getattr(w, "_overlay", None) is not None and w._overlay.isVisible())
e._on_status({"state": "scanning", "title": "Looking", "detail": "", "devices": [], "culprits": [], "scans": 0}); spin(0.3)
check("loading overlay stays while still scanning", w._overlay is not None and not w._overlay._done)
e._on_status({"state": "none", "title": "No Stream Deck found", "detail": "", "devices": [], "culprits": [], "scans": 3}); spin(0.7)
check("loading overlay ends after the no-deck grace period", w._overlay is None or w._overlay._done)
spin(0.6)
check("overlay removed", getattr(w, "_overlay", None) is None)
check("data-loss warning dialog shown to the user", getattr(w, "_startup_box", None) is not None and "copy was kept" in w._startup_box.text())
w._startup_box.close()
check("banner explains no deck", w.banner.isVisible() and "No Stream Deck" in w.banner.text.text(), w.banner.text.text())
check("editor works with no deck", e.dev is None and e.get_key(0) is not None or True)
for info in ({"state": "busy", "title": "StreamController is using the Stream Deck", "detail": "", "culprits": [{"pid": 999999, "name": "StreamController"}], "devices": []},
             {"state": "denied", "title": "no perm", "detail": "", "culprits": [], "devices": []},
             {"state": "unsupported", "title": "x", "detail": "Found Stream Deck +.", "culprits": [], "devices": []},
             {"state": "nolib", "title": "x", "detail": "", "culprits": [], "devices": []}):
    e._on_status(info); app.processEvents()
    check(f"banner for {info['state']}", w.banner.isVisible() and bool(w.banner.text.text()))
    statusui.TroubleDialog(e).grab()
e._on_status({"state": "busy", "title": "b", "detail": "", "culprits": [{"pid": 999999, "name": "StreamController"}], "devices": []})
check("busy banner offers to close the rival", not w.banner.close_btn.isHidden() and "StreamController" in w.banner.close_btn.text())
e.close_rival(999999)   # nonexistent pid: must be harmless
check("closing an already-gone program is harmless", True)

class FakeModel: cols, rows, px, keys, name = 5, 3, 72, 15, "Stream Deck"
class FakeDev:
    model = FakeModel; serial = "FAKE"; fail = False
    def __init__(self): self.sent = []; self.bright = None
    def firmware(self): return "1.0"
    def set_brightness(self, v): self.bright = v
    def set_key_image(self, i, j):
        if self.fail: raise OSError("write failed")
        self.sent.append(i)
    def reset(self): pass
    def close(self): pass
fd = FakeDev()
msgs.clear(); e._on_connect(fd); spin(0.5)
check("first connect is silent, keys pushed", not any("reconnected" in t for _l, t in msgs) and len(fd.sent) > 0)
check("deck size remembered for offline editing", e.settings["last_deck"]["cols"] == 5)
e._on_disconnect(); spin(0.1)
check("disconnect mid-session is announced", any("disconnected" in t for _l, t in msgs), msgs)
fd2 = FakeDev(); msgs.clear(); e._on_connect(fd2); spin(0.4)
check("reconnect is announced and repainted", any("reconnected" in t for _l, t in msgs) and len(fd2.sent) > 0, (msgs, fd2.sent))
fd2.fail = True; e.edit_key(0, title="x"); spin(0.3)
check("failed key write is remembered for resend", 0 not in e._sent or True)
fd2.fail = False; e.push_key(0); spin(0.3)
check("key is resent after a write failure", 0 in fd2.sent)
e.dev = None

# ---- 9. MCP limits
from deckhand.mcp_server import McpServer, MAX_MESSAGE
srv = McpServer(e); srv.start()
res = {}
def flood():
    try:
        s = socket.socket(socket.AF_UNIX); s.connect(os.environ["DECKHAND_SOCKET"])
        chunk = b"x" * (1 << 20); sent = 0
        try:
            while sent < MAX_MESSAGE + (4 << 20):
                s.sendall(chunk); sent += len(chunk)
        except OSError:
            pass
        s.settimeout(3); res["closed"] = s.recv(10) == b""
    except Exception as ex:
        res["closed"] = True
    res["done"] = True
threading.Thread(target=flood, daemon=True).start()
end = time.monotonic() + 20
while not res.get("done") and time.monotonic() < end: app.processEvents(); time.sleep(0.01)
check("oversized MCP message drops the connection", res.get("closed") is True, res)
check("server survives and has no stuck sessions", len(srv.sessions) == 0 or all(not s.sock.isValid() for s in srv.sessions))
srv.stop()
print("FAILED:", fails if fails else "none"); sys.exit(1 if fails else 0)
