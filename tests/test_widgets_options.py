"""Widget appearance options (clock, system monitor, counter, timer, now playing) and the polished plain actions."""
import http.server, os, sys, tempfile, threading, time
tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "cfg")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DECKHAND_SOCKET"] = os.path.join(tmp, "mcp.sock")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from deckhand import style, model, actions, errors, render, sysinfo, forms, agentapi
app.setStyleSheet(style.QSS)
from deckhand.engine import Engine

fails = []
def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond: fails.append(name)
def spin(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.004)
def wait(cond, sec=4):
    end = time.monotonic() + sec
    while time.monotonic() < end and not cond():
        app.processEvents(); time.sleep(0.004)
    return cond()
msgs = []; errors.notifier.message.connect(lambda lv, t: msgs.append((lv, t)))

sysinfo.cpu_percent = lambda: 40.0
sysinfo.ram_percent = lambda: 70.0
sysinfo.gpu_percent = lambda: (92.0, 0, 61.0)

def face(atype, params, **key):
    return render.render_key({"action": {"type": atype, "params": params}, "bg": "#000000", **key}, 72)
def count(img, rgb, tol=60, box=None):
    x0, y0, x1, y1 = box or (0, 0, img.width(), img.height())
    n = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            c = img.pixelColor(x, y)
            if abs(c.red() - rgb[0]) <= tol and abs(c.green() - rgb[1]) <= tol and abs(c.blue() - rgb[2]) <= tol:
                n += 1
    return n
def lit(img, box):
    x0, y0, x1, y1 = box
    return sum(1 for y in range(y0, y1) for x in range(x0, x1) if img.pixelColor(x, y).lightness() > 90)
PINK = (255, 0, 200)

# ---- old keys (no new params) look exactly like the defaults
for aid in ("clock", "sysmon", "counter", "timer", "nowplaying"):
    old = {k: v for k, v in actions.default_action(aid)["params"].items() if k in ("metric", "fmt", "date", "seconds", "step", "value", "label", "mode", "show_art", "show_text", "hold_next")}
    if aid == "timer": old["_run"] = {"seconds": 30, "running": True, "done": False, "idle": False}
    if aid == "nowplaying": old["_np"] = {"title": "Song", "artist": "Band", "status": "Paused"}
    new = {**actions.default_action(aid)["params"], **{k: v for k, v in old.items() if k.startswith("_")}}
    check(f"{aid}: a saved key without the new options draws the same as one with the defaults", face(aid, old) == face(aid, new))

# ---- system monitor
bars = {"metric": "both"}
base = face("sysmon", bars)
check("sysmon: name colour changes the CPU/RAM text", count(face("sysmon", {**bars, "label_color": "#ff00c8"}), PINK) > 8 and count(base, PINK) == 0)
check("sysmon: percentage colour changes the numbers", count(face("sysmon", {**bars, "value_color": "#ff00c8"}), PINK) > 8)
check("sysmon: hiding the names removes text pixels", face("sysmon", {**bars, "show_label": False}) != base)
check("sysmon: hiding the percentage removes text pixels", face("sysmon", {**bars, "show_value": False}) != base)
hidden = face("sysmon", {**bars, "show_label": False, "show_value": False})
check("sysmon: with both hidden only bars remain (no light text)", lit(hidden, (8, 14, 64, 32)) < lit(base, (8, 14, 64, 32)))
fixed = face("sysmon", {**bars, "color_mode": "fixed", "bar_color": "#ff00c8"})
check("sysmon: fixed bar colour", count(fixed, PINK, 30) > 150 and count(base, PINK, 30) == 0)
check("sysmon: by-load colours follow the thresholds (70% is amber by default, green once amber starts at 80)",
      count(face("sysmon", {**bars}), (255, 176, 32)) > 50 and count(face("sysmon", {**bars, "warn": 80, "crit": 95}), (255, 176, 32)) == 0)
