"""Cheap system metrics for live keys."""
import re
import json
import os
import subprocess
import time

_cpu_prev = None
_cpu_val = 0.0
_gpu = (None, None, None)
_gpu_t = 0.0


def cpu_percent():
    global _cpu_prev, _cpu_val
    try:
        with open("/proc/stat") as f:
            parts = [int(x) for x in f.readline().split()[1:]]
    except OSError:
        return 0.0
    idle = parts[3] + parts[4]
    total = sum(parts)
    if _cpu_prev is not None:
        di, dt = idle - _cpu_prev[0], total - _cpu_prev[1]
        if dt > 0:
            _cpu_val = max(0.0, min(100.0, 100.0 * (1 - di / dt)))
    _cpu_prev = (idle, total)
    return _cpu_val


def ram_percent():
    try:
        m = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                m[k] = int(v.split()[0])
        return 100.0 * (1 - m["MemAvailable"] / m["MemTotal"])
    except Exception:
        return 0.0


def gpu_percent():
    """(util %, mem %, temp C) via nvidia-smi, cached for 2s."""
    global _gpu, _gpu_t
    now = time.monotonic()
    if now - _gpu_t < 2.0:
        return _gpu
    _gpu_t = now
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=1.5).stdout.strip()
        u, mu, mt, t = [float(x) for x in out.split(",")]
        _gpu = (u, 100.0 * mu / mt, t)
    except Exception:
        _gpu = (None, None, None)
    return _gpu


def _pactl(*args, timeout=1.5):
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def _mute(kind, dev):
    target = dev or ("@DEFAULT_SOURCE@" if kind == "source" else "@DEFAULT_SINK@")
    return "yes" in _pactl(f"get-{kind}-mute", target)


def audio_devices(kind):
    """[{name, description, default}] for kind 'source' (microphones) or 'sink' (outputs)."""
    import json
    try:
        data = json.loads(_pactl("--format=json", "list", f"{kind}s", timeout=3) or "[]")
    except ValueError:
        data = []
    default = _pactl(f"get-default-{kind}").strip()
    out = []
    for d in data:
        if kind == "source" and (d.get("name", "").endswith(".monitor") or d.get("monitor_of_sink") is not None):
            continue
        out.append({"name": d["name"], "description": d.get("description") or d["name"], "default": d["name"] == default})
    return out


def toggle_mute(kind, dev):
    target = dev or ("@DEFAULT_SOURCE@" if kind == "source" else "@DEFAULT_SINK@")
    subprocess.run(["pactl", f"set-{kind}-mute", target, "toggle"], capture_output=True, timeout=3)


def mpris_playing():
    """True if any MPRIS media player (browser, Spotify, mpv...) is currently playing."""
    try:
        out = subprocess.run(["busctl", "--user", "list", "--no-legend"], capture_output=True, text=True, timeout=1.5).stdout
        for line in out.splitlines():
            name = line.split()[0] if line.split() else ""
            if not name.startswith("org.mpris.MediaPlayer2."):
                continue
            r = subprocess.run(["busctl", "--user", "get-property", name, "/org/mpris/MediaPlayer2",
                                "org.mpris.MediaPlayer2.Player", "PlaybackStatus"], capture_output=True, text=True, timeout=1.0).stdout
            if "Playing" in r:
                return True
    except Exception:
        pass
    return False


def display_off(output):
    """True if the named monitor output (e.g. DP-1) is currently disabled."""
    try:
        out = subprocess.run(["kscreen-doctor", "-o"], capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return False
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)
    cur = None
    for line in out.splitlines():
        w = line.split()
        if len(w) >= 3 and w[0] == "Output:":
            cur = w[2]
        elif cur == output and w and w[0] in ("enabled", "disabled"):
            return w[0] == "disabled"
    return False


def toggle_display(output):
    verb = "enable" if display_off(output) else "disable"
    subprocess.run(["kscreen-doctor", f"output.{output}.{verb}"], capture_output=True, timeout=5)


_np_cache = (0.0, None)
_art_fail = {}
ART_DIR = os.path.expanduser("~/.cache/deckhand/art")
MAX_ART_BYTES = 3 * 1024 * 1024


