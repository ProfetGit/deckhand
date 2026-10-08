"""Action registry (what the sidebar lists and the inspector edits) and the executors."""
import os
import shlex
import subprocess
import time

from . import keymap, sysinfo
from .icons import find_app

ACTIONS = {}
CATEGORIES = []


def category(name):
    CATEGORIES.append((name, []))


def reg(aid, name, glyph, desc="", defaults=None, fields=None, dynamic=False, multi=True, hidden=False, state=None):
    ACTIONS[aid] = dict(id=aid, name=name, glyph=glyph, desc=desc, defaults=defaults or {}, fields=fields or [],
                        dynamic=dynamic, multi=multi, state=state, category=CATEGORIES[-1][0] if CATEGORIES else "")
    if CATEGORIES and not hidden:
        CATEGORIES[-1][1].append(aid)


def F(key, label, typ, **kw):
    return dict(key=key, label=label, type=typ, **kw)


DATE_FORMATS = [("short", "Wed 8 Oct"), ("fi", "8.10."), ("iso", "2026-10-08"), ("dmy", "08/10/2026"), ("month", "8 October"), ("weekday", "Wednesday")]
DATE_STRFTIME = {"short": "%a %-d %b", "fi": "%-d.%-m.", "iso": "%Y-%m-%d", "dmy": "%d/%m/%Y", "month": "%-d %B", "weekday": "%A"}

category("System")
reg("hotkey", "Hotkey", "keyboard", "Send a keyboard shortcut.", {"hotkey": {}}, [F("hotkey", "Shortcut", "hotkey")])
reg("text", "Type Text", "text", "Insert a block of text into the focused app.", {"text": "", "enter": False, "delay": 0},
    [F("text", "Text", "multiline"), F("enter", "Press Enter afterwards", "bool"),
     F("delay", "Wait before typing (seconds)", "int", min=0, max=10, hint="Gives you time to let go of the key or switch window first.")])
reg("app", "Open App", "grid", "Launch an installed application.", {"app": ""}, [F("app", "Application", "app")])
reg("website", "Website", "globe", "Open a link in your browser.", {"url": "", "browser": ""},
    [F("url", "URL", "string", placeholder="https://"),
     F("browser", "Open with (optional)", "app", hint="Leave empty to use the default browser.")])
reg("file", "Open File or Folder", "folder", "Open a file or folder with its default app.", {"path": "", "with": ""},
    [F("path", "Path", "path"), F("with", "Open with (optional)", "app", hint="Leave empty to use the default app for this type.")])
reg("command", "Run Command", "terminal", "Run a shell command or script.", {"cmd": "", "terminal": False, "workdir": "", "notify": False},
    [F("cmd", "Command", "multiline", mono=True), F("workdir", "Working folder (optional)", "string", placeholder="~"),
     F("terminal", "Show in a terminal window", "bool"),
     F("notify", "Show a notice when it finishes", "bool", hint="Reports success, or the last error line.", when={"terminal": False})])
reg("lock", "Lock Screen", "lock", "Lock the session.")
reg("sleep", "Sleep", "moon", "Suspend the computer.")
reg("display", "Toggle Monitor", "monitor", "Turn a monitor output on or off. The icon shows when it is off.",
    {"device": "DP-1"}, [F("device", "Output", "string", placeholder="DP-1", hint="Output name from kscreen-doctor -o.")],
    state={"source": "display_off", "label": "off", "follows": "the monitor", "off": {"glyph": "monitor"},
           "on": {"glyph": "moon", "bg": "#3a1010", "icon_color": "#ff6b6b"}})
reg("screenshot", "Screenshot", "camera", "Capture the screen with Spectacle.", {"mode": "region", "clipboard": False, "delay": 0, "pointer": False},
    [F("mode", "Capture", "choice", options=[("region", "Rectangular region"), ("full", "All screens"), ("screen", "Current screen"), ("window", "Active window")]),
     F("delay", "Delay (seconds)", "int", min=0, max=30), F("pointer", "Include the mouse pointer", "bool"),
     F("clipboard", "Copy to clipboard only", "bool")])

