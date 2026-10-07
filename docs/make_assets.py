"""Regenerates the README banner and screenshots from a throwaway demo profile (no real data used).

    python3 docs/make_assets.py
"""
import math, os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ.update(LC_ALL="C.UTF-8", LANG="C.UTF-8", XDG_CONFIG_HOME=tmp, HOME=tmp, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR="1.5", DECKHAND_SOCKET=os.path.join(tmp, "s.sock"),
                  DECKHAND_DBUS_SERVICE=f"org.deckhand.assets{os.getpid()}")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QRadialGradient
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from deckhand import actions, model, render, style, sysinfo, wallpaper
app.setStyle("Fusion"); app.setStyleSheet(style.QSS)
f = app.font(); f.setPixelSize(13); app.setFont(f)
import deckhand.statusui as su, deckhand.mainwindow as mw
su.MIN_SHOWN_S = 0.0; su.HARD_TIMEOUT_S = mw.HARD_TIMEOUT_S = 0.2
from deckhand.engine import Engine
from deckhand.mainwindow import MainWindow

from PIL import Image


def to_pil(q):
    q = (q.toImage() if hasattr(q, "toImage") else q).convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer("RGBA", (q.width(), q.height()), bytes(q.constBits().asarray(q.sizeInBytes())), "raw", "RGBA", q.bytesPerLine(), 1)


def save_webp(q, name, quality=90):
    to_pil(q).convert("RGB").save(os.path.join(OUT, name), "WEBP", quality=quality, method=6)


def spin(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.005)

# ---- artwork made in code
def sunset(path, w=1600, h=900):
    img = QImage(w, h, QImage.Format.Format_RGB32); p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, 0, h); g.setColorAt(0, QColor("#150c3a")); g.setColorAt(.5, QColor("#7b2d8e")); g.setColorAt(.75, QColor("#ff5f6d")); g.setColorAt(1, QColor("#ffc371"))
    p.fillRect(img.rect(), g)
    r = QRadialGradient(QPointF(w * .68, h * .66), 220); r.setColorAt(0, QColor("#fff6c8")); r.setColorAt(1, QColor(255, 200, 120, 0)); p.setBrush(r); p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(w * .68, h * .66), 220, 220); p.setBrush(QColor("#fff3b0")); p.drawEllipse(QPointF(w * .68, h * .66), 95, 95)
    for i, (col, off) in enumerate((("#3a1450", 0), ("#240d3a", 90), ("#12081f", 170))):
        p.setBrush(QColor(col)); path = []
        for x in range(0, w + 40, 40): path.append(QPointF(x, h * (.78 + i * .07) + math.sin(x / 190 + i * 2) * (38 - i * 7) - off * .15))
        from PyQt6.QtGui import QPolygonF
        poly = QPolygonF(path + [QPointF(w, h), QPointF(0, h)]); p.drawPolygon(poly)
    p.end()
    return img
wp_path = os.path.join(tmp, "sunset.png"); sunset(wp_path).save(wp_path)
cover = QImage(640, 640, QImage.Format.Format_RGB32); p = QPainter(cover); p.setRenderHint(QPainter.RenderHint.Antialiasing)
g = QLinearGradient(0, 0, 640, 640); g.setColorAt(0, QColor("#00c6ff")); g.setColorAt(1, QColor("#7b2ff7")); p.fillRect(cover.rect(), g)
p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, 40))
for r_ in (260, 190, 120): p.drawEllipse(QPointF(320, 320), r_, r_)
p.setBrush(QColor("#0b1020")); p.drawEllipse(QPointF(320, 320), 52, 52); p.end()
cover_path = os.path.join(tmp, "cover.png"); cover.save(cover_path)

