"""Headless engine/model/UI smoke test. Uses a throwaway XDG_CONFIG_HOME."""
import os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication(sys.argv)
from deckhand import style, actions, model, keymap
app.setStyleSheet(style.QSS)
from deckhand.engine import Engine
from deckhand.mainwindow import MainWindow

e = Engine()
w = MainWindow(e)
w.show()
fails = []
def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

# seeded
check("seed profile has keys", len(e.container["keys"]) >= 10)
# assign + edit + undo
e.assign_action(14, "website")
check("assign website", e.get_key(14)["action"]["type"] == "website")
e.edit_params(14, url="example.com")
check("edit params", e.get_key(14)["action"]["params"]["url"] == "example.com")
e.undo(); e.undo()
check("undo x2 clears key", e.get_key(14) is None)
e.redo()
check("redo restores action", e.get_key(14) and e.get_key(14)["action"]["type"] == "website")
# coalesced edits = single undo step
e.undo()
for i in range(5):
    e.edit_key(13, coalesce="t", title="x" * (i + 1))
e.undo()
check("coalesce title edits", e.get_key(13) is None)
# move/copy/swap
e.assign_action(12, "hotkey")
e.move_key(12, 13)
check("move", e.get_key(13) and not e.get_key(12))
e.move_key(13, 0, copy_it=True)
check("copy", e.get_key(0)["action"]["type"] == "hotkey" and e.get_key(13))
e.move_key(0, 1)
check("swap", e.get_key(0)["action"]["type"] == "playpause" and e.get_key(1)["action"]["type"] == "hotkey")
# folders
e.assign_action(11, "folder")
fid = e.get_key(11)["action"]["params"]["folder"]
check("folder created", fid in e.profile["folders"])
e.open_folder(fid)
check("in folder, back key locked", e.in_folder and e.get_key(0)["action"]["type"] == "back")
e.assign_action(2, "text")
e.go_back()
n_folders = len(e.profile["folders"])
e.paste_key(9, e.get_key(11))
check("paste folder clones subtree", len(e.profile["folders"]) == n_folders + 1)
e.clear_key(9)
check("gc folders on clear", len(e.profile["folders"]) == n_folders)
# pages & profiles
e.add_page(); check("add page", len(e.profile["pages"]) == 2 and e.loc["page"] == 1)
e.delete_page(1); check("delete page", len(e.profile["pages"]) == 1)
e.new_profile("Gaming"); check("new profile", e.profile["name"] == "Gaming" and len(e.profiles()) == 2)
e.duplicate_profile(); check("duplicate", len(e.profiles()) == 3)
check("delete profile", e.delete_profile() and len(e.profiles()) == 2)
# persistence
e.store.save()
st = model.Store()
check("persisted", len(st.profiles) == 2)
# render all action types
for aid in actions.ACTIONS:
    k = model.new_key(); k["action"] = actions.default_action(aid)
    from deckhand import render
    img = render.render_key(k, 72)
    check(f"render {aid}", img.width() == 72 and len(render.to_jpeg(img)) > 100)
# UI: select every key, inspector builds for every action type
for i in range(15):
    w._select(i)
for aid in actions.ACTIONS:
    e.assign_action(5, aid) if aid != "back" else None
    w._select(5)
    w.grab()
check("inspector builds for all actions", True)
# multi action with steps
e.assign_action(6, "multi")
e.edit_params(6, steps=[actions.default_action("hotkey"), {"type": "delay", "params": {"ms": 5}}, actions.default_action("lock")])
w._select(6); w.grab()
check("multi action steps", len(e.get_key(6)["action"]["params"]["steps"]) == 3)
# uinput available + keyboard device creation
check("uinput writable", keymap.keyboard.available())
if keymap.keyboard.available():
    keymap.keyboard.tap([keymap.LABELS and 70])   # ScrollLock: harmless
    check("uinput tap", True)

