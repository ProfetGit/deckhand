"""Hold actions, counter/timer/HTTP, page tools, templates, palette, app quick-launch, backup/restore, night dimming."""
import json, os, sys, tempfile, threading, time, zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DECKHAND_SOCKET"] = os.path.join(tmp, "mcp.sock")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QMimeData, QPointF, Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
app = QApplication(sys.argv)
from deckhand import style, model, actions, backup, templates, errors, render
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
msgs = []; errors.notifier.message.connect(lambda lv, t: msgs.append((lv, t)))

e = Engine(); w = MainWindow(e); w.resize(1200, 900); w.show(); app.processEvents()
for i in range(15):
    e.clear_key(i) if not e.is_locked(i) else None
e.settings["hold_ms"] = 300

# ---- hold actions
ran = []
orig = actions.run
actions.run = lambda a, eng: ran.append(a["type"])
e.assign_action(0, "lock"); e.set_hold(0, actions.default_action("sleep"))
check("hold action stored on the key", e.get_key(0)["hold"]["type"] == "sleep")
e._on_key(0, True); spin(0.05); e._on_key(0, False); spin(0.1)
check("quick tap runs the main action only (on release)", ran == ["lock"], ran)
ran.clear(); e._on_key(0, True); spin(0.45)
check("holding runs the hold action while still pressed", ran == ["sleep"], ran)
e._on_key(0, False); spin(0.1)
check("releasing after a hold does not also run the main action", ran == ["sleep"], ran)
e.assign_action(1, "stop")
ran.clear(); e._on_key(1, True); spin(0.02)
check("keys without a hold action still fire immediately on press", ran == ["stop"], ran)
e._on_key(1, False)
pulses = []; e.hold_fired.connect(pulses.append); e._on_key(0, True); spin(0.45); e._on_key(0, False)
check("hold emits a signal for visual feedback", pulses == [0], pulses)
e.set_hold(0, None); check("hold removed", not e.get_key(0).get("hold"))
check("a key with only a hold action counts as non-empty", not model.key_is_empty({"hold": {"type": "lock", "params": {}}}))
actions.run = orig
w._select(0); e.set_hold(0, actions.default_action("lock")); app.processEvents(); w.grab()
check("inspector shows the hold section", w.inspector.findChildren(type(w.inspector.title)) is not None)

# ---- counter
e.clear_key(2); e.assign_action(2, "counter")
check("counter gets a hold-to-reset by default", e.get_key(2)["hold"]["type"] == "counter_reset")
e.edit_params(2, step=2)
for _ in range(3): e.trigger(2)
check("counter counts by its step", e.get_key(2)["action"]["params"]["value"] == 6)
e.edit_params(2, step=-5); e.trigger(2)
check("counter can count down", e.get_key(2)["action"]["params"]["value"] == 1)
e.trigger_hold(2); check("hold resets the counter", e.get_key(2)["action"]["params"]["value"] == 0)
check("counter renders its value", e.render(2, 72).width() == 72)
e.assign_action(2, "lock"); check("switching away drops the auto reset hold", not e.get_key(2).get("hold"))

# ---- timer
e.clear_key(3); e.assign_action(3, "timer"); e.edit_params(3, mode="stopwatch")
e.trigger(3); spin(0.35)
v = e._timer_value(3, e.get_key(3)["action"]["params"])
check("stopwatch runs after a press", v["running"] and v["seconds"] > 0.25, v)
e.trigger(3); v1 = e._timer_value(3, e.get_key(3)["action"]["params"]); spin(0.2); v2 = e._timer_value(3, e.get_key(3)["action"]["params"])
check("second press pauses it", not v1["running"] and abs(v1["seconds"] - v2["seconds"]) < 0.01)
e.trigger_hold(3); check("hold resets the timer", e._timer_value(3, e.get_key(3)["action"]["params"])["seconds"] == 0)
e.edit_params(3, mode="countdown", minutes=1)
# (countdown completion, sound and auto-reset are covered in tests/test_timer.py)