reg("http", "HTTP Request", "link", "Send a web request (webhooks, smart home, APIs) from this computer.",
    {"method": "GET", "url": "", "headers": "", "body": "", "timeout": 10, "show_response": False},
    [F("method", "Method", "choice", options=[("GET", "GET"), ("POST", "POST"), ("PUT", "PUT"), ("PATCH", "PATCH"), ("DELETE", "DELETE")]),
     F("url", "URL", "string", placeholder="https://"),
     F("headers", "Headers (one per line, Name: value)", "multiline", mono=True),
     F("body", "Body (JSON or text)", "multiline", mono=True),
     F("timeout", "Timeout (seconds)", "int", min=1, max=60),
     F("show_response", "Show the response in a notice", "bool", hint="Displays the first line of what the server answers.")])

category("Widgets")
reg("clock", "Clock", "clock", "Live time and date on the key.",
    {"fmt": "24h", "date": True, "seconds": False, "ampm": True, "date_fmt": "short", "color": "", "date_color": "", "scale": 100},
    [F("fmt", "Format", "choice", options=[("24h", "24-hour"), ("12h", "12-hour")]),
     F("ampm", "Show AM/PM", "bool", when={"fmt": "12h"}),
     F("seconds", "Show seconds", "bool"), F("date", "Show date", "bool"),
     F("date_fmt", "Date format", "choice", options=DATE_FORMATS, when={"date": True}),
     F("color", "Time colour", "color", hint="Auto uses the key's text colour."),
     F("date_color", "Date colour", "color", when={"date": True}),
     F("scale", "Time size (%)", "int", min=50, max=140)], dynamic=True, multi=False)
reg("sysmon", "System Monitor", "cpu", "Live CPU, memory or GPU load.",
    {"metric": "both", "show_label": True, "show_value": True, "show_temp": True, "color_mode": "load", "bar_color": "",
     "warn": 60, "crit": 85, "label_color": "", "value_color": ""},
    [F("metric", "Show", "choice", options=[("both", "CPU + Memory"), ("cpu", "CPU"), ("ram", "Memory"), ("gpu", "GPU")]),
     F("show_label", "Show name (CPU / RAM / GPU)", "bool"), F("show_value", "Show percentage", "bool"),
     F("show_temp", "Show GPU temperature", "bool", when={"metric": "gpu"}),
     F("label_color", "Name colour", "color", when={"show_label": True}),
     F("value_color", "Percentage colour", "color", when={"show_value": True}),
     F("color_mode", "Bar colour", "choice", options=[("load", "By load (green, amber, red)"), ("fixed", "One fixed colour")]),
     F("bar_color", "Bar colour", "color", when={"color_mode": "fixed"}),
     F("warn", "Amber from (%)", "int", min=1, max=99, when={"color_mode": "load"}),
     F("crit", "Red from (%)", "int", min=1, max=100, when={"color_mode": "load"})], dynamic=True, multi=False)

reg("nowplaying", "Now Playing", "music", "Album art and track from your media player. Press to play/pause, hold for the next track.",
    {"show_art": True, "show_text": True, "hold_next": True, "show_artist": True, "dim_paused": True, "text_color": "", "artist_color": ""},
    [F("show_art", "Show album art", "bool"), F("show_text", "Show title and artist", "bool"),
     F("show_artist", "Show the artist line", "bool", when={"show_text": True}),
     F("text_color", "Title colour", "color", when={"show_text": True}),
     F("artist_color", "Artist colour", "color", when={"show_text": True}),
     F("dim_paused", "Dim the art while paused", "bool"),
     F("hold_next", "Hold to skip to the next track", "bool")],
    dynamic=True, multi=False)
