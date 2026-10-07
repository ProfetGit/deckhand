"""Profile data model and JSON persistence. Plain dicts so undo/redo and import/export stay trivial."""
import copy
import json
import os
import re
import shutil
import time
import uuid

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "deckhand")
PROFILES_FILE = os.path.join(CONFIG_DIR, "profiles.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
ICON_DIR = os.path.join(CONFIG_DIR, "icons")

DEFAULT_SETTINGS = {
    "brightness": 70,
    "sleep_minutes": 0,
    "start_minimized": False,
    "close_to_tray": True,
    "pressed_effect": True,
    "animations": True,
    "hold_ms": 500,
    "night": {"enabled": False, "start": "22:00", "end": "07:00", "brightness": 20},
    "auto_switch": {"enabled": False, "default": "", "rules": []},
    "agent_enabled": True,
    "agent_access": "edit",
}

BACK_KEY = {
    "action": {"type": "back", "params": {}},
    "title": "Back",
    "icon": None,
}


def new_id():
    return uuid.uuid4().hex[:8]


def new_key():
    return {
        "action": None,
        "title": "",
        "show_title": True,
        "title_pos": "bottom",
        "title_size": 14,
        "title_color": "#ffffff",
        "bold": True,
        "icon": None,
        "icon_color": "#ffffff",
        "bg": "#000000",
    }


def key_is_empty(key):
    if not key:
        return True
    return (not key.get("action") and not key.get("hold") and not key.get("title") and not key.get("icon")
            and key.get("bg", "#000000") == "#000000")


def new_page(name="Page"):
    return {"id": new_id(), "name": name, "keys": {}}


def new_profile(name, cols, rows):
    return {"id": new_id(), "name": name, "cols": cols, "rows": rows, "pages": [new_page("Page 1")], "folders": {}}


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_or_quarantine(path):
    """(data, problem). A file we cannot parse is copied aside (never silently overwritten)."""
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, ValueError) as e:
        dest = f"{path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.copyfile(path, dest)
            kept = f"A copy was kept at {dest}."
        except OSError:
            kept = "It could not be backed up."
        return None, f"{os.path.basename(path)} could not be read ({e.__class__.__name__}). {kept}"


_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_POS = ("top", "middle", "bottom")
MAX_KEYS = 256


def _s(v, default="", limit=200):
    return v[:limit] if isinstance(v, str) else default


def _i(v, lo, hi, default):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _clean_icon(ic):
    if isinstance(ic, dict) and ic.get("kind") in ("glyph", "theme", "file") and isinstance(ic.get("value"), str) and ic["value"]:
        out = {"kind": ic["kind"], "value": ic["value"][:500]}
        if ic.get("auto"):
            out["auto"] = True
        return out
    return None


def _clean_action(a, depth=0):
    if not isinstance(a, dict) or not isinstance(a.get("type"), str):
        return None
    params = a.get("params")
    params = dict(params) if isinstance(params, dict) else {}
    if a["type"] == "multi":
        steps = params.get("steps")
        params["steps"] = [s for s in (_clean_action(x, depth + 1) for x in steps[:100]) if s] if isinstance(steps, list) and depth < 4 else []
    return {"type": a["type"][:40], "params": params}


def clean_key(k):
    if not isinstance(k, dict):
        return None
    base = new_key()
    out = dict(base)
    out["action"] = _clean_action(k.get("action"))
    out["hold"] = _clean_action(k.get("hold"))
    if out["hold"] and out["hold"]["type"] in ("folder", "multi_nested"):
        out["hold"] = None
    out["title"] = _s(k.get("title"), "", 120)
    out["show_title"] = bool(k.get("show_title", True))
    out["title_pos"] = k.get("title_pos") if k.get("title_pos") in _POS else "bottom"
    out["title_size"] = _i(k.get("title_size"), 8, 40, 14)
    out["bold"] = bool(k.get("bold", True))
    for f, d in (("title_color", "#ffffff"), ("icon_color", "#ffffff"), ("bg", "#000000")):
        v = k.get(f)
        out[f] = v if isinstance(v, str) and _COLOR.match(v) else d
    out["icon"] = _clean_icon(k.get("icon"))
    alt = k.get("alt")
    if isinstance(alt, dict):
        a2 = {}
        if _clean_icon(alt.get("icon")):
            a2["icon"] = _clean_icon(alt["icon"])
        if isinstance(alt.get("title"), str):
            a2["title"] = alt["title"][:120]
        for f in ("title_color", "icon_color", "bg"):
            if isinstance(alt.get(f), str) and _COLOR.match(alt[f]):
                a2[f] = alt[f]
        if a2:
            out["alt"] = a2
    return out


def _clean_keys(keys, n):
    out = {}
    if not isinstance(keys, dict):
        return out
    for i, k in list(keys.items())[:MAX_KEYS]:
        try:
            idx = int(i)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < n:
            ck = clean_key(k)
            if ck and not key_is_empty(ck):
                out[str(idx)] = ck
    return out