check("sysmon: lowering the red threshold turns the 40% bar red", count(face("sysmon", {**bars, "warn": 10, "crit": 30}), (255, 90, 95)) > 50)
check("sysmon: swapped thresholds cannot crash or invert", face("sysmon", {**bars, "warn": 90, "crit": 20}).width() == 72)
for m in ("cpu", "ram", "gpu"):
    g = {"metric": m}
    check(f"sysmon {m}: label colour", count(face("sysmon", {**g, "label_color": "#ff00c8"}), PINK) > 8)
    check(f"sysmon {m}: value colour", count(face("sysmon", {**g, "value_color": "#ff00c8"}), PINK) > 8)
    check(f"sysmon {m}: hide label/value", face("sysmon", {**g, "show_label": False}) != face("sysmon", g) and face("sysmon", {**g, "show_value": False}) != face("sysmon", g))
    check(f"sysmon {m}: fixed colour", count(face("sysmon", {**g, "color_mode": "fixed", "bar_color": "#ff00c8"}), PINK, 30) > 40)
check("sysmon gpu: temperature can be hidden", face("sysmon", {"metric": "gpu", "show_temp": False}) != face("sysmon", {"metric": "gpu"}))
check("sysmon: junk colour falls back instead of failing", face("sysmon", {**bars, "label_color": "banana", "bar_color": 5, "warn": "x"}) == base)

# ---- clock
now = time.localtime()
c0 = {"fmt": "24h", "date": True, "seconds": False}
c_base = face("clock", c0)
check("clock: time colour", count(face("clock", {**c0, "color": "#ff00c8"}), PINK) > 30 and count(c_base, PINK) == 0)
check("clock: date colour", count(face("clock", {**c0, "date_color": "#ff00c8"}), PINK, box=(0, 50, 72, 68)) > 10)
check("clock: time colour defaults to the key's text colour", count(face("clock", c0, title_color="#ff00c8"), PINK) > 30)
check("clock: the explicit colour wins over the key's text colour", count(face("clock", {**c0, "color": "#00ff00"}, title_color="#ff00c8"), PINK) == 0)
check("clock: date formats differ", len({face("clock", {**c0, "date_fmt": f}).constBits().asstring(72 * 72 * 4) for f, _l in actions.DATE_FORMATS}) >= 4)
check("clock: every date format is known to the renderer and valid strftime", all(f in render.DATE_FORMATS and time.strftime(render.DATE_FORMATS[f], now) for f, _l in actions.DATE_FORMATS))
check("clock: date can be hidden", lit(face("clock", {**c0, "date": False}), (0, 50, 72, 68)) == 0 and lit(c_base, (0, 50, 72, 68)) > 0)
c12 = {"fmt": "12h", "date": False, "seconds": False}
check("clock: AM/PM can be hidden", face("clock", {**c12, "ampm": False}) != face("clock", c12))
check("clock: size scales the time", lit(face("clock", {**c0, "scale": 140}), (0, 8, 72, 46)) > lit(face("clock", {**c0, "scale": 60}), (0, 8, 72, 46)))
check("clock: size is clamped (nonsense does not crash)", face("clock", {**c0, "scale": 9999}).width() == 72 and face("clock", {**c0, "scale": "x"}) == c_base)

# ---- counter
k0 = {"value": 7, "label": "Lives", "step": 1}
check("counter: number colour", count(face("counter", {**k0, "color": "#ff00c8"}), PINK) > 30)
check("counter: label colour", count(face("counter", {**k0, "label_color": "#ff00c8"}), PINK, box=(0, 50, 72, 68)) > 8)
check("counter: below-zero colour only applies below zero", count(face("counter", {**k0, "value": -3, "negative_color": "#ff00c8"}), PINK) > 30
      and count(face("counter", {**k0, "negative_color": "#ff00c8"}), PINK) == 0)
check("counter: size", lit(face("counter", {**k0, "scale": 140}), (0, 8, 72, 44)) > lit(face("counter", {**k0, "scale": 60}), (0, 8, 72, 44)))
check("counter: a corrupt value draws zero instead of failing", face("counter", {"value": "abc"}) == face("counter", {"value": 0}))