reg("counter", "Counter", "plus", "Counts up (or down) every press. Hold to reset. The number is shown on the key.",
    {"step": 1, "value": 0, "label": "", "color": "", "label_color": "", "scale": 100, "negative_color": ""},
    [F("step", "Change per press", "int", min=-1000, max=1000), F("value", "Current value", "int", min=-1000000, max=1000000),
     F("label", "Label under the number", "string"),
     F("color", "Number colour", "color", hint="Auto uses the key's text colour."),
     F("negative_color", "Colour when below zero", "color"),
     F("label_color", "Label colour", "color"),
     F("scale", "Number size (%)", "int", min=50, max=140)], dynamic=True, multi=False)
reg("timer", "Timer", "clock", "Stopwatch or countdown. Press to start/pause, hold to reset. A countdown plays a sound when it finishes, then resets.",
    {"mode": "stopwatch", "minutes": 25, "seconds": 0, "sound": "default", "volume": 80, "show_caption": True,
     "color": "", "run_color": "", "paused_color": "", "done_color": "", "caption_color": "", "scale": 100},
    [F("mode", "Mode", "choice", options=[("stopwatch", "Stopwatch"), ("countdown", "Countdown")]),
     F("minutes", "Countdown minutes", "int", min=0, max=600, when={"mode": "countdown"}),
     F("seconds", "Countdown seconds", "int", min=0, max=59, when={"mode": "countdown"}),
     F("sound", "Sound when finished", "sound", when={"mode": "countdown"}),
     F("volume", "Sound volume (%)", "int", min=5, max=100, when={"mode": "countdown"}),
     F("show_caption", "Show the caption (Countdown, Running, Paused…)", "bool"),
     F("caption_color", "Caption colour", "color", when={"show_caption": True}),
     F("color", "Time colour (idle)", "color", hint="Auto uses the key's text colour."),
     F("run_color", "Time colour while running", "color"),
     F("paused_color", "Time colour while paused", "color"),
     F("done_color", "Colour when finished", "color", when={"mode": "countdown"}),
     F("scale", "Time size (%)", "int", min=50, max=140)], dynamic=True, multi=False)
reg("counter_reset", "Reset Counter", "refresh", "Set the counter back to zero.", multi=False, hidden=True)
reg("timer_reset", "Reset Timer", "refresh", "Stop and zero the timer.", multi=False, hidden=True)

category("Multimedia")
reg("playpause", "Play / Pause", "play-pause", "Toggle media playback. The icon shows whether something is playing.",
    state={"source": "playing", "label": "playing", "follows": "your media player", "off": {"glyph": "play"},
           "on": {"glyph": "pause", "icon_color": "#3ddc84"}})
reg("next", "Next Track", "next", "Skip to the next track.")
reg("prev", "Previous Track", "prev", "Go back to the previous track.")
reg("stop", "Stop", "stop", "Stop playback.")
reg("volup", "Volume Up", "volume-up", "Raise the system volume.", {"step": 0},
    [F("step", "Step (%)", "int", min=0, max=50, hint="0 uses the system's default step.")])
reg("voldown", "Volume Down", "volume-down", "Lower the system volume.", {"step": 0},
    [F("step", "Step (%)", "int", min=0, max=50, hint="0 uses the system's default step.")])
reg("mute", "Mute", "volume-mute", "Mute or unmute the speakers. The icon follows the real mute state.",
    {"device": ""}, [F("device", "Output device", "audio_out", hint="System default follows the output chosen in Plasma's sound settings.")],
    state={"source": "spk_muted", "label": "muted", "follows": "your speakers", "off": {"glyph": "volume-up"},
           "on": {"glyph": "volume-mute", "bg": "#3a1010", "icon_color": "#ff6b6b"}})
reg("micmute", "Mute Microphone", "mic-off", "Mute or unmute a microphone (the system default, or one you pick). The icon follows the real mute state.",
    {"device": ""}, [F("device", "Microphone", "audio_in", hint="System default follows the input chosen in Plasma's sound settings, even when you switch headsets.")],
    state={"source": "mic_muted", "label": "muted", "follows": "your microphone", "off": {"glyph": "mic"},
           "on": {"glyph": "mic-off", "bg": "#3a1010", "icon_color": "#ff6b6b"}})