# ---- demo profile (every live source is faked so nothing from the real machine appears)
DEMO_NP = {"status": "Playing", "title": "Neon Skyline", "artist": "Aurora Drive", "art": cover_path, "album": "", "player": "demo", "source": "other"}
sysinfo.LIVE["nowplaying"] = lambda arg: DEMO_NP
sysinfo.LIVE["mic_muted"] = lambda arg: False
sysinfo.LIVE["spk_muted"] = lambda arg: False
sysinfo.LIVE["playing"] = lambda arg: True
sysinfo.gpu_percent = lambda: (34.0, 40.0, 52.0)
sysinfo.cpu_percent = lambda: 23.0
sysinfo.ram_percent = lambda: 48.0
e = Engine(); e.windows.install_script = False
class FakeModel: cols, rows, px, keys, name = 5, 3, 72, 15, "Stream Deck"
class FakeDev:
    model = FakeModel; serial = "DEMO"; alive = True
    def firmware(self): return ""
    def set_brightness(self, v): pass
    def set_key_image(self, i, j): pass
    def reset(self): pass
    def close(self): pass
e._on_status({"state": "ok", "title": "Stream Deck", "detail": "", "devices": [], "culprits": [], "scans": 0}); e._on_connect(FakeDev())
def key(aid, title="", icon=None, bg=None, hold=None, **params):
    k = model.new_key(); k["action"] = actions.default_action(aid); k["action"]["params"].update(params)
    if title: k["title"] = title
    if icon: k["icon"] = {"kind": "glyph", "value": icon}
    if bg: k["bg"] = bg
    return k
def hotkey(mods, code, label, title, icon):
    return key("hotkey", title, icon, hotkey={"mods": mods, "code": code, "label": label})
layout = [key("prev"), key("playpause"), key("next"), key("nowplaying"), key("clock", bg="#0d1424", date=True),
          key("micmute"), key("mute"), key("timer", bg="#0d1424", mode="countdown", minutes=25), key("counter", bg="#0d1424", label="Streak"),
          key("sysmon", bg="#0d1424", metric="gpu"),
          key("website", "GitHub", "globe", url="https://github.com"), key("screenshot", "Capture"), hotkey(["ctrl"], 46, "C", "Copy", "copy"),
          key("folder", "Tools", "briefcase"), key("lock", "Lock")]
pg = e.profile["pages"][0]; pg["keys"].clear()
for i, k in enumerate(layout): pg["keys"][str(i)] = k
fid = model.new_id(); e.profile["folders"][fid] = {"id": fid, "name": "Tools", "keys": {}}; pg["keys"]["13"]["action"]["params"] = {"folder": fid}
e.profile["wallpaper"] = wallpaper.normalize({"file": wp_path, "dim": 30, "fy": 55})
e.live["nowplaying"] = DEMO_NP; e.live["playing"] = True
e._timers[e._tkey(7)] = {"acc": 205.0, "t0": None}
e.profile["pages"][0]["keys"]["8"]["action"]["params"]["value"] = 12
e.push_all()
w = MainWindow(e); w.resize(1280, 860); w.show(); spin(1.0); w._select(3); spin(0.8)
save_webp(w.grab(), "editor.webp")

from deckhand.wallpaper_dialog import WallpaperDialog
from deckhand.templates_dialog import TemplatesDialog
from deckhand.agents_dialog import AgentsDialog
from deckhand.autoswitch_dialog import AutoSwitchDialog
from deckhand.palette import CommandPalette
from deckhand.mcp_server import McpServer
d = WallpaperDialog(e, w); d.resize(700, 700); d.show(); spin(0.4); save_webp(d.grab(), "wallpaper.webp"); d.close()
d = TemplatesDialog(e, w); d.resize(800, 640); d.show(); spin(0.3); save_webp(d.grab(), "templates.webp"); d.close()
srv = McpServer(e)
os.makedirs(os.path.join(tmp, ".gemini"), exist_ok=True); os.makedirs(os.path.join(tmp, ".codex"), exist_ok=True); os.makedirs(os.path.join(tmp, ".cursor"), exist_ok=True)
d = AgentsDialog(e, srv, w); d.resize(680, 800); d.show(); spin(0.3); save_webp(d.grab(), "agents.webp"); d.close()
games = model.new_profile("Gaming", 5, 3); work = model.new_profile("Work", 5, 3); e.store.profiles.extend([games, work])
e.set_auto_switch({"enabled": False, "default": "", "rules": [{"kind": "app", "pattern": "steam", "profile": games["id"]}, {"kind": "app", "pattern": "code", "profile": work["id"]},
                   {"kind": "title", "pattern": "re:YouTube|Twitch", "profile": games["id"]}]})
