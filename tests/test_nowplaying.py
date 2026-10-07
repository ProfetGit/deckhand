"""Now Playing key: Spotify / YouTube Music art, player selection, rendering, hold-next, double-click open."""
import json, os, sys, tempfile, threading, time
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["HOME"] = tmp
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DECKHAND_SOCKET"] = os.path.join(tmp, "mcp.sock")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from http.server import BaseHTTPRequestHandler, HTTPServer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QImage, QMouseEvent, QColor
app = QApplication(sys.argv)
from deckhand import style, sysinfo, render, actions, model, icons
app.setStyleSheet(style.QSS)
sysinfo.ART_DIR = os.path.join(tmp, "art")
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

# ---- local "CDN"
red = QImage(300, 300, QImage.Format.Format_RGB32); red.fill(QColor("#ff0000")); red.save(tmp + "/red.png")
hits = {}
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        hits[self.path] = hits.get(self.path, 0) + 1
        if "missing" in self.path:
            self.send_response(404); self.end_headers(); return
        if "huge" in self.path:
            self.send_response(200); self.end_headers(); self.wfile.write(b"x" * (4 * 1024 * 1024)); return
        if "slow" in self.path: time.sleep(0.6)
        body = open(tmp + "/red.png", "rb").read()
        self.send_response(200); self.send_header("Content-Type", "image/png"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"

# ---- URL handling
n = sysinfo.normalize_art_url
check("YouTube Music thumbnail is upgraded to a large cover", n("https://lh3.googleusercontent.com/x=w60-h60-l90-rj").endswith("=w544-h544-l90-rj") and n("https://yt3.ggpht.com/y=s88-c").endswith("=w544-h544-l90-rj"))
check("already-large YouTube Music cover is left alone", n("https://lh3.googleusercontent.com/x=w800-h800-l90-rj").endswith("=w800-h800-l90-rj"))
check("YouTube video thumbnails use the sharper variant", n("https://i.ytimg.com/vi/ABCDEFGHIJK/default.jpg").endswith("/hqdefault.jpg") and n("https://i.ytimg.com/vi/ABCDEFGHIJK/mqdefault.webp").endswith("/hqdefault.webp"))
check("Spotify's 64px cover is upgraded to 640px", n("https://i.scdn.co/image/ab67616d00004851abc").endswith("ab67616d0000b273abc"))
check("Spotify 300px/640px covers are untouched", n("https://i.scdn.co/image/ab67616d00001e02abc").endswith("00001e02abc"))
check("unknown hosts and malformed URLs pass through", n("https://example.com/a.jpg") == "https://example.com/a.jpg" and n("http://[bad") == "http://[bad")
s = sysinfo.source_of
check("source detection", s("org.mpris.MediaPlayer2.spotify") == "spotify" and s("firefox", "https://open.spotify.com/track/1") == "spotify"
      and s("firefox", "https://music.youtube.com/watch?v=abc") == "youtube-music" and s("org.mpris.MediaPlayer2.youtube-music") == "youtube-music"
      and s("chromium", "https://www.youtube.com/watch?v=abc") == "youtube" and s("vlc") == "other")
check("video thumbnail from a watch URL", sysinfo.video_thumb("https://music.youtube.com/watch?v=EhQDjTztFU0&list=RD") == "https://i.ytimg.com/vi/EhQDjTztFU0/hqdefault.jpg"
      and sysinfo.video_thumb("https://youtu.be/EhQDjTztFU0") .endswith("EhQDjTztFU0/hqdefault.jpg") and sysinfo.video_thumb("https://example.com") == "" and sysinfo.video_thumb("") == "")

# ---- art fetching (web art must never block the poller)
t0 = time.monotonic(); r = sysinfo.resolve_art(base + "/slow/cover.png"); dt = time.monotonic() - t0
check("web art returns immediately and downloads in the background", r == "" and dt < 0.3, (r, dt))
for _ in range(40):
    r = sysinfo.resolve_art(base + "/slow/cover.png")
    if r: break
    time.sleep(0.05)
check("finished download is served from the cache", r and os.path.exists(r) and QImage(r).width() == 300, r)
before = hits.get("/slow/cover.png", 0); sysinfo.resolve_art(base + "/slow/cover.png")
check("cached art is not downloaded again", hits.get("/slow/cover.png", 0) == before)
check("blocking mode returns the file", sysinfo.resolve_art(base + "/direct.png", wait=True).endswith(".img"))
check("404 art gives nothing", sysinfo.resolve_art(base + "/missing.png", wait=True) == "")
c = hits.get("/missing.png", 0); sysinfo.resolve_art(base + "/missing.png", wait=True); sysinfo.resolve_art(base + "/missing.png", wait=True)
check("a failing URL is not hammered", hits.get("/missing.png", 0) == c)
check("oversized art is refused", sysinfo.resolve_art(base + "/huge.png", wait=True) == "")
import base64
png = base64.b64encode(open(tmp + "/red.png", "rb").read()).decode()
check("data: URLs work", sysinfo.resolve_art("data:image/png;base64," + png, wait=True).endswith(".img"))
check("non-http schemes are ignored", sysinfo.resolve_art("ftp://x/y.png") == "" and sysinfo.resolve_art("javascript:alert(1)") == "" and sysinfo.resolve_art("") == "" and sysinfo.resolve_art(None) == "")
open(tmp + "/a b.png", "wb").write(open(tmp + "/red.png", "rb").read())
check("file:// URLs are decoded", sysinfo.resolve_art("file://" + (tmp + "/a%20b.png")) == tmp + "/a b.png")
check("missing file:// art gives nothing", sysinfo.resolve_art("file:///no/such.png") == "")

# ---- player selection through a fake busctl
def mk(players):
    def fake(*args, timeout=1.5):
        args = list(args)
        if args[:1] == ["list"]:
            return "\n".join(f"{n} 123 x user x" for n in players) + "\n"
        js = "--json=short" in args
        a = [x for x in args if x != "--json=short"]
        if a[0] == "get-property":
            p = players[a[1]]
            if a[4] == "PlaybackStatus":
                return json.dumps({"type": "s", "data": p["status"]}) if js else p["status"]
            if a[4] == "Metadata":
                if p.get("bad"): return "not json"
                m = {k: {"type": "s", "data": v} for k, v in p["meta"].items()}
                return json.dumps({"type": "a{sv}", "data": m})
        return ""
    return fake
def np(players):
    sysinfo._np_cache = (0.0, None); sysinfo._busctl = mk(players); return sysinfo.mpris_nowplaying()
SP = "org.mpris.MediaPlayer2.spotify"; YT = "org.mpris.MediaPlayer2.firefox.instance_1"; CH = "org.mpris.MediaPlayer2.chromium.instance2"
spotify = {"status": "Playing", "meta": {"xesam:title": "Song A", "xesam:artist": ["Artist X", "Artist Y"], "xesam:album": "Album", "mpris:artUrl": base + "/img/spotify.png"}}
ytm = {"status": "Paused", "meta": {"xesam:title": "Track B", "xesam:artist": ["Someone"], "mpris:artUrl": "file://" + tmp + "/a%20b.png", "xesam:url": "https://music.youtube.com/watch?v=EhQDjTztFU0"}}
r = np({SP: spotify, YT: ytm})
check("a playing Spotify beats a paused YouTube Music tab", r["status"] == "Playing" and r["title"] == "Song A" and r["source"] == "spotify" and r["artist"] == "Artist X, Artist Y", r)
for _ in range(40):
    r = np({SP: spotify, YT: ytm})
    if r["art"]: break
    time.sleep(0.05)
check("Spotify cover arrives after its background download", r["art"].endswith(".img"), r)
r = np({YT: ytm})
check("YouTube Music (browser) is recognised and its local art used", r["source"] == "youtube-music" and r["art"] == tmp + "/a b.png" and r["status"] == "Paused", r)
seen = []; orig = sysinfo.resolve_art; sysinfo.resolve_art = lambda u, wait=False: seen.append(u) or ""
np({CH: {"status": "Playing", "meta": {"xesam:title": "No art here", "xesam:url": "https://music.youtube.com/watch?v=EhQDjTztFU0"}}})
check("YouTube Music without art falls back to the video thumbnail", seen and seen[-1] == "https://i.ytimg.com/vi/EhQDjTztFU0/hqdefault.jpg", seen)
seen.clear(); np({CH: {"status": "Playing", "meta": {"xesam:title": "Local file", "xesam:url": "file:///music/a.mp3"}}})
check("other players get no invented art", seen and seen[-1] == "", seen)
sysinfo.resolve_art = orig
check("no players -> nothing playing", np({})["status"] == "None")
check("a player with unreadable metadata is skipped", np({CH: {"status": "Playing", "meta": {}, "bad": True}})["status"] == "None")
check("stopped player with no title still reports", np({CH: {"status": "Stopped", "meta": {}}})["status"] in ("Stopped", "None"))
r = np({SP: {"status": "Paused", "meta": {"xesam:title": "P"}}, CH: {"status": "Playing", "meta": {"xesam:title": "Q"}}})
check("playing wins regardless of order", r["title"] == "Q")
r = np({SP: {"status": "Playing", "meta": {}}, CH: {"status": "Playing", "meta": {"xesam:title": "Has title"}}})
check("among equals a player with a title wins", r["title"] == "Has title")
sysinfo._np_cache = (0.0, None); sysinfo._busctl = orig_b = (lambda *a, **k: "")

# ---- rendering
art_file = tmp + "/cover.png"; im = QImage(400, 225, QImage.Format.Format_RGB32); im.fill(QColor("#00aa00")); im.save(art_file)
def card(**p):
    return {"action": {"type": "nowplaying", "params": {"show_art": True, "show_text": True, "hold_next": True, "_np": p}}}
playing = {"status": "Playing", "title": "A very long song title that cannot fit", "artist": "Some Artist", "art": art_file}
img = render.render_key(card(**playing), 72)
check("album art fills the key (centre-cropped)", img.pixelColor(2, 2).green() > 120 and img.pixelColor(2, 2).red() < 60 and img.pixelColor(69, 3).green() > 120)
check("title and artist are drawn over the art", render.render_key(card(**playing), 72) != render.render_key({**card(**playing), "action": {"type": "nowplaying", "params": {"show_text": False, "show_art": True, "_np": playing}}}, 72))
paused = render.render_key(card(**{**playing, "status": "Paused"}), 72)
check("paused art is dimmed", paused.pixelColor(2, 2).green() < img.pixelColor(2, 2).green())
noart = render.render_key(card(**{**playing, "art": ""}), 72)
check("no art gives a tasteful placeholder", noart != img and noart.pixelColor(36, 5).blue() > noart.pixelColor(36, 5).red())
check("art can be turned off", render.render_key({"action": {"type": "nowplaying", "params": {"show_art": False, "_np": playing}}}, 72) != img)
nothing = render.render_key(card(status="None", title="", artist="", art=""), 72)
check("nothing playing shows a quiet card", nothing.pixelColor(2, 2).green() < 60 and nothing != noart)
for odd in ({"title": "日本語のタイトル 🎵🎶 émoji", "artist": "Ärtïst"}, {"title": "", "artist": "Only artist"}, {"title": "x" * 500, "artist": "y" * 500}, {"title": "T", "artist": "", "art": "/not/a/file.png"}):
    render.render_key(card(**{"status": "Playing", "art": "", **odd}), 72)
check("odd titles (unicode, empty, huge, broken art path) never crash rendering", True)
check("renders at editor sizes too", render.render_key(card(**playing), 220).width() == 220)

# ---- engine behaviour
sysinfo.LIVE["nowplaying"] = lambda arg: playing_now          # the engine's own poller reads this
playing_now = {"status": "None", "title": "", "artist": "", "art": ""}
e = Engine(); w = MainWindow(e); w.resize(1200, 900); w.show(); app.processEvents()
for i in range(15):
    e.clear_key(i) if not e.is_locked(i) else None
e.assign_action(4, "nowplaying")
check("Now Playing key does not add a hold action of its own", not e.get_key(4).get("hold"))
check("the key is polled while visible", "nowplaying" in (e._update_live_wanted() or e._live_wanted))
playing_now = playing; spin(1.2)
f = e.render(4, 72)
check("a new track repaints the key", f.pixelColor(2, 2).green() > 100)
ran = []; orig_run = actions.run; actions.run = lambda a, eng: ran.append(a["type"])
e.settings["hold_ms"] = 300
e._on_key(4, True); spin(0.05); e._on_key(4, False); spin(0.1)
check("tap = play/pause", ran == ["nowplaying"], ran)
ran.clear(); e._on_key(4, True); spin(0.45); e._on_key(4, False); spin(0.05)
check("hold = next track (built in)", ran == ["next"], ran)
e.edit_params(4, hold_next=False); ran.clear(); e._on_key(4, True); spin(0.02)
check("with 'hold to skip' off the key reacts instantly again", ran == ["nowplaying"], ran); e._on_key(4, False)
e.edit_params(4, hold_next=True); e.set_hold(4, actions.default_action("mute")); ran.clear(); e._on_key(4, True); spin(0.45); e._on_key(4, False)
check("an explicit hold action overrides the built-in skip", ran == ["mute"], ran)
actions.run = orig_run
check("Now Playing is a widget in the sidebar", "nowplaying" in actions.CATEGORIES[[c for c, _ in actions.CATEGORIES].index("Widgets")][1])
check("media template includes Now Playing", any((k.get("action") or {}).get("type") == "nowplaying" for k in __import__("deckhand.templates", fromlist=["x"]).build_page("media", 5, 3)["keys"].values()))
from deckhand import agentapi
t = agentapi.Tools(e)
check("agents can place Now Playing", t.call("set_key", {"index": 5, "action": {"type": "nowplaying", "params": {"show_text": False}}})["updated"] == [5] and e.get_key(5)["action"]["params"]["show_text"] is False)
check("agents see it in the catalog", any(a["type"] == "nowplaying" for a in t.call("list_actions", {})))

# ---- double-click opens folders / goes back
e.goto_page(0); e.clear_key(6); e.assign_action(6, "folder"); fid = e.get_key(6)["action"]["params"]["folder"]
e.profile["folders"][fid]["keys"]["1"] = model.new_key(); e.profile["folders"][fid]["keys"]["1"]["action"] = actions.default_action("lock")
def dbl(i):
    r = w.deck.key_rect(i).center()
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonDblClick, QPointF(r), QPointF(r), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    w.deck.mouseDoubleClickEvent(ev); app.processEvents()
dbl(6)
check("double-clicking a folder key opens the folder", e.in_folder and e.loc["folders"] == [fid])
check("selection moves into the folder", w.deck.sel == 0)
check("the Back key is shown in the folder", e.get_key(0)["action"]["type"] == "back")
dbl(1); check("double-clicking an ordinary key does nothing special", e.in_folder)
dbl(0)
check("double-clicking Back returns to the page", not e.in_folder and e.loc["page"] == 0)
dbl(4); check("double-clicking a non-folder key on a page does nothing", not e.in_folder)
dbl(10); check("double-clicking an empty key is harmless", not e.in_folder)
w.deck.set_selected(6); from PyQt6.QtGui import QKeyEvent; from PyQt6.QtCore import QEvent
w.deck.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)); app.processEvents()
check("Enter on a selected folder key opens it too", e.in_folder)
e.go_back()
e.profile["folders"].pop(fid); dbl(6); check("a folder key pointing nowhere does not crash or navigate", not e.in_folder)
w.deck.set_selected(0); e.go_back(); dbl(0); check("Back key outside a folder is ignored", not e.in_folder)
srv.shutdown(); e.shutdown()
print("FAILED:", fails if fails else "none"); sys.exit(1 if fails else 0)