category("Navigation")
reg("folder", "Folder", "folder", "Open a folder of more keys.", {"folder": ""}, multi=False)
reg("back", "Back", "arrow-left", "Return to the previous level.", multi=False, hidden=True)
reg("nextpage", "Next Page", "arrow-right", "Go to the next page.", multi=False)
reg("prevpage", "Previous Page", "arrow-left", "Go to the previous page.", multi=False)
reg("profile", "Switch Profile", "layers", "Jump to another profile.", {"profile": ""},
    [F("profile", "Profile", "profile")])
reg("brightness", "Brightness", "sun", "Change or set the deck brightness.", {"mode": "up", "value": 10},
    [F("mode", "Action", "choice", options=[("up", "Brighter"), ("down", "Dimmer"), ("set", "Set to value")]),
     F("value", "Amount (%)", "int", min=1, max=100)])

category("Multi Action")
reg("multi", "Multi Action", "zap", "Chain several actions with delays.", {"steps": []},
    [F("steps", "Steps", "steps")], multi=False)
reg("delay", "Delay", "clock", "Wait before the next step.", {"ms": 500},
    [F("ms", "Milliseconds", "int", min=0, max=60000)], hidden=True)


def live_source(action):
    """Name of the system state a key follows, or None."""
    meta = ACTIONS.get((action or {}).get("type"))
    if not meta or not meta.get("state"):
        return None
    dev = ((action or {}).get("params") or {}).get("device")
    return meta["state"]["source"] + (f":{dev}" if dev else "")


def default_action(aid):
    import copy
    return {"type": aid, "params": copy.deepcopy(ACTIONS[aid]["defaults"])}


def describe(action, engine=None):
    """One-line summary for the inspector header / tooltips."""
    if not action:
        return ""
    t = action["type"]
    p = action.get("params", {})
    if t == "hotkey":
        return keymap.hotkey_label(p.get("hotkey")) or "No shortcut set"
    if t == "app":
        a = find_app(p.get("app", ""))
        return a["name"] if a else "Choose an app"
    if t == "website":
        return p.get("url") or "No URL set"
    if t == "file":
        return p.get("path") or "No path set"
    if t == "command":
        return (p.get("cmd") or "").split("\n")[0] or "No command set"
    if t == "text":
        return (p.get("text") or "").split("\n")[0] or "No text set"
    if t == "multi":
        n = len(p.get("steps", []))
        return f"{n} step{'s' if n != 1 else ''}"
    return ACTIONS[t]["desc"] if t in ACTIONS else ""


def _spawn(args, **kw):
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, **kw)


def _spawn_watched(args, what, wait=2.0, cwd=None):
    """Start a program detached, but notice if it fails right away and say why (this runs on a worker
    thread, so waiting briefly is fine). Long-running programs are simply left running."""
    p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         start_new_session=True, cwd=cwd)
    try:
        code = p.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        try:
            p.stderr.close()
        except Exception:
            pass
        return
    if code != 0:
        err = (p.stderr.read() or b"").decode(errors="replace").strip().splitlines()
        tail = err[-1][:160] if err else f"exit code {code}"
        raise RuntimeError(f"{what} failed: {tail}")


def _need_uinput():
    if not keymap.keyboard.available():
        raise RuntimeError("Cannot send keys: no write access to /dev/uinput. Open Preferences for the one-line fix.")


def x_hotkey(p, e):
    _need_uinput()
    if not p.get("hotkey"):
        raise RuntimeError("Hotkey has no shortcut set")
    keymap.keyboard.hotkey(p["hotkey"])