d = AutoSwitchDialog(e, w); d.resize(760, 560); d.show(); spin(0.3); save_webp(d.grab(), "autoswitch.webp"); d.close()
items = [("Add action: Hotkey", "to the selected key", "keyboard", None), ("Add a page from a template…", "", "grid", None), ("Switch to profile: Gaming", "", "layers", None),
         ("Deck wallpaper…", "", "image", None), ("Auto-switch by window…", "", "layers", None), ("Connect AI agents…", "", "bot", None), ("Undo", "Ctrl+Z", "undo", None)]
pal = CommandPalette(items, w); pal.show(); pal.edit.setText("a"); spin(0.3); save_webp(pal.grab(), "palette.webp"); pal.close()

# ---- animated banner (WebP): every frame is drawn with the real key renderer
from PyQt6.QtGui import QPainterPath, QPen, QPolygonF
W, H, FPS, N = 1600, 480, 60, 240          # drawn in a 1600x480 space, written at 0.8x
SCALE = 0.8
RADIUS = 34
px, gap, cols, rows = 96, 24, 5, 3
bf = QFont(app.font()); bf.setPixelSize(112); bf.setBold(True); bf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -2)
sf = QFont(app.font()); sf.setPixelSize(34)
cf = QFont(app.font()); cf.setPixelSize(24)