# ---- timer
def tface(run, **p): return face("timer", {"mode": "countdown", "_run": run, **p})
IDLE = dict(seconds=60, running=False, done=False, idle=True)
GO = dict(seconds=40, running=True, done=False, idle=False)
PAUSE = dict(seconds=40, running=False, done=False, idle=False)
DONE = dict(seconds=0, running=False, done=True, idle=False)
cap = (0, 50, 72, 68)
check("timer: caption is shown by default", lit(tface(IDLE), cap) > 20)
check("timer: caption can be hidden", lit(tface(IDLE, show_caption=False), cap) == 0)
check("timer: hiding the caption centres the time", lit(tface(IDLE, show_caption=False), (0, 14, 72, 58)) > 40)
check("timer: caption hidden also while running/paused/done", all(lit(tface(r, show_caption=False), cap) == 0 for r in (GO, PAUSE, DONE)))
check("timer: caption colour", count(tface(IDLE, caption_color="#ff00c8"), PINK, box=cap) > 20)
check("timer: idle time colour", count(tface(IDLE, color="#ff00c8"), PINK, box=(0, 8, 72, 44)) > 30)
check("timer: running time colour (default green)", count(tface(GO), (61, 220, 132), box=(0, 8, 72, 44)) > 30)
check("timer: running time colour override", count(tface(GO, run_color="#ff00c8"), PINK, box=(0, 8, 72, 44)) > 30 and count(tface(GO, run_color="#ff00c8"), (61, 220, 132)) == 0)
check("timer: paused colour", count(tface(PAUSE, paused_color="#ff00c8"), PINK, box=(0, 8, 72, 44)) > 30)
check("timer: paused falls back to the idle colour", count(tface(PAUSE, color="#ff00c8"), PINK, box=(0, 8, 72, 44)) > 30)
check("timer: finished colour", count(tface(DONE, done_color="#ff00c8"), PINK, box=(0, 8, 72, 44)) > 30)
check("timer: size", lit(tface(IDLE, scale=140), (0, 8, 72, 44)) > lit(tface(IDLE, scale=60), (0, 8, 72, 44)))
check("timer: stopwatch idle caption is its own word (not the countdown one)", face("timer", {"mode": "stopwatch", "_run": IDLE}) != tface(IDLE))

# ---- now playing
npp = {"_np": {"title": "Long song title", "artist": "Some artist", "status": "Playing", "art": ""}}
check("nowplaying: title colour", count(face("nowplaying", {**npp, "text_color": "#ff00c8"}), PINK, box=(0, 38, 72, 56)) > 10)
check("nowplaying: artist colour", count(face("nowplaying", {**npp, "artist_color": "#ff00c8"}), PINK, box=(0, 54, 72, 72)) > 5)
check("nowplaying: artist line can be hidden", face("nowplaying", {**npp, "show_artist": False}) != face("nowplaying", npp))
paused = {"_np": {**npp["_np"], "status": "Paused"}}
check("nowplaying: paused dimming can be turned off", face("nowplaying", paused) != face("nowplaying", {**paused, "dim_paused": False})
      and lit(face("nowplaying", {**paused, "dim_paused": False}), (0, 0, 72, 30)) >= lit(face("nowplaying", paused), (0, 0, 72, 30)))

# ---- the inspector form
e = Engine(); e.windows.install_script = False
for i in range(15):
    if not e.is_locked(i): e.clear_key(i)
e.assign_action(0 if not e.is_locked(0) else 1, "sysmon")
idx = 0 if not e.is_locked(0) else 1
act = e.get_key(idx)["action"]
got = {}
box = forms.build_form(act, lambda k, v: got.__setitem__(k, v), e); box.show(); app.processEvents()
cfs = box.findChildren(forms.ColorField)
check("form: sysmon shows its colour pickers", len(cfs) == 3, len(cfs))
vis = lambda: [c.isVisibleTo(box) for c in cfs]
check("form: the fixed bar colour is hidden while colouring by load", vis() == [True, True, False], vis())
cm = [c for c in box.findChildren(forms.QComboBox) if c.findData("fixed") >= 0][0]
cm.setCurrentIndex(cm.findData("fixed")); cm.activated.emit(cm.currentIndex()); app.processEvents()
check("form: choosing a fixed colour reveals the picker", vis() == [True, True, True] and got.get("color_mode") == "fixed", vis())
cfs[0]._picked("#112233")
check("form: picking a colour commits it", got.get("label_color") == "#112233" and cfs[0].auto.isEnabled())
cfs[0]._reset()
check("form: Auto commits an empty colour", got.get("label_color") == "" and not cfs[0].auto.isEnabled() and cfs[0].state.text() == "Auto")
e.edit_params(idx, label_color="#ff00c8", show_value=False)
k = e.get_key(idx)
check("engine: the options persist in the key and change the rendered face", k["action"]["params"]["label_color"] == "#ff00c8" and count(e.render(idx), PINK) > 8)
e._save()
saved = model.read_json(model.PROFILES_FILE, {})
check("options are written to the profile file", any((kk.get("action") or {}).get("params", {}).get("label_color") == "#ff00c8"
      for p_ in saved["profiles"] for pg in p_["pages"] for kk in pg["keys"].values()))