def x_text(p, e):
    _need_uinput()
    text = p.get("text", "")
    if not text:
        return
    time.sleep(max(0, min(10, _int(p.get("delay"), 0))))
    old = None
    try:
        r = subprocess.run(["wl-paste", "-n", "-t", "text"], capture_output=True, timeout=1)
        if r.returncode == 0:
            old = r.stdout
    except Exception:
        pass
    subprocess.run(["wl-copy", "--", text], timeout=2)
    time.sleep(0.08)
    keymap.keyboard.tap([keymap.KEY_V], ["ctrl"])
    if p.get("enter"):
        time.sleep(0.05)
        keymap.keyboard.tap([28])
    if old is not None:
        time.sleep(0.4)
        subprocess.run(["wl-copy", "--"], input=old, timeout=2)


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _open_with(app_id, target, what):
    """Open a path/URL with a chosen app, or with the system default when none is chosen."""
    a = find_app(app_id) if app_id else None
    if app_id and not a:
        raise RuntimeError("The chosen app is not installed - pick another one or clear it")
    _spawn_watched(["gio", "launch", a["path"], target] if a else ["xdg-open", target], what)


def x_app(p, e):
    a = find_app(p.get("app", ""))
    if not a:
        raise RuntimeError("App not found - pick another one")
    _spawn_watched(["gio", "launch", a["path"]], f"Launching {a['name']}")


def x_website(p, e):
    url = (p.get("url") or "").strip()
    if not url:
        raise RuntimeError("No URL set")
    if "://" not in url and not url.startswith("mailto:"):
        url = "https://" + url
    _open_with(p.get("browser", ""), url, "Opening the link")


def x_file(p, e):
    path = os.path.expanduser(p.get("path", "").strip())
    if not path:
        raise RuntimeError("No path set")
    if not os.path.exists(path):
        raise RuntimeError(f"{path} does not exist any more")
    _open_with(p.get("with", ""), path, "Opening the file")


def _tail(text):
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return lines[-1][:160] if lines else ""


def _watch_command(proc, cmd):
    """Report how a command ended (own thread: commands may run for minutes)."""
    from . import errors
    try:
        err = proc.communicate(timeout=3600)[1]
    except Exception:
        return
    name = (cmd.strip().splitlines() or ["command"])[0][:40]
    if proc.returncode == 0:
        errors.report(f"Finished: {name}", "ok", once_key=f"cmd-{name}", cooldown=0.5)
    else:
        errors.report(f"Failed ({proc.returncode}): {name}" + (f" - {_tail(err.decode("utf-8", "replace"))}" if err else ""),
                      "warn", once_key=f"cmd-{name}", cooldown=0.5)