def sanitize_profile(p, seen_ids=None):
    """Return a structurally valid copy of a profile dict (or None if it is hopeless)."""
    if not isinstance(p, dict):
        return None
    cols, rows = _i(p.get("cols"), 0, 16, 0), _i(p.get("rows"), 0, 16, 0)
    if not (1 <= cols <= 12 and 1 <= rows <= 8):
        return None
    n = cols * rows
    pid = _s(p.get("id"), "", 40) or new_id()
    if seen_ids is not None:
        while pid in seen_ids:
            pid = new_id()
        seen_ids.add(pid)
    out = {"id": pid, "name": _s(p.get("name"), "Profile", 80).strip() or "Profile", "cols": cols, "rows": rows, "pages": [], "folders": {}}
    pages = p.get("pages")
    for pg in (pages[:100] if isinstance(pages, list) else []):
        if isinstance(pg, dict):
            out["pages"].append({"id": _s(pg.get("id"), "", 40) or new_id(), "name": _s(pg.get("name"), "Page", 80) or "Page",
                                 "keys": _clean_keys(pg.get("keys"), n)})
    if not out["pages"]:
        out["pages"].append(new_page("Page 1"))
    folders = p.get("folders")
    for fid, f in (list(folders.items())[:500] if isinstance(folders, dict) else []):
        if isinstance(fid, str) and isinstance(f, dict):
            out["folders"][fid] = {"id": fid, "name": _s(f.get("name"), "Folder", 80) or "Folder", "keys": _clean_keys(f.get("keys"), n)}
    from . import wallpaper
    wp = wallpaper.normalize(p.get("wallpaper"))
    if wp:
        out["wallpaper"] = wp
    # heal folder keys that point at a folder that no longer exists
    holders = [pg["keys"] for pg in out["pages"]] + [f["keys"] for f in out["folders"].values()]
    for keys in holders:
        for k in keys.values():
            a = k.get("action")
            if a and a["type"] == "folder":
                fid = a["params"].get("folder")
                if not isinstance(fid, str) or fid not in out["folders"]:
                    fid = fid if isinstance(fid, str) and fid else new_id()
                    out["folders"][fid] = {"id": fid, "name": k.get("title") or "Folder", "keys": {}}
                    a["params"] = {"folder": fid}
    return out


def _hhmm(v, default):
    if isinstance(v, str) and re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", v):
        h, mi = v.split(":")
        return f"{int(h):02d}:{mi}"
    return default


def clean_settings(s):
    out = dict(DEFAULT_SETTINGS)
    if isinstance(s, dict):
        out.update({k: v for k, v in s.items() if k in DEFAULT_SETTINGS or k in ("last_deck", "preferred_serial")})
    from . import autoswitch
    out["auto_switch"] = autoswitch.clean_config(out.get("auto_switch"))
    out["brightness"] = _i(out["brightness"], 5, 100, 70)
    out["sleep_minutes"] = _i(out["sleep_minutes"], 0, 1440, 0)
    out["hold_ms"] = _i(out.get("hold_ms"), 250, 2000, 500)
    nt = out.get("night") if isinstance(out.get("night"), dict) else {}
    out["night"] = {"enabled": bool(nt.get("enabled", False)), "start": _hhmm(nt.get("start"), "22:00"), "end": _hhmm(nt.get("end"), "07:00"),
                    "brightness": _i(nt.get("brightness"), 5, 100, 20)}
    for k in ("start_minimized", "close_to_tray", "pressed_effect", "animations", "agent_enabled"):
        out[k] = bool(out[k])
    if out.get("agent_access") not in ("read", "edit", "full"):
        out["agent_access"] = "edit"
    ld = out.get("last_deck")
    out["last_deck"] = ld if isinstance(ld, dict) and _i(ld.get("cols"), 0, 16, 0) and _i(ld.get("rows"), 0, 16, 0) else None
    return out


class Settings(dict):
    def __init__(self):
        raw, self.problem = load_or_quarantine(SETTINGS_FILE)
        super().__init__(clean_settings(raw))

    def save(self):
        write_json(SETTINGS_FILE, dict(self))


def container(profile, loc):
    fids = loc.get("folders") or []
    if fids and fids[-1] in profile["folders"]:
        return profile["folders"][fids[-1]]
    pages = profile["pages"]
    return pages[max(0, min(loc.get("page", 0), len(pages) - 1))]


def in_folder(profile, loc):
    fids = loc.get("folders") or []
    return bool(fids) and fids[-1] in profile["folders"]


def folder_ids(key):
    a = (key or {}).get("action") or {}
    return [a["params"]["folder"]] if a.get("type") == "folder" and a.get("params", {}).get("folder") else []


def reachable_folders(profile):
    seen = set()
    stack = []
    for pg in profile["pages"]:
        for k in pg["keys"].values():
            stack += folder_ids(k)
    while stack:
        fid = stack.pop()
        if fid in seen or fid not in profile["folders"]:
            continue
        seen.add(fid)
        for k in profile["folders"][fid]["keys"].values():
            stack += folder_ids(k)
    return seen