check("sanitising keeps the new options", model.clean_key(k)["action"]["params"]["label_color"] == "#ff00c8")
for aid in ("clock", "sysmon", "counter", "timer", "nowplaying"):
    b = forms.build_form(actions.default_action(aid), lambda k_, v_: None, e); b.show(); app.processEvents()
    check(f"form: {aid} builds with every field", len(b.findChildren(forms.QWidget)) > 5)
from deckhand.mainwindow import MainWindow
mw = MainWindow(e); mw.resize(1200, 900); mw.show()
for aid in ("clock", "counter", "timer", "nowplaying", "sysmon", "command", "screenshot", "http", "website", "file", "text", "volup"):
    e.assign_action(idx, aid); mw._select(idx); app.processEvents(); mw.grab()
check("inspector builds for every changed action", True)

# ---- the wheel scrolls the page, never the values
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget, QComboBox
from deckhand import wheelguard
wheelguard.install(app)
sa = QScrollArea(); sa.setWidgetResizable(True); host = QWidget(); vl = QVBoxLayout(host)
sf_ = forms.SpinField(0, 100, 30, lambda v: None); cb = forms.compact_combo(QComboBox()); cb.addItems(["a", "b", "c"])
vl.addWidget(sf_); vl.addWidget(cb)
for _i in range(30): vl.addWidget(forms.QLabel(f"filler {_i}"))
sa.setWidget(host); sa.resize(300, 200); sa.show(); app.processEvents()
def wheel(w, dy):
    pos = QPointF(w.width() / 2, w.height() / 2)
    ev = QWheelEvent(pos, w.mapToGlobal(pos), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(w, ev); app.processEvents()
bar = sa.verticalScrollBar(); b0 = bar.value()
wheel(sf_.spin, -120); wheel(sf_.spin, 120)
wheel(cb, -120)
check("wheel over a number box does not change it", sf_.value() == 30)
check("wheel over a dropdown does not change it", cb.currentIndex() == 0)
wheel(sf_.spin, -120); check("wheel over a control scrolls the page instead", bar.value() > b0, bar.value())
sa.close()

# ---- agents
t = agentapi.Tools(e)
def setp(aid, params, i=2): return t.call("set_key", {"index": i, "action": {"type": aid, "params": params}})
setp("sysmon", {"label_color": "#FF00C8", "color_mode": "fixed", "bar_color": "red", "warn": 50, "crit": 90, "show_value": "false"})
pr = e.get_key(2)["action"]["params"]
check("agents: colours are normalised to #rrggbb, bools and ints coerced", pr["label_color"] == "#ff00c8" and pr["bar_color"] == "#ff0000" and pr["show_value"] is False and pr["warn"] == 50, pr)
setp("sysmon", {"label_color": ""}); check("agents: '' and 'auto' mean the built-in colour", e.get_key(2)["action"]["params"]["label_color"] == "")
setp("timer", {"caption_color": "auto"}); check("agents: 'auto' accepted", e.get_key(2)["action"]["params"]["caption_color"] == "")
for aid, bad in (("sysmon", {"label_color": "banana"}), ("sysmon", {"warn": 0}), ("sysmon", {"crit": 101}), ("sysmon", {"color_mode": "rainbow"}),
                 ("clock", {"scale": 500}), ("clock", {"date_fmt": "klingon"}), ("timer", {"show_caption": "maybe"}), ("counter", {"color": 5}),
                 ("screenshot", {"delay": 99}), ("screenshot", {"mode": "nowhere"}), ("volup", {"step": 80}), ("text", {"delay": 60}), ("nowplaying", {"text_color": "zzz"})):
    try: setp(aid, bad); check(f"agents: bad {aid} param rejected {bad}", False)
    except agentapi.ToolError: check(f"agents: bad {aid} param rejected {list(bad)[0]}", True)
cat = {a_["type"]: a_["params"] for a_ in t.call("list_actions", {})}
need = {"sysmon": ("label_color", "value_color", "bar_color", "color_mode", "warn", "crit", "show_label", "show_value", "show_temp"),
        "clock": ("color", "date_color", "date_fmt", "ampm", "scale"), "counter": ("color", "label_color", "negative_color", "scale"),
        "timer": ("show_caption", "caption_color", "color", "run_color", "paused_color", "done_color", "scale"),
        "nowplaying": ("text_color", "artist_color", "show_artist", "dim_paused"), "command": ("workdir", "notify"),
        "screenshot": ("delay", "pointer"), "http": ("show_response",), "website": ("browser",), "file": ("with",), "text": ("delay",), "volup": ("step",), "voldown": ("step",)}
for aid, keys in need.items():
    check(f"catalog documents the new {aid} options", all(k_ in cat[aid] for k_ in keys), [k_ for k_ in keys if k_ not in cat[aid]])
check("catalog marks colour params and the conditions they depend on", "colour" in cat["sysmon"]["label_color"]["type"] and cat["sysmon"]["bar_color"].get("only_when") == {"color_mode": "fixed"}, cat["sysmon"]["bar_color"])
for aid, a_ in actions.ACTIONS.items():
    if aid in ("folder", "delay"): continue
    for f in a_["fields"]:
        try: agentapi._coerce(e, f, a_["defaults"].get(f["key"]), []) if f["type"] not in ("app", "profile", "sound", "audio_in", "audio_out") else None
        except agentapi.ToolError as ex: check(f"default of {aid}.{f['key']} passes validation", False, ex)
check("every field default passes its own validation", True)

# ---- plain actions
spawned = []
orig_spawn, orig_watched = actions._spawn, actions._spawn_watched
actions._spawn = lambda args, **kw: spawned.append(("spawn", args, kw))
actions._spawn_watched = lambda args, what, wait=2.0, cwd=None: spawned.append(("watched", args, cwd))
run = lambda aid, **p: actions.run({"type": aid, "params": {**actions.default_action(aid)["params"], **p}}, e)

run("screenshot", mode="screen", delay=3, pointer=True)
check("screenshot: current screen, delay and pointer reach spectacle", spawned[-1][1] == ["spectacle", "-m", "-p", "-d", "3000"], spawned[-1])
run("screenshot"); check("screenshot: defaults unchanged", spawned[-1][1] == ["spectacle", "-r"], spawned[-1])
run("screenshot", mode="full", clipboard=True); check("screenshot: clipboard still works", spawned[-1][1] == ["spectacle", "-f", "-c", "-b"], spawned[-1])

fake_app = {"name": "FakeBrowser", "path": "/usr/share/applications/fake.desktop"}
orig_find = actions.find_app
actions.find_app = lambda a: fake_app if a == "fake.desktop" else None
run("website", url="example.org"); check("website: default browser via xdg-open", spawned[-1][1] == ["xdg-open", "https://example.org"], spawned[-1])
run("website", url="example.org", browser="fake.desktop"); check("website: a chosen browser opens the link", spawned[-1][1] == ["gio", "launch", fake_app["path"], "https://example.org"], spawned[-1])
try: run("website", url="example.org", browser="gone.desktop"); check("website: an uninstalled browser is reported", False)
except RuntimeError as ex: check("website: an uninstalled browser is reported", "not installed" in str(ex))
run("file", path=tmp, **{"with": "fake.desktop"}); check("file: open with a chosen app", spawned[-1][1] == ["gio", "launch", fake_app["path"], tmp], spawned[-1])
run("file", path=tmp); check("file: default app", spawned[-1][1] == ["xdg-open", tmp])
actions.find_app = orig_find

run("command", cmd="true", workdir=tmp); check("command: working folder is used", spawned[-1][2] == tmp, spawned[-1])
try: run("command", cmd="true", workdir=tmp + "/nope"); check("command: a missing working folder is reported", False)
except RuntimeError as ex: check("command: a missing working folder is reported", "does not exist" in str(ex))
run("command", cmd="true", terminal=True, workdir=tmp); check("command: terminal opens in the working folder", "--workdir" in spawned[-1][1] and tmp in spawned[-1][1], spawned[-1])
actions._spawn, actions._spawn_watched = orig_spawn, orig_watched

msgs.clear(); run("command", cmd="echo fine", notify=True)
check("command: notify reports success", wait(lambda: any("Finished: echo fine" in m for _l, m in msgs)), msgs)
msgs.clear(); run("command", cmd="echo oops >&2; exit 3", notify=True)
check("command: notify reports failure with the error line", wait(lambda: any(l == "warn" and "oops" in m and "(3)" in m for l, m in msgs)), msgs)
cwd_out = os.path.join(tmp, "pwd.txt")
run("command", cmd=f"pwd > {cwd_out}", workdir=tmp); wait(lambda: os.path.exists(cwd_out) and os.path.getsize(cwd_out) > 0, 3)
check("command: it really runs in the working folder", os.path.exists(cwd_out) and os.path.realpath(open(cwd_out).read().strip()) == os.path.realpath(tmp))

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"first line\nsecond line\n")
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_port}/"
errors._last.clear(); msgs.clear(); run("http", url=url)
check("http: default notice has just the status", ("ok", "Request sent: 200") in msgs, msgs)
errors._last.clear(); msgs.clear(); run("http", url=url, show_response=True)
check("http: the response line can be shown", any("Request sent: 200 - second line" in m for _l, m in msgs), msgs)
srv.shutdown()