def x_command(p, e):
    cmd = p.get("cmd", "").strip()
    if not cmd:
        raise RuntimeError("No command set")
    cwd = os.path.expanduser((p.get("workdir") or "").strip()) or None
    if cwd and not os.path.isdir(cwd):
        raise RuntimeError(f"Working folder {cwd} does not exist")
    if p.get("terminal"):
        _spawn(["konsole", "--hold"] + (["--workdir", cwd] if cwd else []) + ["-e", "sh", "-c", cmd])
    elif p.get("notify"):
        proc = subprocess.Popen(["sh", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                start_new_session=True, cwd=cwd)
        import threading
        threading.Thread(target=_watch_command, args=(proc, cmd), daemon=True).start()
    else:
        _spawn_watched(["sh", "-c", cmd], "The command", wait=1.5, cwd=cwd)


def x_screenshot(p, e):
    mode = p.get("mode", "region")
    flag = {"region": "-r", "full": "-f", "screen": "-m", "window": "-a"}.get(mode, "-r")
    args = ["spectacle", flag]
    if p.get("clipboard"):
        args += ["-c", "-b"]
    if p.get("pointer"):
        args.append("-p")
    delay = max(0, min(30, _int(p.get("delay"), 0)))
    if delay:
        args += ["-d", str(delay * 1000)]
    _spawn(args)


def x_http(p, e):
    import urllib.error
    import urllib.request
    url = (p.get("url") or "").strip()
    if not url:
        raise RuntimeError("No URL set")
    if "://" not in url:
        url = "https://" + url
    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError("Only http:// and https:// URLs are allowed")
    headers = {}
    for line in (p.get("headers") or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip():
                headers[k.strip()] = v.strip()
    body = (p.get("body") or "").encode("utf-8") if p.get("method", "GET") != "GET" and p.get("body") else None
    if body and not any(h.lower() == "content-type" for h in headers):
        headers["Content-Type"] = "application/json" if body.lstrip()[:1] in (b"{", b"[") else "text/plain; charset=utf-8"
    headers.setdefault("User-Agent", "Deckhand")
    req = urllib.request.Request(url, data=body, headers=headers, method=p.get("method", "GET"))
    try:
        with urllib.request.urlopen(req, timeout=max(1, min(60, int(p.get("timeout", 10))))) as r:
            body = r.read(65536)
            code = r.status
    except urllib.error.HTTPError as ex:
        raise RuntimeError(f"The server answered {ex.code} {ex.reason}")
    except urllib.error.URLError as ex:
        raise RuntimeError(f"Could not reach {url}: {ex.reason}")
    from . import errors
    line = _tail(body.decode("utf-8", "replace")) if p.get("show_response") else ""
    errors.report(f"Request sent: {code}" + (f" - {line}" if line else ""), "ok", once_key=f"http-{url}", cooldown=1.0)


def x_key(code):
    def run(p, e):
        _need_uinput()
        keymap.keyboard.tap([code])
    return run


def x_volume(sign, code):
    def run(p, e):
        step = _int(p.get("step"), 0)
        if step > 0:
            r = subprocess.run(["wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", f"{step}%{sign}"], capture_output=True, timeout=3)
            if r.returncode == 0:
                return
        _need_uinput()
        keymap.keyboard.tap([code])
    return run


def x_micmute(p, e):
    sysinfo.toggle_mute("source", p.get("device", ""))


def x_mute(p, e):
    if p.get("device"):
        sysinfo.toggle_mute("sink", p["device"])
    else:
        _need_uinput()
        keymap.keyboard.tap([keymap.KEY_MUTE])


def x_display(p, e):
    out = (p.get("device") or "").strip()
    if not out:
        raise RuntimeError("No monitor output set")
    sysinfo.toggle_display(out)


def x_nav(name):
    def run(p, e):
        e.request.emit(name, p)
    return run


def x_multi(p, e, depth=0):
    if depth > 3:
        raise RuntimeError("Multi action is nested too deeply")
    steps = p.get("steps", [])
    for step in steps[:100]:
        if not e.alive:
            return
        if step.get("type") == "delay":
            time.sleep(min(60000, max(0, step.get("params", {}).get("ms", 0))) / 1000)
        elif step.get("type") == "multi":
            x_multi(step.get("params", {}), e, depth + 1)
        else:
            run(step, e)


EXEC = {
    "hotkey": x_hotkey, "text": x_text, "app": x_app, "website": x_website, "file": x_file, "command": x_command,
    "lock": lambda p, e: _spawn_watched(["loginctl", "lock-session"], "Locking the screen", wait=3),
    "sleep": lambda p, e: _spawn_watched(["systemctl", "suspend"], "Suspending", wait=3),
    "screenshot": x_screenshot,
    "playpause": x_key(keymap.KEY_PLAYPAUSE), "next": x_key(keymap.KEY_NEXT), "prev": x_key(keymap.KEY_PREV),
    "stop": x_key(keymap.KEY_STOP), "volup": x_volume("+", keymap.KEY_VOLUP), "voldown": x_volume("-", keymap.KEY_VOLDOWN),
    "mute": x_mute, "micmute": x_micmute, "nowplaying": x_key(keymap.KEY_PLAYPAUSE), "display": x_display,
    "folder": x_nav("folder"), "back": x_nav("back"), "nextpage": x_nav("nextpage"), "prevpage": x_nav("prevpage"),
    "profile": x_nav("profile"), "brightness": x_nav("brightness"),
    "multi": x_multi, "http": x_http,
}


def run(action, engine):
    fn = EXEC.get(action.get("type"))
    if fn:
        fn(action.get("params", {}), engine)