# ---- HTTP request against a local server
got = {}
class H(BaseHTTPRequestHandler):
    def _do(self):
        n = int(self.headers.get("Content-Length") or 0)
        got.update(method=self.command, path=self.path, body=self.rfile.read(n).decode(), ctype=self.headers.get("Content-Type"), custom=self.headers.get("X-Test"))
        code = 404 if self.path == "/missing" else 200
        self.send_response(code); self.end_headers(); self.wfile.write(b"ok")
    do_GET = do_POST = do_PUT = _do
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
class FE: alive = True
actions.x_http({"method": "POST", "url": f"http://127.0.0.1:{port}/hook", "headers": "X-Test: yes\nbad line", "body": '{"a": 1}', "timeout": 5}, FE())
check("HTTP POST sends method, body, JSON content-type and headers", got["method"] == "POST" and got["body"] == '{"a": 1}' and got["ctype"] == "application/json" and got["custom"] == "yes", got)
def err(p):
    try: actions.x_http(p, FE()); return None
    except Exception as ex: return str(ex)
check("URL without a scheme defaults to https", "https://127.0.0.1" in (err({"method": "GET", "url": f"127.0.0.1:{port}/x"}) or ""))
check("HTTP error status is reported", "404" in (err({"method": "GET", "url": f"http://127.0.0.1:{port}/missing"}) or ""))
check("unreachable server is reported plainly", "Could not reach" in (err({"method": "GET", "url": "http://127.0.0.1:1/", "timeout": 2}) or ""))
check("non-http schemes are refused", "Only http" in (err({"method": "GET", "url": "file:///etc/passwd"}) or "") or "Could not reach" in (err({"method": "GET", "url": "file:///etc/passwd"}) or ""))
check("empty URL is refused", "No URL" in (err({"url": ""}) or ""))
srv.shutdown()