# ---- UI interaction: drag & drop events, inspector widgets
from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from deckhand.widgets import MIME_ACTION, MIME_KEY
e.loc = {"page": 0, "folders": []}; e.changed.emit()
w.resize(1260, 920); app.processEvents()
def drop(mime, idx, mods=Qt.KeyboardModifier.NoModifier, act=Qt.DropAction.CopyAction):
    pos = QPointF(w.deck.key_rect(idx).center())
    w.deck.dragEnterEvent(QDragEnterEvent(pos.toPoint(), act, mime, Qt.MouseButton.LeftButton, mods))
    w.deck.dragMoveEvent(QDragMoveEvent(pos.toPoint(), act, mime, Qt.MouseButton.LeftButton, mods))
    w.deck.dropEvent(QDropEvent(pos, act, mime, Qt.MouseButton.LeftButton, mods))
for i in range(15): e.clear_key(i) if not e.is_locked(i) else None
m = QMimeData(); m.setData(MIME_ACTION, b"hotkey"); drop(m, 3)
check("DnD action onto key", e.get_key(3) and e.get_key(3)["action"]["type"] == "hotkey" and w.deck.sel == 3)
m = QMimeData(); m.setData(MIME_KEY, b"3"); drop(m, 7, act=Qt.DropAction.MoveAction)
check("DnD key move", e.get_key(7) and not e.get_key(3))
m = QMimeData(); m.setData(MIME_KEY, b"7"); drop(m, 8, Qt.KeyboardModifier.ControlModifier)
check("DnD ctrl-drag copy", e.get_key(7) and e.get_key(8))
img = os.path.join(tmp, "x.png")
from PyQt6.QtGui import QImage
im = QImage(32, 32, QImage.Format.Format_RGB32); im.fill(0xff0000); im.save(img)
m = QMimeData(); m.setUrls([QUrl.fromLocalFile(img)]); drop(m, 9)
check("DnD image file sets icon", e.get_key(9) and e.get_key(9)["icon"]["kind"] == "file" and os.path.exists(e.get_key(9)["icon"]["value"]))
# inspector title typing
w._select(7); app.processEvents()
w.inspector.title.setPlainText("Hello")
check("typing title updates key", e.get_key(7)["title"] == "Hello")
# hotkey widget
from deckhand.widgets import HotkeyEdit
he = w.inspector.findChild(HotkeyEdit)
check("hotkey widget present for hotkey action", he is not None)
if he:
    he.mod_btns["ctrl"].click()
    check("hotkey mods propagate", "ctrl" in e.get_key(7)["action"]["params"]["hotkey"]["mods"])
# app combo auto icon
e.assign_action(10, "app"); w._select(10); app.processEvents()
from deckhand.forms import AppCombo
ac = w.inspector.findChild(AppCombo)
check("app combo present", ac is not None and ac.count() > 5)
if ac and ac.count() > 5:
    ac.setCurrentIndex(1); ac.activated.emit(1)
    k = e.get_key(10)
    check("app pick sets param + auto icon", k["action"]["params"]["app"] and k["icon"] and k["icon"].get("auto"))
# sidebar double-click assign
w.deck.set_selected(14); w._sidebar_add("lock")
check("sidebar add", any(e.get_key(i) and e.get_key(i)["action"] and e.get_key(i)["action"]["type"] == "lock" for i in range(15)))
# key events on engine
e._on_key(7, True); e._on_key(7, False)
check("engine handles key events", True)
# paste across
w.deck.set_selected(7); w.copy_key(); w.deck.set_selected(6); w.paste_key()
check("copy/paste", e.get_key(6) and e.get_key(6)["title"] == "Hello")

# hotkey recorder via synthetic key event
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtCore import QEvent
he2 = HotkeyEdit(); got = []
he2.changed.connect(got.append); he2.show()
he2._start()
ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, 58, 0, 0, "m")
he2.event(ev)
check("hotkey records scancode", got and got[-1]["code"] == 50 and got[-1]["mods"] == ["ctrl", "shift"] and got[-1]["label"] == "M")
# command + multi action executors
outf = os.path.join(tmp, "out.txt")
actions.run({"type": "multi", "params": {"steps": [
    {"type": "command", "params": {"cmd": f"echo one > {outf}"}},
    {"type": "delay", "params": {"ms": 50}},
    {"type": "command", "params": {"cmd": f"echo two >> {outf}"}}]}}, e)