def gc_folders(profile):
    live = reachable_folders(profile)
    for fid in list(profile["folders"]):
        if fid not in live:
            del profile["folders"][fid]


def clone_key(profile, key, _path=()):
    """Deep copy a key; a folder key gets its own copy of the folder tree (cycles are cut)."""
    k = copy.deepcopy(key)
    for fid in folder_ids(k):
        src = profile["folders"].get(fid)
        if not src:
            continue
        if fid in _path or len(_path) > 12:
            k["action"] = None
            continue
        nid = new_id()
        sub = copy.deepcopy(src)
        sub["id"] = nid
        sub["keys"] = {i: clone_key(profile, kk, _path + (fid,)) for i, kk in src["keys"].items()}
        profile["folders"][nid] = sub
        k["action"]["params"]["folder"] = nid
    return k


def copy_page(src_profile, page, dst_profile):
    """Deep copy of a page (with new ids and its folder trees) for use in dst_profile (may be the same profile)."""
    tmp = {"folders": dict(src_profile["folders"])}
    new = {"id": new_id(), "name": page["name"], "keys": {}}
    for i, k in page["keys"].items():
        new["keys"][i] = clone_key(tmp, k)
    for fid, f in tmp["folders"].items():
        if fid not in src_profile["folders"]:
            dst_profile["folders"][fid] = f
    return new


def clone_profile(profile, name):
    p = copy.deepcopy(profile)
    p["id"] = new_id()
    p["name"] = name
    return p


def seed_profile(cols, rows):
    p = new_profile("Default", cols, rows)
    keys = p["pages"][0]["keys"]

    def act(t, **params):
        return {"type": t, "params": params}

    def put(i, action, **extra):
        k = new_key()
        k["action"] = action
        k.update(extra)
        keys[str(i)] = k

    n = cols * rows
    if cols >= 5 and rows >= 3:
        put(0, act("prev"))
        put(1, act("playpause"))
        put(2, act("next"))
        put(3, act("voldown"))
        put(4, act("volup"))
        put(5, act("mute"))
        put(6, act("micmute"))
        put(7, act("clock", fmt="24h", date=True, seconds=False), bg="#101820")
        put(8, act("sysmon", metric="both"), bg="#101820")
        put(9, act("lock"))
        fid = new_id()
        p["folders"][fid] = {"id": fid, "name": "Tools", "keys": {}}
        put(10, act("folder", folder=fid), title="Tools", icon={"kind": "glyph", "value": "briefcase"})
        sub = p["folders"][fid]["keys"]
        k = new_key()
        k["action"] = act("screenshot", mode="region")
        sub["1"] = k
        k2 = new_key()
        k2["action"] = act("website", url="https://claude.ai")
        sub["2"] = k2
    elif n >= 3:
        put(0, act("prev"))
        put(1, act("playpause"))
        put(2, act("next"))
    return p


class Store:
    VERSION = 1

    def __init__(self):
        raw, self.problem = load_or_quarantine(PROFILES_FILE)
        self.notes = []
        self.data = {"version": self.VERSION, "current": None, "profiles": []}
        if isinstance(raw, dict):
            if isinstance(raw.get("version"), int) and raw["version"] > self.VERSION:
                try:
                    shutil.copyfile(PROFILES_FILE, f"{PROFILES_FILE}.v{raw['version']}.bak")
                except OSError:
                    pass
                self.notes.append("profiles.json was written by a newer Deckhand; a backup copy was kept.")
            seen, dropped = set(), 0
            profs = raw.get("profiles")
            for p in (profs if isinstance(profs, list) else []):
                cp = sanitize_profile(p, seen)
                if cp:
                    self.data["profiles"].append(cp)
                else:
                    dropped += 1
            if dropped:
                self.notes.append(f"{dropped} unreadable profile(s) were skipped.")
            if isinstance(raw.get("current"), str):
                self.data["current"] = raw["current"]
        elif raw is not None and self.problem is None:
            self.problem = "profiles.json had an unexpected format and was ignored."

    def save(self):
        write_json(PROFILES_FILE, self.data)

    @property
    def profiles(self):
        return self.data["profiles"]

    def get(self, pid):
        for p in self.profiles:
            if p["id"] == pid:
                return p
        return None

    def for_size(self, cols, rows):
        return [p for p in self.profiles if p["cols"] == cols and p["rows"] == rows]

    def ensure(self, cols, rows):
        if not self.for_size(cols, rows):
            self.profiles.append(seed_profile(cols, rows) if not self.profiles else new_profile("Default", cols, rows))
        cur = self.get(self.data.get("current"))
        if cur is None or (cur["cols"], cur["rows"]) != (cols, rows):
            self.data["current"] = self.for_size(cols, rows)[0]["id"]
        return self.get(self.data["current"])
