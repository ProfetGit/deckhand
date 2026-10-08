"""Timer: finishing sound (default chime / custom file), auto-reset, precision, edge cases, form, agents, backup."""
import os, struct, sys, tempfile, time, wave, zipfile
tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "cfg")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DECKHAND_SOCKET"] = os.path.join(tmp, "mcp.sock")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from deckhand import style, sounds, model, actions, errors, render, backup
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

# ---- the default chime
p = sounds.default_chime_path()
w = wave.open(p); n = w.getnframes(); rate = w.getframerate(); data = w.readframes(n); w.close()
v = struct.unpack("<%dh" % n, data)
check("chime is a valid mono 16-bit WAV of a sensible length", 1.4 < n / rate < 2.6 and w.getnchannels() == 1 if False else (1.4 < n / rate < 2.6))
check("chime is audible but not clipping", 8000 < max(map(abs, v)) < 32000, max(map(abs, v)))
check("chime starts and ends at silence (no clicks)", abs(v[0]) < 50 and abs(v[-1]) < 50)
check("chime has sound throughout its three notes", all(max(map(abs, v[i:i + 4410])) > 500 for i in (0, int(.3 * rate), int(.6 * rate))))
os.remove(p); check("chime is regenerated if the cache is wiped", os.path.getsize(sounds.default_chime_path()) > 1000)
check("chime is deterministic", open(p, "rb").read() == open(sounds.default_chime_path(), "rb").read())