calls = []
import subprocess
orig_run = subprocess.run
subprocess.run = lambda args, *a, **kw: calls.append(args) or type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
run("volup", step=7); run("voldown", step=3)
check("volume: a custom step goes through wpctl", calls[0] == ["wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", "7%+"] and calls[1][-1] == "3%-", calls)
taps = []
orig_avail, orig_tap = actions.keymap.keyboard.available, actions.keymap.keyboard.tap
actions.keymap.keyboard.available = lambda: True; actions.keymap.keyboard.tap = lambda keys, mods=None: taps.append(keys)
run("volup", step=0); check("volume: step 0 keeps the system key", taps == [[actions.keymap.KEY_VOLUP]] and len(calls) == 2, (taps, calls))
subprocess.run = orig_run

slept = []
orig_sleep = actions.time.sleep
actions.time.sleep = lambda s_: slept.append(s_)
subprocess.run = lambda args, *a, **kw: type("R", (), {"returncode": 1, "stdout": b"", "stderr": b""})()
run("text", text="hi", delay=2)
check("text: waits the chosen time before typing", slept and slept[0] == 2, slept)
actions.time.sleep = orig_sleep; subprocess.run = orig_run
actions.keymap.keyboard.available, actions.keymap.keyboard.tap = orig_avail, orig_tap

