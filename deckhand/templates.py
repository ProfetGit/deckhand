"""Ready-made pages. Each template is a list of key definitions placed from the top-left, so it fits
any deck size (extra keys are simply dropped on small decks)."""
from . import actions, model


def _k(aid, title="", icon=None, bg=None, icon_color=None, hold=None, **params):
    k = model.new_key()
    k["action"] = actions.default_action(aid)
    k["action"]["params"].update(params)
    if title:
        k["title"] = title
    if icon:
        k["icon"] = {"kind": "glyph", "value": icon}
    if bg:
        k["bg"] = bg
    if icon_color:
        k["icon_color"] = icon_color
    if hold:
        k["hold"] = actions.default_action(hold)
    return k


def _hk(mods, code, label, title, icon):
    return _k("hotkey", title, icon, hotkey={"mods": mods, "code": code, "label": label})


TEMPLATES = {
    "media": {
        "name": "Media & Volume", "desc": "Playback, volume and mute controls.", "glyph": "music",
        "keys": lambda: [_k("prev"), _k("playpause"), _k("next"), _k("voldown"), _k("volup"),
                         _k("mute"), _k("micmute"), _k("nowplaying"), _k("clock", bg="#101820", date=True),
                         _k("screenshot", "Shot")],
    },
    "streaming": {
        "name": "Streaming starter", "desc": "Mic and speaker mute, a live timer, a scene counter and quick captures.", "glyph": "video",
        "keys": lambda: [_k("micmute", "Mic"), _k("mute", "Sound"), _k("timer", bg="#101820", mode="stopwatch"),
                         _k("counter", bg="#101820", label="Scene"), _k("screenshot", "Capture"),
                         _k("clock", bg="#101820"), _k("sysmon", bg="#101820", metric="gpu"), _k("sysmon", bg="#101820", metric="cpu"),
                         _k("playpause"), _k("volup"), _k("voldown"), _k("lock", "Away")],
    },
    "productivity": {
        "name": "Productivity", "desc": "A 25-minute focus timer, clipboard shortcuts and screenshots.", "glyph": "briefcase",
        "keys": lambda: [_k("timer", bg="#101820", mode="countdown", minutes=25),
                         _hk(["ctrl"], 46, "C", "Copy", "copy"), _hk(["ctrl"], 47, "V", "Paste", "download"),
                         _hk(["ctrl"], 44, "Z", "Undo", "undo"), _hk(["ctrl", "shift"], 44, "Z", "Redo", "redo"),
                         _k("screenshot", "Region"), _k("clock", bg="#101820"), _k("counter", bg="#101820", label="Tasks"),
                         _k("lock"), _k("sleep"), _hk(["ctrl"], 31, "S", "Save", "check"), _hk(["ctrl"], 33, "F", "Find", "search")],
    },
    "developer": {
        "name": "Developer", "desc": "Terminal, browser, system gauges and common editor shortcuts.", "glyph": "code",
        "keys": lambda: [_k("command", "Terminal", "terminal", cmd="konsole"), _k("website", "GitHub", "globe", url="https://github.com"),
                         _hk(["ctrl", "shift"], 25, "P", "Palette", "search"), _hk(["ctrl"], 50, "M", "Mark", "check"),
                         _k("sysmon", bg="#101820", metric="cpu"), _k("sysmon", bg="#101820", metric="ram"),
                         _k("sysmon", bg="#101820", metric="gpu"), _k("clock", bg="#101820"),
                         _hk(["ctrl"], 31, "S", "Save", "download"), _hk(["ctrl"], 46, "C", "Copy", "copy"),
                         _hk(["ctrl"], 47, "V", "Paste", "copy"), _k("screenshot", "Shot")],
    },
    "monitor": {
        "name": "System monitor", "desc": "CPU, memory and GPU gauges with a clock and timer.", "glyph": "cpu",
        "keys": lambda: [_k("sysmon", bg="#101820", metric="cpu"), _k("sysmon", bg="#101820", metric="ram"),
                         _k("sysmon", bg="#101820", metric="gpu"), _k("sysmon", bg="#101820", metric="both"),
                         _k("clock", bg="#101820", seconds=True), _k("timer", bg="#101820")],
    },
}


def names():
    return [(tid, t["name"], t["desc"], t["glyph"]) for tid, t in TEMPLATES.items()]


def build_page(tid, cols, rows):
    """A new page dict for template tid sized to the deck (keys beyond the deck are dropped)."""
    t = TEMPLATES[tid]
    page = model.new_page(t["name"])
    for i, key in enumerate(t["keys"]()[:cols * rows]):
        page["keys"][str(i)] = key
    return page