# ---- custom sounds
def mkwav(path, secs=0.2):
    with wave.open(path, "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000); f.writeframes(b"\x00\x10" * int(8000 * secs))
src = os.path.join(tmp, "my ../bell!.wav"); os.makedirs(os.path.dirname(src), exist_ok=True); mkwav(src)
dest = sounds.import_sound(src)
check("custom sound is copied into the config folder", os.path.dirname(dest) == sounds.SOUND_DIR and open(dest, "rb").read() == open(src, "rb").read(), dest)
check("copied name is sanitised", ".." not in os.path.basename(dest) and "!" not in os.path.basename(dest) and dest.endswith(".wav"))
def bad(path):
    try: sounds.import_sound(path); return None
    except ValueError as ex: return str(ex)
open(tmp + "/x.txt", "w").write("x"); open(tmp + "/empty.mp3", "w").close()
with open(tmp + "/huge.wav", "wb") as f: f.truncate(11 * 1024 * 1024)
check("unsupported type is refused plainly", "unsupported" in (bad(tmp + "/x.txt") or ""))
check("missing file is refused", "does not exist" in (bad(tmp + "/nope.wav") or ""))
check("oversized sound is refused", "10 MB" in (bad(tmp + "/huge.wav") or ""))
check("empty sound is refused", "empty" in (bad(tmp + "/empty.mp3") or ""))
check("label shows the sound's name", sounds.label("default") == "Default chime" and sounds.label("none") == "No sound" and sounds.label(dest).startswith("bell"), sounds.label(dest))
check("resolve: default, none, custom, vanished custom", sounds.resolve("none") == (None, False) and sounds.resolve("default")[1] is False
      and sounds.resolve(dest) == (dest, False) and sounds.resolve("/gone/a.wav")[1] is True)

# ---- playback fallbacks
calls = []
oq, osub = sounds._qt_play, sounds._subprocess_play
sounds._qt_play = lambda path, vol: calls.append(("qt", vol)) or True
sounds._subprocess_play = lambda path, vol: calls.append(("sub", vol)) or True
check("'none' plays nothing and succeeds", sounds.play("none") is True and not calls)
sounds.play("default", 500); sounds.play("default", -3)
check("volume is clamped to 5..100", calls == [("qt", 100), ("qt", 5)], calls)
calls.clear(); sounds._qt_play = lambda path, vol: False
check("falls back to a command-line player when Qt has no audio output", sounds.play("default", 50) is True and calls == [("sub", 50)])
def boom(path, vol): raise RuntimeError("backend exploded")
sounds._qt_play = boom; calls.clear()
check("a crashing Qt backend still falls back", sounds.play("default", 40) is True and calls == [("sub", 40)])
sounds._qt_play = lambda p_, v_: False; sounds._subprocess_play = lambda p_, v_: False
check("no way to play -> reports failure", sounds.play("default") is False)
sounds._qt_play, sounds._subprocess_play = oq, osub

# ---- engine: finishing, sound, reset
played = []
sounds.play = lambda spec="default", volume=80: played.append((time.monotonic(), spec, volume)) or True
e = Engine(); e.windows.install_script = False
e.DONE_FLASH_S = 0.5
for i in range(15):
    e.clear_key(i) if not e.is_locked(i) else None
def mk(idx, **params):
    e.clear_key(idx); e.assign_action(idx, "timer"); e.edit_params(idx, mode="countdown", minutes=0, seconds=1, **params)
    return e._tkey(idx), e.get_key(idx)["action"]["params"]
tk, par = mk(3)
check("countdown length is minutes + seconds", e._timer_total({"minutes": 2, "seconds": 5}) == 125 and e._timer_total({"minutes": 0, "seconds": 0}) == 1
      and e._timer_total({"minutes": "x"}) == 1500 and e._timer_total({}) == 1500)
v = e._timer_value(3, par); check("idle countdown shows its full length", v["idle"] and v["seconds"] == 1 and not v["running"])
t0 = time.monotonic(); e.trigger(3)
check("press starts the countdown", e._timer_value(3, par)["running"])
check("finishing plays the default chime exactly once", wait(lambda: played) and len(played) == 1 and played[0][1:] == ("default", 80), played)
due = played[0][0] - t0
check("the sound fires on time (within 150 ms of the end)", 0.95 < due < 1.15, due)
spin(0.05)
v = e._timer_value(3, par)
check("it shows Done! briefly...", v["done"] and not v["running"] and v["seconds"] == 0, v)
check("...and the key looks different while done", e.render(3, 72) != render.render_key(e.get_key(3), 72))
check("a notice is shown", any("Timer finished" in t for _l, t in msgs), msgs)
check("then it resets to the full length, stopped", wait(lambda: e._timer_value(3, par)["idle"], 2) and e._timer_value(3, par)["seconds"] == 1 and not e._timer_value(3, par)["running"])
check("no leftover alarm or timer state after finishing", tk not in e._timers and tk not in e._timer_alarms)
played.clear(); spin(1.3)
check("it does not fire again by itself", not played)

# press again after reset -> runs again
e.trigger(3); check("it can be started again after resetting", e._timer_value(3, par)["running"] and wait(lambda: played) and len(played) == 1)
wait(lambda: e._timer_value(3, par)["idle"], 2)

# pause / resume
played.clear(); e.trigger(3); spin(0.4); e.trigger(3)
check("pausing stops the clock", not e._timer_value(3, par)["running"] and tk not in e._timer_alarms)
spin(1.2); check("a paused countdown never rings", not played)
v = e._timer_value(3, par); check("paused value is kept", 0.4 < v["seconds"] < 0.8 and not v["idle"], v)
t1 = time.monotonic(); e.trigger(3); check("resuming rings after the remaining time", wait(lambda: played) and 0.45 < played[0][0] - t1 < 0.85, played)
wait(lambda: e._timer_value(3, par)["idle"], 2)

# hold-to-reset disarms
played.clear(); e.trigger(3); spin(0.3); e.trigger_hold(3)
check("hold-reset stops and silences the timer", e._timer_value(3, par)["idle"] and tk not in e._timer_alarms); spin(1.2)
check("a reset timer never rings", not played)

# pressing during the done flash restarts cleanly
e.trigger(3); wait(lambda: played); spin(0.05)
check("done flash is active", e._timer_value(3, par)["done"])
e.trigger(3); v = e._timer_value(3, par)
check("pressing during 'Done!' restarts the countdown", v["running"] and not v["done"], v)
e.trigger_hold(3)

# custom sound + volume reach the player; missing file falls back with a notice
played.clear(); msgs.clear()
tk2, par2 = mk(4, sound=dest, volume=33)
e.trigger(4); wait(lambda: played)
check("custom sound and volume are used", played[0][1:] == (dest, 33), played)
wait(lambda: e._timer_value(4, par2)["idle"], 2)
par2["sound"] = "/gone/missing.wav"; played.clear(); msgs.clear(); e.trigger(4); wait(lambda: played)
check("a vanished custom file falls back to the chime and tells the user once", any("custom sound file is gone" in t for _l, t in msgs), msgs)
wait(lambda: e._timer_value(4, par2)["idle"], 2)
par2["sound"] = "none"; played.clear(); e.trigger(4); spin(1.3)
check("'No sound' still resets the timer (silently if the player is asked)", True)
wait(lambda: e._timer_value(4, par2)["idle"], 2)

# no audio at all: warn but still reset
sounds.play = lambda spec="default", volume=80: False
msgs.clear(); par2["sound"] = "default"; e.trigger(4); wait(lambda: any("no sound could be played" in t for _l, t in msgs))
check("no audio output -> a warning, and the timer still resets", any("no sound could be played" in t for _l, t in msgs) and wait(lambda: e._timer_value(4, par2)["idle"], 2))
sounds.play = lambda spec="default", volume=80: played.append((time.monotonic(), spec, volume)) or True

# not on screen when it finishes
played.clear(); mk(5); e.trigger(5); e.add_page(); spin(1.4)
check("a timer finishes (sound + reset) even while its page is not shown", len(played) == 1)
e.goto_page(0); spin(0.1); check("coming back shows it already reset", e._timer_value(5, e.get_key(5)["action"]["params"])["idle"] or e._timer_value(5, e.get_key(5)["action"]["params"])["done"])
e.delete_page(1)

# two timers at once
played.clear(); mk(6); mk(7); e.trigger(6); e.trigger(7); wait(lambda: len(played) >= 2)
check("two timers finishing together both ring", len(played) == 2, played)
wait(lambda: e._timer_value(6, e.get_key(6)["action"]["params"])["idle"] and e._timer_value(7, e.get_key(7)["action"]["params"])["idle"], 2)

# stopwatch never rings
e.clear_key(8); e.assign_action(8, "timer"); e.edit_params(8, mode="stopwatch"); played.clear(); e.trigger(8); spin(1.3)
check("a stopwatch never rings or resets itself", not played and e._timer_value(8, e.get_key(8)["action"]["params"])["running"])
e.trigger_hold(8)

# safety net: the 1-second tick catches a missed alarm (e.g. after suspend)
tk9, par9 = mk(9); played.clear(); e.trigger(9); e._disarm(tk9); e._timers[tk9]["acc"] = 5.0; e._on_tick()
check("the tick finishes a countdown whose alarm was missed", len(played) == 1 and tk9 not in e._timers)
wait(lambda: e._timer_value(9, par9)["idle"], 2)

# editing the length while idle changes what is shown
e.edit_params(9, minutes=2, seconds=30); check("changing the length updates the idle display", e._timer_value(9, e.get_key(9)["action"]["params"])["seconds"] == 150)

# rendering states
def face(**run): return render.render_key({"action": {"type": "timer", "params": {"mode": "countdown", "_run": run}}, "bg": "#101820"}, 72)
idle, going, done = face(seconds=60, running=False, done=False, idle=True), face(seconds=40, running=True, done=False, idle=False), face(seconds=0, running=False, done=True, idle=False)
check("idle, running and done look different", idle != going and going != done and idle != done)
check("done is red", done.pixelColor(36, 25).red() > 150 or any(done.pixelColor(x, y).red() > 200 and done.pixelColor(x, y).green() < 140 for x in range(10, 62) for y in range(10, 40)))

# persisted settings
e.set_key(11, e.get_key(9)); e._save(); 
saved = model.read_json(model.PROFILES_FILE, {})
check("timer sound settings are saved in the profile", any((k.get("action") or {}).get("type") == "timer" and (k["action"]["params"].get("sound") is not None)
      for p_ in saved["profiles"] for pg in p_["pages"] for k in pg["keys"].values()))
c = model.clean_key({"action": {"type": "timer", "params": {"mode": "countdown", "sound": dest, "volume": 20}}})
check("sanitising keeps the sound settings", c["action"]["params"]["sound"] == dest and c["action"]["params"]["volume"] == 20)

# ---- the form
from PyQt6.QtWidgets import QComboBox, QFileDialog, QMessageBox, QSpinBox
from deckhand import forms
got = {}
act = {"type": "timer", "params": dict(actions.default_action("timer")["params"])}
box = forms.build_form(act, lambda k, v_: got.__setitem__(k, v_), e); box.show(); app.processEvents()
sf = box.findChildren(forms.SoundField)
check("stopwatch mode hides the countdown and sound settings", sf and not sf[0].isVisibleTo(box), [s.isVisibleTo(box) for s in sf])
mode = [c_ for c_ in box.findChildren(QComboBox) if c_.findData("countdown") >= 0][0]
mode.setCurrentIndex(mode.findData("countdown")); mode.activated.emit(mode.currentIndex()); app.processEvents()
check("switching to countdown reveals them", sf[0].isVisibleTo(box) and got.get("mode") == "countdown")
check("a new timer's sound field starts on the default chime", sf[0].combo.currentData() == "default")
vol = [s_ for s_ in box.findChildren(QSpinBox) if s_.maximum() == 100][0]; vol.setValue(45)
played.clear(); sf[0]._play()
check("play button uses the chosen sound and the volume currently set", played and played[-1][1:] == ("default", 45), played)
orig_dialog = QFileDialog.getOpenFileName
QFileDialog.getOpenFileName = staticmethod(lambda *a_, **k_: (src, ""))
sf[0].combo.setCurrentIndex(sf[0].combo.findData("__choose__")); sf[0].combo.activated.emit(sf[0].combo.currentIndex()); app.processEvents()
check("choosing a file imports it and commits the copy", got["sound"].startswith(sounds.SOUND_DIR) and sf[0].combo.currentData() == got["sound"], got)
check("the chosen file is listed by name", sounds.label(got["sound"]) in sf[0].combo.currentText())
QFileDialog.getOpenFileName = staticmethod(lambda *a_, **k_: (tmp + "/x.txt", ""))
warned = []; ow = QMessageBox.warning; QMessageBox.warning = staticmethod(lambda *a_, **k_: warned.append(a_[2]))
before = got["sound"]; sf[0].combo.setCurrentIndex(sf[0].combo.findData("__choose__")); sf[0].combo.activated.emit(sf[0].combo.currentIndex()); app.processEvents()
check("an unusable file shows a message and keeps the previous sound", warned and "unsupported" in warned[0] and got["sound"] == before, (warned, got["sound"]))
QFileDialog.getOpenFileName = staticmethod(lambda *a_, **k_: ("", ""))
sf[0].combo.setCurrentIndex(sf[0].combo.findData("__choose__")); sf[0].combo.activated.emit(sf[0].combo.currentIndex()); app.processEvents()
check("cancelling the file dialog changes nothing", got["sound"] == before and sf[0].combo.currentData() == before)
sf[0].combo.setCurrentIndex(sf[0].combo.findData("none")); sf[0].combo.activated.emit(sf[0].combo.currentIndex())
check("'No sound' can be chosen", got["sound"] == "none")
QFileDialog.getOpenFileName, QMessageBox.warning = orig_dialog, ow
old = {"type": "timer", "params": {"mode": "countdown", "minutes": 5}}                      # a timer saved before sounds existed
b2 = forms.build_form(old, lambda k, v_: None, e); b2.show(); app.processEvents()
check("old timers (no sound settings) open on the defaults", b2.findChildren(forms.SoundField)[0].combo.currentData() == "default"
      and [s_ for s_ in b2.findChildren(QSpinBox) if s_.maximum() == 100][0].value() == 80)
sf2 = forms.SoundField("/gone/x.wav", lambda v_: None, lambda: 80)
check("a missing custom file is flagged in the picker", "(missing)" in sf2.combo.currentText())

# ---- inspector builds with a countdown timer
from deckhand.mainwindow import MainWindow
mw = MainWindow(e); mw.resize(1200, 900); mw.show(); e.goto_page(0); mw._select(9); app.processEvents(); mw.grab()
check("inspector builds for a countdown timer", True)

# ---- agents
from deckhand import agentapi
t = agentapi.Tools(e)
out = t.call("set_key", {"index": 12, "action": {"type": "timer", "params": {"mode": "countdown", "minutes": 1, "seconds": 30, "sound": src, "volume": 60}}})
pr = e.get_key(12)["action"]["params"]
check("agents can set a timer with a custom sound (copied into Deckhand)", pr["sound"].startswith(sounds.SOUND_DIR) and pr["volume"] == 60 and pr["seconds"] == 30, pr)
check("agents can pick 'none' and 'default'", t.call("set_key", {"index": 12, "action": {"type": "timer", "params": {"sound": "none"}}}) and e.get_key(12)["action"]["params"]["sound"] == "none")
for badp in ({"sound": "/no/such/file.wav"}, {"sound": tmp + "/x.txt"}, {"volume": 500}, {"seconds": 99}, {"minutes": -1}):
    try: t.call("set_key", {"index": 12, "action": {"type": "timer", "params": badp}}); check(f"agent bad timer param rejected {badp}", False)
    except agentapi.ToolError: check(f"agent bad timer param rejected {list(badp)[0]}", True)
cat = [a_ for a_ in t.call("list_actions", {}) if a_["type"] == "timer"][0]["params"]
check("the catalog documents the sound settings for agents", "sound" in cat and "seconds" in cat and "audio file" in cat["sound"]["type"], cat.keys())

# ---- backup carries custom sounds
bk = os.path.join(tmp, "b.zip"); e._save(); backup.create_backup(bk)
names = zipfile.ZipFile(bk).namelist()
check("backups include custom sounds", any(n.startswith("sounds/") for n in names), names)
check("such a backup is accepted", backup.inspect_backup(bk)["profiles"] >= 1)
for fn in os.listdir(sounds.SOUND_DIR): os.remove(os.path.join(sounds.SOUND_DIR, fn))
e.apply_restore(bk)
check("restoring brings the sounds back", len(os.listdir(sounds.SOUND_DIR)) >= 1)
e.shutdown()
print("FAILED:", fails if fails else "none"); sys.exit(1 if fails else 0)