def frame(i):
    t = i / N
    ph = 2 * math.pi * t
    img = QImage(int(W * SCALE), int(H * SCALE), QImage.Format.Format_ARGB32_Premultiplied); img.fill(Qt.GlobalColor.transparent); p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.scale(SCALE, SCALE)
    rr = QPainterPath(); rr.addRoundedRect(QRectF(0, 0, W, H), RADIUS, RADIUS); p.setClipPath(rr)      # rounded corners, transparent outside
    bg = QLinearGradient(0, 0, W, H); bg.setColorAt(0, QColor("#0b0d16")); bg.setColorAt(.55, QColor("#161a2e")); bg.setColorAt(1, QColor("#2a1646")); p.fillRect(QRectF(0, 0, W, H), bg)
    for cx, cy, r_, col, ph0 in ((1320, 140, 420, QColor(124, 77, 255, 70), 0), (1500, 420, 360, QColor(255, 95, 109, 55), 2.1), (200, 460, 340, QColor(61, 139, 253, 50), 4.2)):
        ox, oy = 40 * math.sin(ph + ph0), 30 * math.cos(ph + ph0)
        rg = QRadialGradient(QPointF(cx + ox, cy + oy), r_); rg.setColorAt(0, col); rg.setColorAt(1, QColor(0, 0, 0, 0)); p.fillRect(QRectF(0, 0, W, H), rg)
    # live state that changes during the loop
    e.live["playing"] = not (0.50 <= t < 0.72)          # play/pause icon flips
    e.live["mic_muted"] = 0.22 <= t < 0.42              # mic key flashes its muted look
    DEMO_NP["status"] = "Playing" if e.live["playing"] else "Paused"; e.live["nowplaying"] = dict(DEMO_NP)
    sysinfo.gpu_percent = lambda: (46 + 30 * math.sin(ph), 40.0, 52.0)
    e._timers[e._tkey(7)] = {"acc": 205.0 + 12 * t, "t0": None}
    e.profile["pages"][0]["keys"]["8"]["action"]["params"]["value"] = 12 + (1 if t >= 0.35 else 0) + (1 if t >= 0.8 else 0)
    wp = {"file": wp_path, "dim": 25, "fy": 55, "fx": 50 + 42 * math.sin(ph), "zoom": 150}
    e.profile["wallpaper"] = wallpaper.normalize(wp)
    p.save(); p.translate(930 + 6 * math.sin(ph * 2), 92 + 9 * math.sin(ph)); p.rotate(-4 + 1.6 * math.sin(ph + 1.0))
    p.setPen(QColor("#3a3f55")); p.setBrush(QColor("#10121c")); p.drawRoundedRect(QRectF(-34, -34, cols * px + (cols - 1) * gap + 68, rows * px + (rows - 1) * gap + 68), 34, 34)
    for k in range(cols * rows):
        x, y = (k % cols) * (px + gap), (k // cols) * (px + gap)
        pp = QPainterPath(); pp.addRoundedRect(QRectF(x, y, px, px), 16, 16)
        p.save(); p.setClipPath(pp); p.drawImage(QPointF(x, y), e.render(k, px)); p.restore()
    p.restore()
    p.setFont(bf); p.setPen(QColor("#ffffff")); p.drawText(QRectF(84, 112, 900, 140), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "Deckhand")
    p.setFont(sf); p.setPen(QColor("#c9cfe8")); p.drawText(QRectF(88, 258, 880, 50), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), "The modern Stream Deck studio for Linux")
    p.setFont(cf); x = 90
    for n, (label, col) in enumerate((("Wayland native", "#3ddc84"), ("Animated wallpapers", "#ff8a8a"), ("AI agents via MCP", "#8fb4ff"))):
        wd = p.fontMetrics().horizontalAdvance(label) + 40
        glow = 0.5 + 0.5 * math.sin(ph + n * 2.0)
        c2 = QColor(col); c2.setAlpha(int(34 + 30 * glow)); p.setPen(Qt.PenStyle.NoPen); p.setBrush(c2); p.drawRoundedRect(QRectF(x, 334, wd, 48), 24, 24)
        p.setPen(QColor(col)); p.drawText(QRectF(x, 334, wd, 48), int(Qt.AlignmentFlag.AlignCenter), label); x += wd + 14
    # continuous motion that is only visible at a high frame rate: drifting particles and a light sweep
    p.setPen(Qt.PenStyle.NoPen)
    for n in range(36):
        r_ = (n * 7919 % 1000) / 1000.0
        px0, sp, sz = (n * 104729 % 1600), 1 + (n % 3), 2 + (n % 4) * 1.6
        yy = H - (((t * sp) + r_) % 1.0) * (H + 20)
        xx = px0 + 18 * math.sin(ph * sp + n)
        a = int(70 * math.sin(math.pi * min(1.0, max(0.0, (H - yy) / H))))
        p.setBrush(QColor(190, 175, 255, a)); p.drawEllipse(QPointF(xx, yy), sz, sz)
    sx = -400 + (W + 800) * t
    band = QPainterPath(); band.moveTo(sx, 0); band.lineTo(sx + 140, 0); band.lineTo(sx + 40, H); band.lineTo(sx - 100, H); band.closeSubpath()
    sg = QLinearGradient(sx - 100, 0, sx + 140, 0); sg.setColorAt(0, QColor(255, 255, 255, 0)); sg.setColorAt(.5, QColor(255, 255, 255, 34)); sg.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillPath(band, sg)
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 46), 3)); p.setBrush(Qt.BrushStyle.NoBrush)      # border so the rounded corners show on dark pages too
    p.drawRoundedRect(QRectF(1.5, 1.5, W - 3, H - 3), RADIUS - 1.5, RADIUS - 1.5)
    p.end()
    return img

frames = [to_pil(frame(i)) for i in range(N)]
# WebP frame delays are whole milliseconds: 17 ms is as close to 60 fps (16.67 ms) as the format allows
frames[0].save(os.path.join(OUT, "banner.webp"), "WEBP", save_all=True, append_images=frames[1:], duration=17, loop=0,
               quality=54, alpha_quality=85, method=4)
frames[0].save(os.path.join(OUT, "banner-still.webp"), "WEBP", quality=92, alpha_quality=100, method=6)
# key close-ups strip
e.profile["wallpaper"] = wallpaper.normalize({"file": wp_path, "dim": 25, "fy": 55}); e.live.update(playing=True, mic_muted=False)
strip = QImage(5 * 164 + 20, 184, QImage.Format.Format_RGB32); strip.fill(QColor("#10121c")); q = QPainter(strip)
for n, idx in enumerate((3, 7, 8, 9, 5)): q.drawImage(10 + n * 164, 10, e.render(idx, 154))
q.end(); save_webp(strip, "widgets.webp")
print("assets written to", OUT, sorted(os.listdir(OUT)))
e.shutdown()