def _busctl(*args, timeout=1.5):
    try:
        return subprocess.run(["busctl", "--user", *args], capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def _prop(name, prop, json_out=False):
    out = _busctl(*(["--json=short"] if json_out else []), "get-property", name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", prop)
    if not json_out:
        return out
    try:
        return json.loads(out)["data"]
    except (ValueError, KeyError, TypeError):
        return None


def _prune_art(keep=60):
    try:
        files = sorted((os.path.join(ART_DIR, f) for f in os.listdir(ART_DIR)), key=os.path.getmtime)
        for f in files[:-keep]:
            os.remove(f)                      # only our own cache files
    except OSError:
        pass


_art_pending = set()


def normalize_art_url(url):
    """Ask streaming services for a bigger cover than the tiny thumbnail some players advertise."""
    import re
    import urllib.parse
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    host = (u.hostname or "").lower()
    if host.endswith(("googleusercontent.com", "ggpht.com")):
        # YouTube Music cover URLs end in a size spec such as =w60-h60-l90-rj or =s88-c
        m = re.search(r"=(?:w(\d+)(?:-h\d+)?|s(\d+))((?:-[a-z0-9]+)*)$", url)
        if m and int(m.group(1) or m.group(2)) < 400:
            return url[:m.start()] + "=w544-h544-l90-rj"
        return url
    if host == "i.ytimg.com":
        return re.sub(r"/(default|mqdefault|sddefault)\.(jpg|webp)", r"/hqdefault.\2", url)
    if host.endswith("scdn.co") or host.endswith("spotify.com"):
        return url.replace("ab67616d00004851", "ab67616d0000b273")          # Spotify's 64px cover -> 640px
    return url


def source_of(player, page_url=""):
    p, u = (player or "").lower(), (page_url or "").lower()
    if "spotify" in p or "open.spotify.com" in u:
        return "spotify"
    if "music.youtube.com" in u or "youtube-music" in p or "youtubemusic" in p or "ytmdesktop" in p or "youtube_music" in p:
        return "youtube-music"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return "other"


def video_thumb(page_url):
    """YouTube / YouTube Music watch URL -> its thumbnail (used only when the player gave no art)."""
    import re
    m = re.search(r"(?:[?&]v=|youtu\.be/)([A-Za-z0-9_-]{11})", page_url or "")
    return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg" if m else ""


def _fetch_art(url, dest):
    import base64
    import hashlib
    import urllib.request
    key = hashlib.sha1(url.encode()).hexdigest()
    try:
        os.makedirs(ART_DIR, exist_ok=True)
        if url.startswith("data:image"):
            data = base64.b64decode(url.split(",", 1)[1])
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Deckhand"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = r.read(MAX_ART_BYTES + 1)
        if not data or len(data) > MAX_ART_BYTES:
            raise ValueError("art too large or empty")
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        _prune_art()
        return dest
    except Exception:
        _art_fail[key] = time.monotonic() + 60       # do not hammer a failing URL
        return ""
    finally:
        _art_pending.discard(key)


def resolve_art(url, wait=False):
    """A local image path for an MPRIS art URL, or '' if not (yet) available.

    file:// is immediate. Web art (Spotify, YouTube Music, ...) is downloaded on a background thread and cached,
    so a slow network never stalls the poller; the next poll returns the finished file."""
    import hashlib
    import threading
    import urllib.parse
    if not url or not isinstance(url, str):
        return ""
    if url.startswith("file://"):
        path = urllib.parse.unquote(url[7:])
        try:
            return path if os.path.isfile(path) and os.path.getsize(path) < 12 * 1024 * 1024 else ""
        except OSError:
            return ""
    if not url.startswith("data:image"):
        if not url.lower().startswith(("http://", "https://")):
            return ""
        url = normalize_art_url(url)
    key = hashlib.sha1(url.encode()).hexdigest()
    dest = os.path.join(ART_DIR, key + ".img")
    if os.path.exists(dest):
        return dest
    if time.monotonic() < _art_fail.get(key, 0):
        return ""
    if wait:
        return _fetch_art(url, dest)
    if key not in _art_pending:
        _art_pending.add(key)
        threading.Thread(target=_fetch_art, args=(url, dest), daemon=True).start()
    return ""


def mpris_nowplaying():
    """What is playing right now: {status, title, artist, album, art, player}. Playing beats Paused beats Stopped."""
    global _np_cache
    now = time.monotonic()
    if _np_cache[1] is not None and now - _np_cache[0] < 0.6:
        return _np_cache[1]
    best, rank = None, -1
    for line in _busctl("list", "--no-legend").splitlines():
        name = line.split()[0] if line.split() else ""
        if not name.startswith("org.mpris.MediaPlayer2."):
            continue
        st = _prop(name, "PlaybackStatus", True)
        meta = _prop(name, "Metadata", True)
        if not isinstance(meta, dict):
            continue
        title = (meta.get("xesam:title") or {}).get("data", "") if isinstance(meta.get("xesam:title"), dict) else ""
        r = {"Playing": 3, "Paused": 2, "Stopped": 1}.get(st, 0) + (0.5 if title else 0)
        if r > rank:
            rank, best = r, (name, st or "Stopped", meta)
    if not best:
        res = {"status": "None", "title": "", "artist": "", "album": "", "art": "", "player": "", "source": "other"}
    else:
        name, st, meta = best

        def val(k):
            v = meta.get(k)
            v = v.get("data") if isinstance(v, dict) else None
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            return str(v) if v is not None else ""
        player = name.rsplit(".", 1)[-1].split(".")[0]
        page = val("xesam:url")
        source = source_of(name, page)
        art_url = val("mpris:artUrl")
        if not art_url and source in ("youtube-music", "youtube"):
            art_url = video_thumb(page)                 # no cover from the player: use the video thumbnail
        res = {"status": st, "title": val("xesam:title"), "artist": val("xesam:artist"), "album": val("xesam:album"),
               "art": resolve_art(art_url), "player": player, "source": source}
    _np_cache = (now, res)
    return res


LIVE = {
    "display_off": display_off,
    "mic_muted": lambda arg: _mute("source", arg),
    "spk_muted": lambda arg: _mute("sink", arg),
    "playing": lambda arg: mpris_playing(),
    "nowplaying": lambda arg: mpris_nowplaying(),
}


def read_live(key):
    name, _, arg = key.partition(":")
    return LIVE[name](arg)