time.sleep(0.4)
check("multi action runs steps in order", open(outf).read().split() == ["one", "two"])
# navigation via request signal
e.loc = {"page": 0, "folders": []}
e.assign_action(2, "folder"); fid = e.get_key(2)["action"]["params"]["folder"]
actions.run({"type": "folder", "params": {"folder": fid}}, e); app.processEvents()
check("folder action navigates", e.in_folder)
actions.run({"type": "back", "params": {}}, e); app.processEvents()
check("back action navigates", not e.in_folder)

# ---- key states: live (mute) + toggle
from deckhand import render as _r, sysinfo
e.loc = {"page": 0, "folders": []}
e.clear_key(2) if not e.is_locked(2) else None
e.assign_action(2, "micmute")
check("micmute has built-in states", _r.has_states(e.get_key(2)))
base = e.render(2, 72, state=False); on = e.render(2, 72, state=True)
check("live look differs between states", base != on)
sysinfo.LIVE["mic_muted"] = lambda arg: True
e._live_wanted = {"mic_muted"}
e._on_live({"mic_muted": True})
check("live state flips look", e.look_state(2) is True and e.render(2, 72) == on)
e._on_live({"mic_muted": False})
check("live state flips back", e.look_state(2) is False)
e.assign_action(3, "next")
check("plain key has no states", not _r.has_states(e.get_key(3)))
e.edit_alt(3, icon={"kind": "glyph", "value": "pause"}, bg="#112233")
check("alt makes toggle key", _r.has_states(e.get_key(3)) and e.look_state(3) is False)
e.trigger(3)
check("press toggles state", e.look_state(3) is True)
check("toggled look uses alt", e.render(3, 72) != e.render(3, 72, state=False))
e.trigger(3)
check("press toggles back", e.look_state(3) is False)
e.edit_alt(3, remove=["bg"])
check("alt edit remove field", "bg" not in e.get_key(3)["alt"])
e.undo(); check("alt edit undoable", e.get_key(3)["alt"].get("bg") == "#112233")
# inspector tabs
w._select(3); w.inspector._set_tab("alt"); app.processEvents()
check("inspector active tab builds", w.inspector.tab == "alt")
w.inspector.title.setPlainText("ON")
check("active tab edits alt title", e.get_key(3)["alt"]["title"] == "ON" and not e.get_key(3)["title"])
w.inspector._set_tab("base"); w.inspector.title.setPlainText("Base")
check("default tab edits base title", e.get_key(3)["title"] == "Base" and e.get_key(3)["alt"]["title"] == "ON")
w._select(2); w.inspector._set_tab("alt"); w.inspector.title.setPlainText("MUTED")
k2 = e.get_key(2)
check("builtin live key: first alt edit seeds look and pins base glyph", k2["alt"]["icon"]["value"] == "mic-off" and k2["icon"]["value"] == "mic" and k2["alt"]["title"] == "MUTED", k2)
w.inspector._remove_alt(); app.processEvents()
check("remove active look", not e.get_key(2).get("alt"))

# play/pause live state + per-device mute
e.clear_key(3); e.assign_action(3, "playpause")
check("playpause is stateful", _r.has_states(e.get_key(3)) and actions.live_source(e.get_key(3)["action"]) == "playing")
e._on_live({"playing": True}); on_img = e.render(3, 72)
e._on_live({"playing": False}); off_img = e.render(3, 72)
check("playpause look changes with playback", on_img != off_img)
e.clear_key(2); e.assign_action(2, "micmute")
e.edit_params(2, device="alsa_input.usb-X")
check("pinned mic uses its own live source", actions.live_source(e.get_key(2)["action"]) == "mic_muted:alsa_input.usb-X")
w._select(2); app.processEvents(); w.grab()
check("device picker form builds", True)