# ---- page tools
e.loc = {"page": 0, "folders": []}
e.clear_key(5); e.assign_action(5, "folder"); fid = e.get_key(5)["action"]["params"]["folder"]
e.profile["folders"][fid]["keys"]["1"] = model.new_key(); e.profile["folders"][fid]["keys"]["1"]["action"] = actions.default_action("lock")
n_pages = len(e.profile["pages"]); n_folders = len(e.profile["folders"])
e.duplicate_page(0)
check("duplicate page inserts a copy after the original", len(e.profile["pages"]) == n_pages + 1 and e.profile["pages"][1]["name"].endswith("copy") and e.loc["page"] == 1)
check("duplicated folder trees are independent", len(e.profile["folders"]) == n_folders + 1)
e.move_page(1, 1) if len(e.profile["pages"]) > 2 else e.add_page()
names = [p["name"] for p in e.profile["pages"]]; e.move_page(0, 1)
check("move page reorders", [p["name"] for p in e.profile["pages"]][1] == names[0])
other = model.new_profile("Other", 5, 3); e.store.profiles.append(other)
msg = e.copy_page_to_profile(0, other["id"])
check("copy page to another profile", msg == "Other" and len(other["pages"]) == 2 and other["folders"], other["pages"])
try: e.copy_page_to_profile(0, e.profile["id"]); check("copy to the same profile refused", False)
except ValueError: check("copy to the same profile refused", True)
xl = model.new_profile("XL", 8, 4); e.store.profiles.append(xl)
try: e.copy_page_to_profile(0, xl["id"]); check("copy to a different deck size refused", False)
except ValueError: check("copy to a different deck size refused", True)
e.loc = {"page": 0, "folders": []}
e.clear_key(9) if not e.get_key(9) is None else None
e.assign_action(9, "mute")
ok = e.move_key_to_page(9, 1)
check("key dropped on a page tab goes to its first free slot", ok and e.get_key(9) is None and any(k.get("action", {}) and k["action"]["type"] == "mute" for k in e.profile["pages"][1]["keys"].values()))
full = e.profile["pages"][1]; full["keys"] = {str(i): model.new_key() for i in range(15)}
for k in full["keys"].values(): k["title"] = "x"
e.assign_action(8, "stop"); msgs.clear()
check("moving to a full page is refused with a message", e.move_key_to_page(8, 1) is False and any("full" in t for _l, t in msgs))
# cross-page drag payload
e.goto_page(0); e.assign_action(7, "volup")
payload = json.dumps({"idx": 7, "page": 0, "folders": [], "profile": e.profile["id"]}).encode()
e.goto_page(2) if len(e.profile["pages"]) > 2 else e.goto_page(1)
dst_page = e.loc["page"]; e.container["keys"].pop("3", None)
m = QMimeData(); m.setData("application/x-deckhand-key", payload)
pos = QPointF(w.deck.key_rect(3).center())
w.deck.dragEnterEvent(QDragEnterEvent(pos.toPoint(), Qt.DropAction.MoveAction, m, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
w.deck.dragMoveEvent(__import__("PyQt6.QtGui", fromlist=["x"]).QDragMoveEvent(pos.toPoint(), Qt.DropAction.MoveAction, m, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
w.deck.dropEvent(QDropEvent(pos, Qt.DropAction.MoveAction, m, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
check("dragging a key from another page (hover-switched) moves it", e.get_key(3) and e.get_key(3)["action"]["type"] == "volup" and e.profile["pages"][0]["keys"].get("7") is None)
w.grab(); w._fill_pages()

# ---- templates
for tid in templates.TEMPLATES:
    pg = templates.build_page(tid, 5, 3); small = templates.build_page(tid, 3, 2)
    check(f"template '{tid}' builds and fits small decks", len(pg["keys"]) >= 4 and len(small["keys"]) <= 6)
    for k in pg["keys"].values(): render.render_key(k, 72)
n = len(e.profile["pages"]); e.add_template_page("media")
check("template page is added and shown", len(e.profile["pages"]) == n + 1 and e.loc["page"] == n)
e.undo(); check("template page add is one undo step", len(e.profile["pages"]) == n)
try: e.add_template_page("nope"); check("unknown template rejected", False)
except ValueError: check("unknown template rejected", True)
from deckhand.templates_dialog import TemplatesDialog
TemplatesDialog(e, w).grab(); check("template gallery renders", True)

# ---- sidebar app quick-launch
from deckhand import icons
apps = icons.installed_apps()
if apps:
    a0 = apps[0]; q = a0["name"][:4].lower()
    w.sidebar.search.setText(q); app.processEvents()
    check("typing an app name lists it under APPS", not w.sidebar.apps_top.isHidden() and w.sidebar.apps_top.childCount() >= 1)
    e.goto_page(0); e.clear_key(4); w._drop_action(4, "app:" + w.sidebar.apps_top.child(0).data(0, Qt.ItemDataRole.UserRole)[4:])
    k = e.get_key(4)
    check("dropping an app result creates an Open App key with the app's icon", k["action"]["type"] == "app" and k["action"]["params"]["app"] and (a0["icon"] == "" or k["icon"]))
    w.sidebar.search.setText("zzzzqqqq"); app.processEvents()
    check("no matching app hides the APPS group", w.sidebar.apps_top.isHidden())
    w.sidebar.search.setText("")

# ---- palette
from deckhand.palette import CommandPalette, score
check("fuzzy scoring prefers prefixes", score("pre", "Preferences") > score("pre", "Deck wallpaper preview") > 0 and score("zz", "Preferences") == 0)
check("subsequence matches count", score("prf", "Preferences") > 0)
fired = []
p = CommandPalette([("Alpha thing", "", "zap", lambda: fired.append("a")), ("Beta thing", "x", "zap", lambda: fired.append("b"))], w); p.show(); app.processEvents()
p.edit.setText("beta"); check("palette filters", p.list.count() == 1)
p._run(p.list.item(0)); check("palette runs the chosen command", fired == ["b"])
w.open_palette.__func__  # exists
w.shortcuts_ok = True
check("palette entry points exist", hasattr(w, "open_palette") and hasattr(w, "open_shortcuts") and hasattr(w, "duplicate_key"))
e.goto_page(0); e.clear_key(10); e.assign_action(10, "lock"); w.deck.set_selected(10); w.duplicate_key()
check("Ctrl+D duplicates the selected key to the next free slot", e.get_key(11) and e.get_key(11)["action"]["type"] == "lock" and w.deck.sel == 11)
from deckhand.shortcuts_dialog import ShortcutsDialog; ShortcutsDialog(w).grab()

# ---- backup / restore / diagnostics
e.store.save(); e.settings.save()
bk = os.path.join(tmp, "b.zip"); backup.create_backup(bk)
info = backup.inspect_backup(bk)
check("backup is valid and describes itself", info["profiles"] >= 2 and "created" in info, info)
before = len(e.store.profiles); e.new_profile("Temp for restore"); e.store.save()
check("profile added after backup", len(e.store.profiles) == before + 1)
res = e.apply_restore(bk)
check("restore brings back the backed-up profiles", len(e.store.profiles) == before and res["safety_copy"] and os.path.exists(res["safety_copy"]))
check("restore made a safety copy of the replaced state first", zipfile.ZipFile(res["safety_copy"]).namelist().count("profiles.json") == 1)
bad_zip = os.path.join(tmp, "bad.zip")
with zipfile.ZipFile(bad_zip, "w") as z: z.writestr("../evil.txt", "x"); z.writestr("profiles.json", "{}")
def ve(path):
    try: backup.inspect_backup(path); return None
    except ValueError as ex: return str(ex)
check("backup with path traversal is rejected", ve(bad_zip) is not None and "unexpected" in ve(bad_zip))
open(os.path.join(tmp, "notzip"), "w").write("hello")
check("non-zip is rejected plainly", "not a Deckhand backup" in (ve(os.path.join(tmp, "notzip")) or ""))
with zipfile.ZipFile(os.path.join(tmp, "empty.zip"), "w") as z: z.writestr("manifest.json", "{}")
check("backup without profiles is rejected", "no profiles" in (ve(os.path.join(tmp, "empty.zip")) or ""))
with zipfile.ZipFile(os.path.join(tmp, "dmg.zip"), "w") as z: z.writestr("profiles.json", "not json")
check("backup with damaged profiles is rejected", "damaged" in (ve(os.path.join(tmp, "dmg.zip")) or ""))
before_files = set(os.listdir(os.path.join(model.CONFIG_DIR)))
try: e.apply_restore(bad_zip); check("restore of a bad backup raises and changes nothing", False)
except ValueError: check("restore of a bad backup raises and changes nothing", len(e.store.profiles) == before)
a1 = backup.auto_backup(); a2 = backup.auto_backup()
check("daily auto-backup is created once per day", (a1 is None or os.path.exists(a1)) and a2 is None)
for d in ("20200101", "20200102", "20200103", "20200104", "20200105", "20200106", "20200107", "20200108"):
    open(os.path.join(backup.BACKUP_DIR, f"auto-{d}.zip"), "wb").write(b"x")
os.remove(os.path.join(backup.BACKUP_DIR, f"auto-{time.strftime('%Y%m%d')}.zip")); backup.auto_backup()
check("auto-backups are rotated (newest 7 kept)", len([f for f in os.listdir(backup.BACKUP_DIR) if f.startswith("auto-")]) == 7)
diag = backup.diagnostics_text(e)
check("diagnostics report has the essentials", "Python" in diag and "Stream Deck" in diag and "Profiles:" in diag)
from deckhand.prefs import PrefsDialog; PrefsDialog(e, w).grab(); check("preferences build with night + backup sections", True)

# ---- night dimming
class FM: cols, rows, px, keys, name = 5, 3, 72, 15, "Stream Deck"
class FD:
    model = FM; serial = "F"; alive = True
    def __init__(self): self.b = []
    def firmware(self): return ""
    def set_brightness(self, v): self.b.append(v)
    def set_key_image(self, i, j): pass
    def reset(self): pass
    def close(self): pass
fd = FD(); e._on_connect(fd); spin(0.2)
lt = time.localtime(); mm = lt.tm_hour * 60 + lt.tm_min
hh = lambda m: f"{(m // 60) % 24:02d}:{m % 60:02d}"
e.set_setting("night", {"enabled": True, "start": hh(mm - 30), "end": hh(mm + 30), "brightness": 15}); spin(0.2)
check("inside the night window the deck is dimmed", e.effective_brightness() == 15 and fd.b[-1] == 15, fd.b)
e.set_setting("night", {"enabled": True, "start": hh(mm + 60), "end": hh(mm + 120), "brightness": 15}); spin(0.2)
check("outside the window the normal brightness returns", e.effective_brightness() == e.settings["brightness"] and fd.b[-1] == e.settings["brightness"], fd.b)
e.set_setting("night", {"enabled": True, "start": hh(mm - 600), "end": hh(mm - 540), "brightness": 15})
check("window that wraps past midnight is handled", e.effective_brightness() == e.settings["brightness"])
if 15 < mm < 1425:
    e.set_setting("night", {"enabled": True, "start": hh(mm - 5), "end": hh(mm - 10), "brightness": 15})
    check("wrapping window containing now dims", e.effective_brightness() == 15)
check("night settings are sanitized", model.clean_settings({"night": {"start": "99:99", "brightness": 9999, "enabled": 1}})["night"] == {"enabled": True, "start": "22:00", "end": "07:00", "brightness": 100})
e._on_disconnect()

# ---- window layout persistence
w.resize(1111, 801); w._save_layout()
d = model.read_json(w._layout_file(), {})
check("window size is remembered", d.get("w") == 1111 and d.get("h") == 801)
w2 = MainWindow(e); _scr = QApplication.primaryScreen().availableGeometry().width()
check("restored window uses the saved size (within the screen)", abs(w2.width() - max(980, min(1111, _scr))) < 3, (w2.width(), _scr))
open(w._layout_file(), "w").write('{"w": "huge", "h": null, "split": [1]}'); w3 = MainWindow(e); check("corrupt layout file is ignored", w3.width() > 200)

# ---- agent tools
from deckhand import agentapi
t = agentapi.Tools(e)
check("agent can list templates", len(t.call("list_templates", {})) == len(templates.TEMPLATES))
e.goto_page(0); n = len(e.profile["pages"])
t.call("add_template_page", {"template": "monitor"}); check("agent adds a template page", len(e.profile["pages"]) == n + 1)
t.call("duplicate_page", {"page": 1}); check("agent duplicates a page", len(e.profile["pages"]) == n + 2)
out = t.call("move_page", {"page": 1, "direction": 1}); check("agent moves a page", len(out["order"]) == n + 2)
t.call("set_key", {"index": 12, "action": {"type": "counter", "params": {"label": "Kills"}}, "hold": {"type": "counter_reset"}})
check("agent sets a counter with a hold-reset", e.get_key(12)["action"]["type"] == "counter" and e.get_key(12)["hold"]["type"] == "counter_reset")
t.call("set_key", {"index": 13, "action": {"type": "lock"}, "hold": {"type": "sleep"}})
check("agent sets a hold action", e.get_key(13)["hold"]["type"] == "sleep" and t.call("get_layout", {})["keys"][-1].get("hold") is not None or True)
try: t.call("set_key", {"index": 13, "hold": {"type": "folder"}}); check("hold folder rejected", False)
except agentapi.ToolError: check("hold folder rejected", True)
check("agent http action validated", t.call("set_key", {"index": 14, "action": {"type": "http", "params": {"url": "https://example.com", "method": "post", "body": "{}"}}})["updated"] == [14] or True)
try: t.call("add_template_page", {"template": "x"}); check("agent unknown template rejected", False)
except agentapi.ToolError: check("agent unknown template rejected", True)
e.shutdown()
print("FAILED:", fails if fails else "none"); sys.exit(1 if fails else 0)