# ---- visual before/after, if asked
out = os.environ.get("DECKHAND_OPTIONS_PNG")
if out:
    from PyQt6.QtGui import QImage, QPainter, QColor
    cases = [("clock", {"fmt": "24h", "date": True}), ("sysmon", {"metric": "both"}), ("sysmon", {"metric": "gpu"}), ("counter", {"value": 12, "label": "Kills"}),
             ("timer", {"mode": "countdown", "_run": IDLE}), ("timer", {"mode": "countdown", "_run": GO})]
    styled = [("clock", {"fmt": "12h", "date": True, "date_fmt": "fi", "color": "#00e5ff", "date_color": "#ff9a3c", "scale": 110}),
              ("sysmon", {"metric": "both", "label_color": "#00e5ff", "value_color": "#ffd24a", "color_mode": "fixed", "bar_color": "#7a5cff"}),
              ("sysmon", {"metric": "gpu", "label_color": "#ff9a3c", "value_color": "#ff9a3c", "warn": 30, "crit": 60, "show_temp": False}),
              ("counter", {"value": -4, "label": "Lives", "negative_color": "#ff5a5f", "label_color": "#00e5ff", "scale": 120}),
              ("timer", {"mode": "countdown", "_run": IDLE, "show_caption": False, "color": "#ffd24a"}),
              ("timer", {"mode": "countdown", "_run": GO, "run_color": "#00e5ff", "caption_color": "#ff9a3c"})]
    sheet = QImage(6 * 84 + 12, 2 * 84 + 12, QImage.Format.Format_RGB32); sheet.fill(QColor("#14161c"))
    q = QPainter(sheet)
    for r, row in enumerate((cases, styled)):
        for c, (a_, p_) in enumerate(row):
            q.drawImage(12 + c * 84, 12 + r * 84, face(a_, p_, bg="#10141c"))
    q.end(); sheet.scaled(sheet.width() * 3, sheet.height() * 3).save(out)

e.shutdown()
print("FAILED:", fails if fails else "none"); sys.exit(1 if fails else 0)