# ---- motion
from deckhand import motion
def spin(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.005)
e.loc = {"page": 0, "folders": []}; e.changed.emit(); spin(1.3)
dv = w.deck
check("animation timer idles when nothing moves", not dv._timer.isActive())
e.clear_key(12) if not e.is_locked(12) else None
spin(0.2)
e.assign_action(12, "lock"); spin(0.02)
check("external change flashes the key", 12 in dv._flash or 12 in dv._fade)
spin(1.0)
check("flash decays and timer stops", not dv._flash and not dv._timer.isActive())
e.engine_quiet = None
e.quiet_flash = True; e.edit_key(12, coalesce="x", title="typing"); e.quiet_flash = False; spin(0.02)
check("typing does not flash", 12 not in dv._flash)
m = QMimeData(); m.setData(MIME_ACTION, b"stop"); dv._expect = set()
drop(m, 11); spin(0.02)
check("drop pops instead of flashing", 11 in dv._pop and 11 not in dv._flash, (dv._pop, dv._flash))
spin(0.5)
e.assign_action(1, "folder") if not e.get_key(1) else None
fid = [k for k in [e.get_key(1)] if k and k.get("action") and k["action"]["type"] == "folder"]
if fid:
    e.open_folder(e.get_key(1)["action"]["params"]["folder"]); spin(0.02)
    check("opening a folder starts a nav transition", dv._nav and dv._nav["kind"] == "open")
    spin(0.4)
    check("transition ends", dv._nav is None)
    e.go_back(); spin(0.02)
    check("back transition", dv._nav and dv._nav["kind"] == "back"); spin(0.4)
dv.set_selected(5); spin(0.02)
check("selection ring fades in on the new key", 5 in dv._ring_tw)
spin(0.4)
check("old key's ring is gone and the new one is fully visible", dv._ring_tw.get(5) and dv._ring_tw[5].v == 1.0 and len(dv._ring_tw) == 1, dv._ring_tw)
motion.set_enabled(False)
dv._flash.clear(); dv._pop.clear()
e.assign_action(13, "sleep"); spin(0.05)
check("animations off: no flash/pop/nav state", not dv._flash and not dv._pop and dv._nav is None)
dv.set_selected(2); app.processEvents()
check("animations off: ring is instantly visible", dv._ring_tw[2].v == 1.0)
motion.set_enabled(True)
w.inspector.rebuild(); w.grab()

# ---- regressions: stale animation handles must not crash; nothing may need sideways scrolling
from deckhand.widgets import StatusDot, Segmented
dot = StatusDot(); dot.show()
for _ in range(3):
    dot.set_color("#3ddc84", ping=True); spin(0.4); dot.set_color("#8c8c97"); spin(0.35)
check("status dot survives repeated changes after animations finish", True)
sg = Segmented([("a", "A", "", False), ("b", "B", "", False)]); sg.show()
for v in ("b", "a", "b"):
    sg.buttons[v].click(); spin(0.3)
check("segmented survives repeated glides", True)
w.resize(980, 800); app.processEvents()
for aid in actions.ACTIONS:
    if aid == "back": continue
    e.clear_key(5); e.assign_action(5, aid); w._select(5); app.processEvents()
    sc = w.inspector.scroll
    hb = sc.horizontalScrollBar()
    need = sc.widget().minimumSizeHint().width() if sc.widget() else 0
    check(f"inspector fits width without sideways scroll: {aid}", need <= sc.viewport().width() and hb.maximum() == 0, (need, sc.viewport().width()))
e.edit_params(5, device="x" * 90)

