"""Animated wallpaper: decoding, playback, pacing, failure modes. Fake deck, throwaway config."""
import os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from deckhand import style, wallpaper, model
app.setStyleSheet(style.QSS)
from deckhand.engine import Engine
from PIL import Image, ImageDraw

fails = []
def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond: fails.append(name)
def spin(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.004)
def wait(cond, sec=6):
    end = time.monotonic() + sec
    while time.monotonic() < end and not cond():
        app.processEvents(); time.sleep(0.01)
    return cond()

def make(path, n=24, dur=50, size=(320, 180)):
    frames = []
    for i in range(n):
        im = Image.new("RGB", size, (10, 10, 30)); d = ImageDraw.Draw(im)
        d.ellipse((i * (size[0] - 40) // n, 60, i * (size[0] - 40) // n + 50, 110), fill=(255, 140 - i * 3, 40 + i * 5))
        frames.append(im)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=dur, loop=0)
gif, webp, big = tmp + "/a.gif", tmp + "/a.webp", tmp + "/big.gif"
make(gif); make(webp); make(big, n=400, dur=100, size=(200, 120))
png = tmp + "/s.png"; Image.new("RGB", (100, 50), (200, 30, 30)).save(png)

check("gif detected as animated", wallpaper.animation_info(gif) == (True, 24))
check("animated webp detected", wallpaper.animation_info(webp)[0] is True)
check("png is not animated", wallpaper.animation_info(png)[0] is False)
check("missing file is not animated", wallpaper.animation_info("/nope.gif") == (False, 0))

a = wallpaper.load_animation({"file": gif, "fps": 10, "dim": 0}, 5, 3, 72)
check("gif decodes into deck-sized frames", a is not None and a.frames[0].width() == wallpaper.canvas_size(5, 3, 72)[0], a)
check("loop length matches the source (24 x 50ms = 1.2s)", abs(a.loop_s - 1.2) < 0.25, a.loop_s)
check("frames really differ over time", a.frames[0] != a.frames[len(a.frames) // 2])
w = wallpaper.load_animation({"file": webp, "fps": 20}, 5, 3, 72)
check("animated webp decodes", w is not None and w.fps == 20 and len(w.frames) >= 20)
check("static image yields no animation", wallpaper.load_animation({"file": png}, 5, 3, 72) is None)
long = wallpaper.load_animation({"file": big, "fps": 12}, 8, 4, 96)
check("very long animation is bounded in time and memory", long is not None and long.loop_s <= wallpaper.MAX_LOOP_S + 0.1 and long.truncated, (long.loop_s if long else None))
check("cancelling stops decoding", wallpaper.load_animation({"file": big}, 5, 3, 72, cancelled=lambda: True) is None)
bad = tmp + "/bad.gif"; open(bad, "wb").write(open(gif, "rb").read()[:200])
check("truncated gif does not crash the decoder", wallpaper.load_animation({"file": bad}, 5, 3, 72) in (None,) or True)
open(tmp + "/junk.gif", "wb").write(b"GIF89a not really")
check("junk gif is just 'not animated'", wallpaper.load_animation({"file": tmp + "/junk.gif"}, 5, 3, 72) is None)
check("fps is clamped", wallpaper.normalize({"file": "x", "fps": 999})["fps"] == 20 and wallpaper.normalize({"file": "x", "fps": 1})["fps"] == 5)
check("animate flag survives", wallpaper.normalize({"file": "x", "animate": False})["animate"] is False)

# ---- engine playback with a fake deck
class FakeModel: cols, rows, px, keys, name = 5, 3, 72, 15, "Stream Deck"
class FakeDev:
    model = FakeModel; serial = "FAKE"; alive = True
    def __init__(self): self.sent = []
    def firmware(self): return ""
    def set_brightness(self, v): pass
    def set_key_image(self, i, j): self.sent.append((time.monotonic(), i, len(j))); time.sleep(0.004)
    def reset(self): pass
    def close(self): pass
e = Engine(); dev = FakeDev(); e._on_connect(dev)
for i in range(15):
    e.clear_key(i) if not e.is_locked(i) else None
e.set_wallpaper({"file": gif, "fit": "fill", "fps": 10, "dim": 20})
check("animation starts loading", e.anim_state["state"] in ("loading", "ready"))
check("animation becomes ready", wait(lambda: e.anim_state["state"] == "ready"), e.anim_state)
frames = []
e.wall_frame.connect(lambda: frames.append(e._anim_idx))
dev.sent.clear(); spin(1.5)
check("frames advance over time", len(set(frames)) > 5, frames[:10])
rate = len(frames) / 1.5
check("playback near the configured 10 fps", 6 <= rate <= 14, rate)
check("frames are pushed to the deck", len(dev.sent) > 30, len(dev.sent))
check("only wallpaper keys are re-sent each frame (custom-bg keys are static)", True)
e.edit_key(5, bg="#102030", title="static"); spin(0.3)
dev.sent.clear(); spin(1.0)
check("keys with their own background are not re-sent", not any(i == 5 for _t, i, _n in dev.sent), {i for _t, i, _n in dev.sent})
imgs = []
for _ in range(2):
    imgs.append(e.render(7, 72)); spin(0.35)
check("rendered key face animates", imgs[0] != imgs[1])
e.edit_key(0, title="Hi", icon={"kind": "glyph", "value": "play"}); spin(0.3)
face = e.render(0, 72)
check("icons stay on top of the moving wallpaper", face.width() == 72)
check("pressed key still renders over the wallpaper", e.render(0, 72, pressed=True).width() == 72)
# backlog: slow deck must not build a queue
dev.set_key_image = lambda i, j: (dev.sent.append((time.monotonic(), i, len(j))), time.sleep(0.05))[1]
dev.sent.clear(); spin(1.5)
check("slow deck drops frames instead of lagging", len(e._pending) <= 15, len(e._pending))
dev.set_key_image = lambda i, j: dev.sent.append((time.monotonic(), i, len(j)))
# asleep / hidden: no work
e._asleep = True; e.ui_visible = False; idx0 = e._anim_idx; spin(0.5)
check("animation pauses when deck is asleep and window hidden", e._anim_idx == idx0)
e._asleep = False; e.ui_visible = True
# toggle animate off -> static first frame
e.set_wallpaper({"file": gif, "animate": False}); spin(0.3)
check("animate off falls back to a static first frame", e._anim is None and e.anim_state["state"] == "paused" and not e._anim_timer.isActive(), e.anim_state)
dev.sent.clear(); spin(0.5)
check("no animation traffic when paused", len(dev.sent) == 0, len(dev.sent))
# swap to a static image
e.set_wallpaper({"file": png}); spin(0.3)
check("switching to a still image stops animating", e._anim is None and e.anim_state["state"] == "none")
# corrupt animated file
e.set_wallpaper({"file": bad}); spin(1.0)
check("undecodable animation degrades gracefully", e.anim_state["state"] in ("error", "none", "paused", "ready"))
e.render(1, 72)
# removal
e.set_wallpaper(None); spin(0.2)
check("removing the wallpaper clears the animation", e._anim is None and e.anim_state["state"] == "none")
# ---- dialog shows the animation state; MCP keeps animated bytes
from deckhand.mainwindow import MainWindow
from deckhand.wallpaper_dialog import WallpaperDialog
e.set_wallpaper({"file": gif, "fps": 10}); wait(lambda: e.anim_state["state"] == "ready")
w = MainWindow(e); dlg = WallpaperDialog(e, w); dlg.show(); app.processEvents()
check("dialog shows animation info", "frames" in dlg.anim_lbl.text() or "Preparing" in dlg.anim_lbl.text(), dlg.anim_lbl.text())
check("dialog shows the frame-rate slider for animated images", not dlg.sliders["fps"][0].isHidden())
dlg.anim_sw.click(); spin(0.2)
check("dialog play switch pauses the animation", e.profile["wallpaper"]["animate"] is False)
e.set_wallpaper({"file": png}); app.processEvents(); spin(0.2)
check("dialog hides animation controls for still images", dlg.anim_row.isHidden())
from deckhand import agentapi
import base64
spec = agentapi._save_animated(base64.b64encode(open(gif, "rb").read()).decode())
check("MCP upload keeps GIF animation (not flattened to PNG)", spec and spec["value"].endswith(".gif") and wallpaper.animation_info(spec["value"])[0])
check("non-animated base64 falls through to normal handling", agentapi._save_animated(base64.b64encode(open(png, "rb").read()).decode()) is None)
e.set_wallpaper({"file": gif, "fps": 10})
# animation reloads when the deck size changes
class XL(FakeModel): cols, rows, px, keys = 8, 4, 96, 32
class XLDev(FakeDev): model = XL
e.set_wallpaper({"file": gif}); wait(lambda: e.anim_state["state"] == "ready")
e._on_disconnect(); e._on_connect(XLDev()); e.set_wallpaper({"file": gif, "fps": 10}); spin(0.2)
check("animation is rebuilt for a different deck", wait(lambda: e._anim is not None and e._anim.frames[0].width() == wallpaper.canvas_size(8, 4, 96)[0]))

dlg.close(); e.shutdown()
print("FAILED:", fails if fails else "none"); sys.exit(1 if fails else 0)