# ---- wallpaper
from PyQt6.QtGui import QImage as _QI, QColor as _QC
from deckhand import wallpaper as _wp
_wimg = os.path.join(tmp, "wp.png"); _im = _QI(400, 200, _QI.Format.Format_RGB32)
for _x in range(400):
    for _y in range(0, 200, 20): _im.setPixelColor(_x, _y, _QC(_x * 255 // 400, 80, 200))
_im.fill(0xff3070c0); _im.save(_wimg)
e.loc = {"page": 0, "folders": []}
e.clear_key(14) if not e.is_locked(14) else None
e.set_wallpaper({"file": _wimg, "fit": "fill", "dim": 0})
check("wallpaper stored on the profile", e.profile["wallpaper"]["fit"] == "fill")
face = e.render(14, 72)
check("empty key shows its wallpaper slice", face.pixelColor(36, 36).blue() > 100)
k = model.new_key(); k["bg"] = "#112233"
check("key with its own background colour keeps it", _r.render_key(k, 72, backdrop=_wp.slice_for(e.profile["wallpaper"], 0, 5, 3, 72)).pixelColor(2, 2) == _QC("#112233"))
for fit in ("fill", "fit", "stretch"):
    e.set_wallpaper({"file": _wimg, "fit": fit, "zoom": 150, "fx": 20, "fy": 80, "dim": 40})
    check(f"wallpaper fit '{fit}' renders", e.render(7, 72).width() == 72)
c1 = _wp.compose({"file": _wimg, "fit": "fill", "zoom": 100}, 5, 3, 72); c2 = _wp.compose({"file": _wimg, "fit": "fill", "zoom": 100, "dim": 60}, 5, 3, 72)
check("dim darkens the wallpaper", c2.pixelColor(10, 10).blue() < c1.pixelColor(10, 10).blue())
check("canvas includes the gaps between keys", c1.width() > 5 * 72)
check("slice has key size", _wp.slice_for({"file": _wimg}, 3, 5, 3, 72).size().width() == 72)
check("wallpaper values are clamped", _wp.normalize({"file": "x", "zoom": 9999, "dim": -5, "fit": "weird"})["zoom"] == 400 and _wp.normalize({"file": "x", "dim": -5})["dim"] == 0 and _wp.normalize({"file": "x", "fit": "weird"})["fit"] == "fill")
check("no file means no wallpaper", _wp.normalize({"file": ""}) is None and _wp.normalize("x") is None)
e.undo(); e.undo(); e.undo(); e.undo(); e.undo()
msgs2 = []
errors_mod = __import__("deckhand.errors", fromlist=["x"]); errors_mod.notifier.message.connect(lambda lv, t: msgs2.append(t))
e.set_wallpaper({"file": "/gone/missing.png"})
fm = e.render(0, 72); e.render(1, 72)
check("missing wallpaper file degrades to plain keys and warns once", fm.width() == 72 and sum("wallpaper" in m for m in msgs2) == 1, msgs2)
e.set_wallpaper(None); check("wallpaper removed", "wallpaper" not in e.profile)
from deckhand.wallpaper_dialog import WallpaperDialog
dlg = WallpaperDialog(e, w); dlg._use_file(_wimg); app.processEvents()
check("dialog sets a wallpaper from a file (copied into config)", e.profile["wallpaper"]["file"].startswith(model.ICON_DIR))
dlg.sliders["dim"][0].setValue(70); check("dialog slider edits dim", e.profile["wallpaper"]["dim"] == 70)
dlg.fit.buttons["stretch"].click(); check("dialog fit control edits fit", e.profile["wallpaper"]["fit"] == "stretch")
dlg._remove(); check("dialog removes wallpaper", "wallpaper" not in e.profile); dlg.grab()

# ---- colour picker popover
from deckhand import colorpicker as _cp
_got = []; _pop = _cp.ColorPopup("#336699"); _pop.changed.connect(_got.append); _pop.show(); app.processEvents()
_pop.set_color("#ff8800"); check("colour popover applies live", _got[-1] == "#ff8800")
_pop._hex("#00ff7f"); check("colour popover accepts hex", _got[-1] == "#00ff7f")
_pop._hue(0.0); check("colour popover hue strip", _got[-1] == "#ff0000")
_pop.keyPressEvent(__import__("PyQt6.QtGui", fromlist=["x"]).QKeyEvent(__import__("PyQt6.QtCore", fromlist=["x"]).QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
check("Esc restores the original colour", _got[-1] == "#336699")
w.grab().save(os.path.join(os.path.dirname(__file__), "..", "last.png"))
print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
