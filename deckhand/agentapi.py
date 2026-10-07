"""Agent-facing API: validation, views and the tool set exposed over MCP.

Everything here runs on the Qt main thread against the live Engine, so agent edits are
undoable (Ctrl+Z), update the editor and the deck instantly, and never race the UI.
"""
import base64
import copy
import difflib
import json
import os

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QIcon, QImage, QPainter

from . import actions, autoswitch, icons, keymap, model, render, sysinfo, templates, trouble, wallpaper
from .iconpicker import import_image

VERSION = "1.0.0"
LEVELS = {"read": 0, "edit": 1, "full": 2}
LEVEL_NAMES = {"read": "Read-only", "edit": "Edit layout", "full": "Full control"}


class ToolError(Exception):
    pass


class Content(list):
    """Marker: a ready-made list of MCP content blocks."""


# ---- hotkeys ----------------------------------------------------------------------------
_MOD_SYN = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt", "option": "alt", "altgr": "alt",
            "meta": "meta", "super": "meta", "win": "meta", "windows": "meta", "cmd": "meta", "command": "meta"}
_KEY_SYN = {"esc": 1, "escape": 1, "enter": 28, "return": 28, "space": 57, "spacebar": 57, "tab": 15, "backspace": 14,
            "delete": 111, "del": 111, "insert": 110, "ins": 110, "home": 102, "end": 107, "pageup": 104, "pgup": 104,
            "pagedown": 109, "pgdn": 109, "up": 103, "down": 108, "left": 105, "right": 106, "minus": 12, "dash": 12,
            "equals": 13, "comma": 51, "period": 52, "dot": 52, "slash": 53, "backslash": 43, "semicolon": 39,
            "quote": 40, "apostrophe": 40, "grave": 41, "backtick": 41, "lbracket": 26, "rbracket": 27,
            "printscreen": 99, "prtsc": 99, "playpause": 164, "nexttrack": 163, "prevtrack": 165, "volumeup": 115,
            "volumedown": 114, "volumemute": 113, "capslock": 58, "menu": 127}
_KEY_BY_NAME = {v.lower().replace(" ", ""): k for k, v in keymap.LABELS.items()}
_KEY_BY_NAME.update(_KEY_SYN)


def parse_hotkey(text):
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+")]
    if len(parts) >= 2 and parts[-1] == "" and parts[-2] == "":
        parts = parts[:-2] + ["="]
    parts = [p for p in parts if p]
    if not parts:
        raise ToolError("hotkey is empty; use e.g. 'ctrl+shift+m'")
    mods, key = [], None
    for p in parts:
        if p in _MOD_SYN:
            mods.append(_MOD_SYN[p])
        elif p in _KEY_BY_NAME:
            if key is not None:
                raise ToolError(f"hotkey '{text}' has more than one non-modifier key")
            key = p
        else:
            names = difflib.get_close_matches(p, list(_KEY_BY_NAME), 4)
            raise ToolError(f"unknown key '{p}' in hotkey '{text}'" + (f" (did you mean {', '.join(names)}?)" if names else ""))
    if key is None:
        raise ToolError(f"hotkey '{text}' needs a non-modifier key, e.g. 'ctrl+c'")
    code = _KEY_BY_NAME[key]
    return {"mods": [m for m in keymap.MOD_ORDER if m in mods], "code": code, "label": keymap.LABELS.get(code, key)}


def format_hotkey(hk):
    if not hk or not hk.get("code"):
        return ""
    lab = (hk.get("label") or keymap.LABELS.get(hk["code"], str(hk["code"]))).lower().replace(" ", "")
    return "+".join(list(hk.get("mods", [])) + [lab])


# ---- action catalog / validation -----------------------------------------------------------
_TYPE_DOC = {
    "string": "string", "multiline": "string", "path": "string (absolute path or ~/...)", "bool": "boolean",
    "int": "integer", "choice": "string (one of options)", "hotkey": "string like 'ctrl+shift+m', 'f13', 'super+d'",
    "app": "string: .desktop id from list_apps (app name also accepted)", "profile": "string: profile id or name",
    "steps": "array of {type, params}; also {type:'delay', params:{ms}}",
    "audio_in": "string: '' = follow the system default microphone, or a device name/description from list_audio_devices",
    "audio_out": "string: '' = follow the system default output, or a device name/description from list_audio_devices",
}


def catalog(category=None):
    out = []
    for aid, a in actions.ACTIONS.items():
        if aid == "delay":
            continue
        if category and a["category"].lower() != category.lower():
            continue
        params = {}
        for f in a["fields"]:
            d = {"type": _TYPE_DOC.get(f["type"], f["type"]), "label": f["label"]}
            if f["type"] == "choice":
                d["options"] = [v for v, _l in f["options"]]
            if f["type"] == "int":
                d["min"], d["max"] = f.get("min", 0), f.get("max", 100)
            if a["defaults"].get(f["key"]) is not None:
                d["default"] = a["defaults"][f["key"]]
            params[f["key"]] = d
        if aid == "folder":
            params = {"name": {"type": "string", "label": "Folder name (used when the folder is created)"}}
        out.append({"type": aid, "name": a["name"], "category": a["category"], "description": a["desc"], "params": params,
                    "live_widget": a["dynamic"], "usable_in_multi_action": a["multi"],
                    **({"follows_system_state": a["state"]["follows"] + " " + a["state"]["label"]} if a.get("state") else {})})
    if not category or category.lower() == "multi action":
        out.append({"type": "delay", "name": "Delay", "category": "Multi Action",
                    "description": "Wait before the next step (only inside a multi action's steps).",
                    "params": {"ms": {"type": "integer", "min": 0, "max": 60000, "default": 500}},
                    "live_widget": False, "usable_in_multi_action": True})
    return out


def _resolve_app(v):
    v = str(v).strip()
    apps = icons.installed_apps()
    for a in apps:
        if a["id"] == v or a["id"] == v + ".desktop":
            return a["id"]
    hits = [a for a in apps if a["name"].lower() == v.lower()]
    if len(hits) == 1:
        return hits[0]["id"]
    near = [a["id"] for a in apps if v.lower() in a["name"].lower() or v.lower() in a["id"].lower()][:6]
    raise ToolError(f"app '{v}' not found" + (f"; similar: {', '.join(near)}" if near else "; use list_apps"))


def _resolve_profile(engine, v):
    for p in engine.store.profiles:
        if p["id"] == v:
            return p
    hits = [p for p in engine.store.profiles if p["name"].lower() == str(v).lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ToolError(f"profile name '{v}' is ambiguous; use an id from list_profiles")
    raise ToolError(f"profile '{v}' not found; use list_profiles")


def _coerce(engine, f, v, warnings):
    t, key = f["type"], f["key"]
    if t in ("string", "multiline", "path"):
        if not isinstance(v, str):
            raise ToolError(f"param '{key}' must be a string")
        return v
    if t == "bool":
        if isinstance(v, str) and v.lower() in ("true", "false"):
            return v.lower() == "true"
        if not isinstance(v, bool):
            raise ToolError(f"param '{key}' must be a boolean")
        return v
    if t == "int":
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ToolError(f"param '{key}' must be an integer")
        lo, hi = f.get("min", 0), f.get("max", 100)
        if not lo <= n <= hi:
            raise ToolError(f"param '{key}' must be between {lo} and {hi}")
        return n
    if t == "choice":
        opts = [o for o, _l in f["options"]]
        for o, label in f["options"]:
            if str(v).lower() in (o.lower(), label.lower()):
                return o
        raise ToolError(f"param '{key}' must be one of {opts}")
    if t == "hotkey":
        if isinstance(v, dict):
            if not v:
                return {}
            if not isinstance(v.get("code"), int):
                raise ToolError("hotkey object needs an integer evdev 'code'; prefer a string like 'ctrl+m'")
            return {"mods": [m for m in keymap.MOD_ORDER if m in v.get("mods", [])], "code": v["code"], "label": v.get("label", "")}
        if v in ("", None):
            return {}
        return parse_hotkey(str(v))
    if t == "app":
        return _resolve_app(v) if v else ""
    if t == "profile":
        return _resolve_profile(engine, v)["id"] if v else ""
    if t in ("audio_in", "audio_out"):
        if v in ("", None, "default"):
            return ""
        devs = sysinfo.audio_devices("source" if t == "audio_in" else "sink")
        for d in devs:
            if v == d["name"]:
                return d["name"]
        hits = [d for d in devs if str(v).lower() in d["description"].lower()]
        if len(hits) == 1:
            return hits[0]["name"]
        raise ToolError(f"audio device '{v}' not found or ambiguous; use list_audio_devices. Candidates: {[d['description'] for d in (hits or devs)][:8]}")
    if t == "steps":
        if not isinstance(v, list):
            raise ToolError("param 'steps' must be an array")
        return [normalize_action(engine, s, warnings, in_steps=True) for s in v]
    raise ToolError(f"unsupported field type {t}")


def normalize_action(engine, action, warnings=None, in_steps=False):
    warnings = warnings if warnings is not None else []
    if not isinstance(action, dict) or "type" not in action:
        raise ToolError("action must be an object like {\"type\": \"hotkey\", \"params\": {...}}; see list_actions")
    t = action["type"]
    if t == "delay" and in_steps:
        ms = (action.get("params") or {}).get("ms", 500)
        return {"type": "delay", "params": {"ms": _coerce(engine, {"key": "ms", "type": "int", "min": 0, "max": 60000}, ms, warnings)}}
    if t not in actions.ACTIONS or t == "delay":
        near = difflib.get_close_matches(str(t), list(actions.ACTIONS), 3)
        raise ToolError(f"unknown action type '{t}'" + (f" (did you mean {', '.join(near)}?)" if near else "; see list_actions"))
    meta = actions.ACTIONS[t]
    if in_steps and not meta["multi"]:
        raise ToolError(f"action '{t}' cannot be used inside a multi action")
    params_in = action.get("params") or {}
    if not isinstance(params_in, dict):
        raise ToolError("'params' must be an object")
    params = copy.deepcopy(meta["defaults"])
    if t == "folder":
        for k in params_in:
            if k not in ("name", "folder"):
                raise ToolError(f"folder only accepts 'name' (and an existing 'folder' id), not '{k}'")
        params = {}
        if "name" in params_in:
            params["name"] = str(params_in["name"])
        if params_in.get("folder"):
            if params_in["folder"] not in engine.profile["folders"]:
                raise ToolError("unknown folder id; omit it to create a new folder")
            params["folder"] = params_in["folder"]
        return {"type": t, "params": params}
    fields = {f["key"]: f for f in meta["fields"]}
    for k, v in params_in.items():
        if k not in fields:
            raise ToolError(f"action '{t}' has no param '{k}'; valid params: {list(fields) or 'none'}")
        params[k] = _coerce(engine, fields[k], v, warnings)
    if t == "hotkey" and not params.get("hotkey"):
        warnings.append("hotkey action has no shortcut set")
    if t == "website" and not params.get("url"):
        warnings.append("website action has no url")
    if t == "command" and not params.get("cmd"):
        warnings.append("command action has no command")
    if t == "app" and not params.get("app"):
        warnings.append("app action has no app")
    if t == "profile" and not params.get("profile"):
        warnings.append("profile action has no target profile")
    return {"type": t, "params": params}


def normalize_icon(spec):
    if spec is None:
        return None
    if isinstance(spec, str):
        spec = {"glyph": spec} if spec in icons.GLYPHS else {"theme": spec}
    if not isinstance(spec, dict) or len(spec) != 1:
        raise ToolError("icon must be null or an object with exactly one of: glyph, theme, file, app, image_base64")
    (kind, val), = spec.items()
    if kind == "glyph":
        if val not in icons.GLYPHS:
            near = difflib.get_close_matches(str(val), icons.GLYPH_NAMES, 5)
            raise ToolError(f"unknown glyph '{val}'" + (f"; similar: {', '.join(near)}" if near else "; use list_icons"))
        return {"kind": "glyph", "value": val}
    if kind == "theme":
        if QIcon.fromTheme(str(val)).isNull():
            raise ToolError(f"theme icon '{val}' not found; use list_icons with a query")
        return {"kind": "theme", "value": str(val)}
    if kind == "app":
        a = icons.find_app(_resolve_app(val))
        if not a or not a["icon"]:
            raise ToolError("that app has no icon")
        return {"kind": "file" if a["icon"].startswith("/") else "theme", "value": a["icon"]}
    if kind == "file":
        path = os.path.expanduser(str(val))
        if not os.path.isfile(path) or icons.file_image(path) is None:
            raise ToolError(f"cannot read an image at {path}")
        return import_image(path)
    if kind == "image_base64":
        raw = str(val)
        if raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        try:
            data = base64.b64decode(raw)
        except Exception:
            raise ToolError("image_base64 is not valid base64")
        if len(data) > 8 * 1024 * 1024:
            raise ToolError("image is larger than 8 MB")
        img = QImage()
        if not img.loadFromData(data):
            raise ToolError("image_base64 is not a readable image (png, jpg, gif, webp, bmp)")
        os.makedirs(model.ICON_DIR, exist_ok=True)
        dest = os.path.join(model.ICON_DIR, f"agent-{model.new_id()}.png")
        img.save(dest, "PNG")
        return {"kind": "file", "value": dest}
    raise ToolError(f"unknown icon source '{kind}'")


def _save_animated(raw):
    """Keep GIF / animated WebP bytes as they are (normalize_icon would flatten them to one PNG frame)."""
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        raise ToolError("image_base64 is not valid base64")
    ext = "gif" if data[:4] == b"GIF8" else "webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None
    if not ext:
        return None
    if len(data) > 32 * 1024 * 1024:
        raise ToolError("image is larger than 32 MB")
    os.makedirs(model.ICON_DIR, exist_ok=True)
    dest = os.path.join(model.ICON_DIR, f"wallpaper-{model.new_id()}.{ext}")
    with open(dest, "wb") as f:
        f.write(data)
    return {"kind": "file", "value": dest}


_PATCH_KEYS = {"action", "hold", "alt", "icon", "title", "show_title", "title_pos", "title_size", "title_color", "bold", "icon_color",
               "background"}
_LOC_KEYS = {"index", "row", "col", "profile", "page", "folder"}


def _color(v, name):
    c = QColor(str(v))
    if not c.isValid():
        raise ToolError(f"{name} must be a color like '#ff8800'")
    return c.name()


def build_patch(engine, item, warnings):
    unknown = set(item) - _PATCH_KEYS - _LOC_KEYS
    if unknown:
        raise ToolError(f"unknown field(s): {sorted(unknown)}; allowed: {sorted(_PATCH_KEYS)}")
    p = {}
    if "action" in item:
        p["action"] = None if item["action"] is None else normalize_action(engine, item["action"], warnings)
    if "hold" in item:
        h = item["hold"]
        if h is not None:
            h = normalize_action(engine, h, warnings, in_steps=True) if h.get("type") not in ("counter_reset", "timer_reset") else {"type": h["type"], "params": {}}
        p["hold"] = h
    if "icon" in item:
        p["icon"] = normalize_icon(item["icon"])
    if "alt" in item:
        al = item["alt"]
        if al is None:
            p["alt"] = None
        else:
            if not isinstance(al, dict) or not al:
                raise ToolError("alt must be null or an object with any of: icon, title, title_color, icon_color, background")
            bad = set(al) - {"icon", "title", "title_color", "icon_color", "background"}
            if bad:
                raise ToolError(f"alt has unknown field(s) {sorted(bad)}")
            out = {}
            if "icon" in al:
                ic = normalize_icon(al["icon"])
                if ic:
                    out["icon"] = ic
            if "title" in al:
                out["title"] = str(al["title"])
            for src, dst in (("title_color", "title_color"), ("icon_color", "icon_color"), ("background", "bg")):
                if src in al:
                    out[dst] = _color(al[src], "alt." + src)
            p["alt"] = out or None
    if "title" in item:
        if not isinstance(item["title"], str):
            raise ToolError("title must be a string")
        p["title"] = item["title"]
    if "show_title" in item:
        p["show_title"] = bool(item["show_title"])
    if "bold" in item:
        p["bold"] = bool(item["bold"])
    if "title_pos" in item:
        if item["title_pos"] not in ("top", "middle", "bottom"):
            raise ToolError("title_pos must be top, middle or bottom")
        p["title_pos"] = item["title_pos"]
    if "title_size" in item:
        try:
            n = int(item["title_size"])
        except (TypeError, ValueError):
            raise ToolError("title_size must be an integer 8-40")
        if not 8 <= n <= 40:
            raise ToolError("title_size must be 8-40")
        p["title_size"] = n
    for src, dst in (("title_color", "title_color"), ("icon_color", "icon_color"), ("background", "bg")):
        if src in item:
            p[dst] = _color(item[src], src)
    return p


# ---- locations & views ---------------------------------------------------------------------
def folder_chain(profile, fid):
    """(page_index, [folder ids from the page root down to fid]) or None."""
    def walk(keys, chain):
        for k in keys.values():
            for f in model.folder_ids(k):
                if f == fid:
                    return chain + [f]
                sub = profile["folders"].get(f)
                if sub and f not in chain:
                    r = walk(sub["keys"], chain + [f])
                    if r:
                        return r
        return None
    for i, pg in enumerate(profile["pages"]):
        r = walk(pg["keys"], [])
        if r:
            return i, r
    return None


def resolve_folder(profile, v):
    if v in profile["folders"]:
        return v
    hits = [fid for fid, f in profile["folders"].items() if f["name"].lower() == str(v).lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ToolError(f"folder name '{v}' is ambiguous; ids: {hits}")
    raise ToolError(f"folder '{v}' not found; ids/names are listed by get_layout")


def resolve(engine, args):
    prof = _resolve_profile(engine, args["profile"]) if args.get("profile") else engine.profile
    if (prof["cols"], prof["rows"]) != (engine.cols, engine.rows):
        raise ToolError(f"profile '{prof['name']}' is for a {prof['cols']}x{prof['rows']} deck; only {engine.cols}x{engine.rows} profiles can be used now")
    if args.get("folder") is not None:
        fid = resolve_folder(prof, args["folder"])
        chain = folder_chain(prof, fid)
        return prof, {"page": chain[0] if chain else 0, "folders": chain[1] if chain else [fid]}
    if args.get("page") is not None:
        n = len(prof["pages"])
        if not isinstance(args["page"], int) or not 1 <= args["page"] <= n:
            raise ToolError(f"page must be 1..{n}")
        return prof, {"page": args["page"] - 1, "folders": []}
    if prof is engine.profile:
        return prof, copy.deepcopy(engine.loc)
    return prof, {"page": 0, "folders": []}


def get_key_in(profile, loc, idx):
    if model.in_folder(profile, loc) and idx == 0:
        return model.BACK_KEY
    return model.container(profile, loc)["keys"].get(str(idx))


def key_index(engine, args, required=True, name="index"):
    cols, rows = engine.cols, engine.rows
    if args.get(name) is not None:
        idx = args[name]
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise ToolError(f"{name} must be an integer")
    elif name == "index" and args.get("row") is not None and args.get("col") is not None:
        r, c = args["row"], args["col"]
        if not (isinstance(r, int) and isinstance(c, int) and 1 <= r <= rows and 1 <= c <= cols):
            raise ToolError(f"row must be 1..{rows} and col 1..{cols}")
        idx = (r - 1) * cols + (c - 1)
    elif required:
        raise ToolError(f"give '{name}' (0-based, left-to-right then top-to-bottom)" + (" or row+col (1-based)" if name == "index" else ""))
    else:
        return None
    if not 0 <= idx < cols * rows:
        raise ToolError(f"{name} must be 0..{cols * rows - 1}")
    return idx


def key_view(engine, profile, idx, key, locked=False):
    cols = engine.cols
    v = {"index": idx, "row": idx // cols + 1, "col": idx % cols + 1, "ui_label": f"KEY {idx + 1}"}
    if locked:
        v["locked"] = "fixed Back key"
    if model.key_is_empty(key):
        v["empty"] = True
        return v
    a = key.get("action")
    if a:
        params = copy.deepcopy(a.get("params", {}))
        if a["type"] == "hotkey":
            params["hotkey"] = format_hotkey(params.get("hotkey"))
        if a["type"] == "folder":
            fid = params.get("folder")
            params = {"folder": fid, "name": profile["folders"].get(fid, {}).get("name")}
        if a["type"] == "profile":
            p = engine.store.get(params.get("profile"))
            params["profile_name"] = p["name"] if p else None
        v["action"] = {"type": a["type"], "params": params}
    else:
        v["action"] = None
    for f in ("title", "show_title", "title_pos", "title_size", "title_color", "bold", "icon_color"):
        v[f] = key.get(f)
    v["background"] = key.get("bg")
    if key.get("hold"):
        hp = copy.deepcopy(key["hold"].get("params", {}))
        if key["hold"]["type"] == "hotkey":
            hp["hotkey"] = format_hotkey(hp.get("hotkey"))
        v["hold"] = {"type": key["hold"]["type"], "params": hp}
    al = key.get("alt")
    if al:
        v["alt"] = {("background" if f == "bg" else f): (({al[f]["kind"]: al[f]["value"]}) if f == "icon" else al[f]) for f in al}
    src = actions.live_source(key.get("action"))
    if src:
        v["follows_system_state"] = src
    ic = key.get("icon")
    v["icon"] = {ic["kind"]: ic["value"]} if ic and ic.get("value") else None
    return v


def where(profile, loc):
    pages = profile["pages"]
    fids = loc.get("folders") or []
    f = profile["folders"].get(fids[-1]) if fids else None
    return {"profile": {"id": profile["id"], "name": profile["name"]}, "page": loc["page"] + 1, "pages": len(pages),
            "page_name": pages[loc["page"]]["name"], "folder": {"id": f["id"], "name": f["name"]} if f else None}


def layout_view(engine, profile, loc):
    in_f = model.in_folder(profile, loc)
    n = engine.cols * engine.rows
    keys, empty = [], []
    for i in range(n):
        k = get_key_in(profile, loc, i)
        if model.key_is_empty(k):
            empty.append(i)
        else:
            keys.append(key_view(engine, profile, i, k, locked=in_f and i == 0))
    folders = []
    for fid, f in profile["folders"].items():
        ch = folder_chain(profile, fid)
        folders.append({"id": fid, "name": f["name"], "keys": len(f["keys"]), "page": (ch[0] + 1) if ch else None,
                        "parent_folder": ch[1][-2] if ch and len(ch[1]) > 1 else None})
    return {"location": where(profile, loc), "grid": {"cols": engine.cols, "rows": engine.rows},
            "wallpaper": ({**wallpaper.normalize(profile.get("wallpaper")), "animated": wallpaper.animation_info(profile["wallpaper"]["file"])[0],
                           **({"animation": engine.anim_state} if profile is engine.profile else {})}
                          if wallpaper.normalize(profile.get("wallpaper")) else None),
            "keys": keys, "empty_indices": empty, "page_names": [p["name"] for p in profile["pages"]], "folders": folders}


def _png_b64(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(bytes(ba)).decode()


def render_view(engine, profile, loc, idx, size):
    """A key as it looks on the deck right now, wallpaper (and its current animation frame) included."""
    if profile is engine.profile and loc.get("page") == engine.loc.get("page") and (loc.get("folders") or []) == engine.loc.get("folders", []):
        return engine.render(idx, size)
    return render.render_key(get_key_in(profile, loc, idx), size,
                             backdrop=wallpaper.slice_for(profile.get("wallpaper"), idx, engine.cols, engine.rows, size))


def deck_image(engine, profile, loc, size=96):
    cols, rows = engine.cols, engine.rows
    gap, pad = max(6, size // 8), max(12, size // 5)
    w = pad * 2 + cols * size + (cols - 1) * gap
    h = pad * 2 + rows * size + (rows - 1) * gap
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("#1a1a1d"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont(QGuiApplication.font().family())
    f.setPixelSize(max(9, size // 7))
    f.setBold(True)
    p.setFont(f)
    for i in range(cols * rows):
        x = pad + (i % cols) * (size + gap)
        y = pad + (i // cols) * (size + gap)
        p.drawImage(x, y, render_view(engine, profile, loc, i, size))
        badge = QRectF(x + 3, y + 3, size * 0.28, size * 0.24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(badge, 4, 4)
        p.setPen(QColor("#9fd0ff"))
        p.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), str(i))
    p.end()
    return img


# ---- tools --------------------------------------------------------------------------------
TOOLS = {}

LOC = {
    "profile": {"type": "string", "description": "Profile id or name. Default: the active profile."},
    "page": {"type": "integer", "description": "Page number, 1-based. Default: the page currently shown."},
    "folder": {"type": "string", "description": "Folder id or name (from get_layout). Targets that folder instead of a page."},
}
KEYPOS = {
    "index": {"type": "integer", "description": "Key index, 0-based, left-to-right then top-to-bottom. The UI label 'KEY n' is index n-1."},
    "row": {"type": "integer", "description": "Row, 1-based (alternative to index, with col)."},
    "col": {"type": "integer", "description": "Column, 1-based."},
}
PATCH = {
    "action": {"type": ["object", "null"], "description": "{type, params} from list_actions; null removes the action. Folder: {type:'folder', params:{name}} creates a new folder and returns its id."},
    "title": {"type": "string"},
    "show_title": {"type": "boolean"},
    "title_pos": {"type": "string", "enum": ["top", "middle", "bottom"]},
    "title_size": {"type": "integer", "minimum": 8, "maximum": 40},
    "title_color": {"type": "string", "description": "#rrggbb"},
    "bold": {"type": "boolean"},
    "icon": {"type": ["object", "string", "null"], "description": "null = default icon for the action. Otherwise exactly one of {glyph:'play'} (built-in, see list_icons), {theme:'firefox'} (system icon), {app:'firefox.desktop'}, {file:'/abs/img.png'} or {image_base64:'...'} (png/jpg/gif/webp, copied into Deckhand)."},
    "icon_color": {"type": "string", "description": "#rrggbb tint for built-in glyphs"},
    "background": {"type": "string", "description": "#rrggbb key background"},
    "hold": {"type": ["object", "null"], "description": "Second action {type, params} that runs when the key is HELD (default 0.5 s) instead of tapped; a quick tap runs 'action'. Not for folders/navigation. Counter and timer keys get a hold-to-reset automatically. null removes it."},
    "alt": {"type": ["object", "null"], "description": "Active look shown instead when the key is 'on': {icon, title, title_color, icon_color, background}; only the fields given differ from the normal look. For actions that follow system state (mute, mic mute) it shows while muted; for any other key it toggles on every press. null removes it. Example mic key: {icon:{glyph:'mic'}, alt:{icon:{glyph:'mic-off'}, background:'#3a1010'}}."},
}


def tool(name, description, props=None, required=(), level="read", destructive=False):
    def deco(fn):
        schema = {"type": "object", "properties": props or {}, "additionalProperties": False}
        if required:
            schema["required"] = list(required)
        TOOLS[name] = {"name": name, "description": description, "inputSchema": schema, "level": level, "fn": fn,
                       "annotations": {"readOnlyHint": level == "read", "destructiveHint": destructive,
                                       "idempotentHint": level == "read", "openWorldHint": level == "full"}}
        return fn
    return deco


def _loc_args(a):
    return {k: a[k] for k in ("profile", "page", "folder") if k in a}


def describe_action(a, depth=0):
    """Plain-language description of what an action would do, for approval prompts."""
    pad = "  " * depth
    t, p = a["type"], a.get("params", {})
    name = actions.ACTIONS[t]["name"] if t in actions.ACTIONS else t
    if t == "command":
        return f"{pad}Run shell command{' (in a terminal)' if p.get('terminal') else ''}:\n{pad}  {p.get('cmd', '')}"
    if t == "text":
        return f"{pad}Type text into the focused app:\n{pad}  {p.get('text', '')[:400]}"
    if t == "hotkey":
        return f"{pad}Send keyboard shortcut: {format_hotkey(p.get('hotkey')) or '(none)'}"
    if t == "website":
        return f"{pad}Open website: {p.get('url', '')}"
    if t == "http":
        body = (p.get("body") or "")[:200]
        return f"{pad}Send HTTP {p.get('method', 'GET')} request to {p.get('url', '')}" + (f"\n{pad}  body: {body}" if body else "")
    if t == "file":
        return f"{pad}Open file or folder: {p.get('path', '')}"
    if t == "app":
        ap = icons.find_app(p.get("app", ""))
        return f"{pad}Launch app: {ap['name'] if ap else p.get('app', '')}"
    if t == "delay":
        return f"{pad}Wait {p.get('ms', 0)} ms"
    if t == "multi":
        steps = p.get("steps", [])
        return f"{pad}Multi action ({len(steps)} steps):\n" + "\n".join(describe_action(s, depth + 1) for s in steps)
    extra = actions.describe(a)
    return f"{pad}{name}" + (f": {extra}" if extra and extra != actions.ACTIONS.get(t, {}).get("desc") else "")


class Tools:
    def __init__(self, engine):
        self.e = engine

    def prepare(self, name, args):
        """Validate a full-control call and return a human summary of what it will do (for the approval prompt)."""
        t = TOOLS.get(name)
        if not t or t["level"] != "full":
            return None
        if not isinstance(args, dict):
            raise ToolError("arguments must be an object")
        e = self.e
        if name == "press_key":
            prof, loc = resolve(e, _loc_args(args))
            idx = key_index(e, args)
            k = get_key_in(prof, loc, idx)
            act = (k.get("hold") if args.get("hold") else k.get("action")) if k else None
            if not act:
                raise ToolError(f"key {idx} has no {'hold ' if args.get('hold') else ''}action")
            return f"Press KEY {idx + 1}" + (f" \u201c{k['title']}\u201d" if k.get("title") else "") + ":\n" + describe_action(act)
        if name == "run_action":
            if "action" not in args:
                raise ToolError("action is required")
            act = normalize_action(e, args["action"], [])
            return "Run an action:\n" + describe_action(act)
        return name

    @property
    def level(self):
        return self.e.settings.get("agent_access", "full")

    def visible(self):
        lv = LEVELS.get(self.level, 2)
        return [t for t in TOOLS.values() if LEVELS[t["level"]] <= lv]

    def call(self, name, args):
        t = TOOLS.get(name)
        if not t:
            raise ToolError(f"unknown tool '{name}'")
        if LEVELS[t["level"]] > LEVELS.get(self.level, 2):
            raise ToolError(f"'{name}' needs access level '{t['level']}', but the user set Deckhand to '{self.level}'. "
                            f"They can change it in Deckhand > Connect agents.")
        if not isinstance(args, dict):
            raise ToolError("arguments must be an object")
        bad = set(args) - set(t["inputSchema"]["properties"])
        if bad:
            raise ToolError(f"unknown argument(s) {sorted(bad)} for {name}; allowed: {sorted(t['inputSchema']['properties'])}")
        return t["fn"](self, args)

    # -- read ------------------------------------------------------------------------------
    @tool("get_status", "Overview of the app, the connected Stream Deck, active profile and what is currently shown on the deck. Call this first.")
    def get_status(self, a):
        e = self.e
        dev = e.dev
        return {"app": "Deckhand", "version": VERSION,
                "device": {"connected": bool(dev), "model": dev.model.name if dev else None, "serial": dev.serial if dev else None,
                           "firmware": e.firmware if dev else None, "state": e.conn_info.get("state"), "message": e.conn_info.get("title"),
                           **({"hint": trouble.guide(e.conn_info)["summary"]} if not dev else {})},
                "grid": {"cols": e.cols, "rows": e.rows, "keys": e.n_keys},
                "settings": {"brightness": e.settings["brightness"], "sleep_minutes": e.settings["sleep_minutes"],
                             "pressed_effect": e.settings["pressed_effect"]},
                "view": where(e.profile, e.loc), "can_undo": e.can_undo, "can_redo": e.can_redo,
                "agent_access": self.level, "profiles": len(e.profiles()),
                "notes": "Edits appear on the deck and in the editor immediately and can be undone by the user with Ctrl+Z."}

    @tool("list_actions", "Catalog of every action type a key can have, with exact parameter schemas. Use these types/params in set_key.",
          {"category": {"type": "string", "description": "Optional filter: System, Widgets, Multimedia, Navigation, Multi Action"}})
    def list_actions(self, a):
        return catalog(a.get("category"))

    @tool("list_icons", "Find icons for keys. Built-in glyphs are crisp white line icons (best default). Theme icons are the system icon theme (app logos, folders, etc).",
          {"query": {"type": "string", "description": "Substring filter. Theme icons are only listed when a query is given."}})
    def list_icons(self, a):
        q = (a.get("query") or "").lower()
        out = {"glyphs": [n for n in icons.GLYPH_NAMES if q in n]}
        if q:
            names = [n for n in icons.theme_icon_names() if q in n]
            out["theme_icons"] = names[:80]
            if len(names) > 80:
                out["theme_icons_note"] = f"{len(names)} matches; showing 80, refine the query"
        else:
            out["note"] = "Pass a query to search system theme icons as well."
        return out

    @tool("list_apps", "Installed desktop applications usable with the 'app' action (Open App) or as an icon source.",
          {"query": {"type": "string"}})
    def list_apps(self, a):
        q = (a.get("query") or "").lower()
        hits = [x for x in icons.installed_apps() if q in x["name"].lower() or q in x["id"].lower()]
        return {"count": len(hits), "apps": [{"id": x["id"], "name": x["name"], "icon": x["icon"]} for x in hits[:120]]}

    @tool("list_audio_devices", "Microphones and outputs, with the current system default marked. Use a device name as the 'device' param of the mic mute / mute actions to pin a key to one device; leave it empty to follow the system default.")
    def list_audio_devices(self, a):
        return {"microphones": sysinfo.audio_devices("source"), "outputs": sysinfo.audio_devices("sink")}

    @tool("list_profiles", "All profiles. Only profiles matching the connected deck's grid size are editable.")
    def list_profiles(self, a):
        e = self.e
        return [{"id": p["id"], "name": p["name"], "grid": f"{p['cols']}x{p['rows']}", "pages": len(p["pages"]),
                 "folders": len(p["folders"]), "active": p is e.profile, "editable": (p["cols"], p["rows"]) == (e.cols, e.rows)}
                for p in e.store.profiles]

    @tool("get_layout", "Full contents of one page or folder: every non-empty key (action, title, icon, colors) plus empty slots, page names and the folder tree. Defaults to what is currently shown.", LOC)
    def get_layout(self, a):
        prof, loc = resolve(self.e, a)
        return layout_view(self.e, prof, loc)

    @tool("screenshot", "Render the deck (or a single key) as a PNG so you can SEE the result. Each key is labelled with its index. Use after edits to verify the design.",
          {**LOC, "index": KEYPOS["index"], "size": {"type": "integer", "minimum": 48, "maximum": 200, "description": "Pixels per key (default 96)"}})
    def screenshot(self, a):
        e = self.e
        prof, loc = resolve(e, a)
        size = a.get("size") or 96
        if not isinstance(size, int) or not 48 <= size <= 200:
            raise ToolError("size must be an integer 48-200")
        idx = key_index(e, a, required=False)
        if idx is not None:
            img = render_view(e, prof, loc, idx, 192)
        else:
            img = deck_image(e, prof, loc, size)
        return Content([{"type": "image", "data": _png_b64(img), "mimeType": "image/png"},
                        {"type": "text", "text": json.dumps({"shown": where(prof, loc), "note": "numbers in the corner of each key are key indices"})}])

    @tool("export_profile", "Return a profile as portable JSON (round-trips with import_profile).", {"profile": LOC["profile"]})
    def export_profile(self, a):
        prof = _resolve_profile(self.e, a["profile"]) if a.get("profile") else self.e.profile
        return copy.deepcopy(prof)

    # -- edit ------------------------------------------------------------------------------
    def _apply(self, args, items):
        e = self.e
        prof, loc = resolve(e, args)
        in_f = model.in_folder(prof, loc)
        warnings, prepared = [], []
        for it in items:
            if not isinstance(it, dict):
                raise ToolError("each key must be an object")
            idx = key_index(e, it)
            if in_f and idx == 0:
                raise ToolError("key 0 inside a folder is the fixed Back key; use index 1 or higher")
            patch = build_patch(e, it, warnings)
            act = patch.get("action")
            if act and act["type"] == "app" and act["params"].get("app") and "icon" not in patch:
                cur = get_key_in(prof, loc, idx)
                if not (cur and cur.get("icon") and not cur["icon"].get("auto")):
                    ap = icons.find_app(act["params"]["app"])
                    if ap and ap["icon"]:
                        patch["icon"] = {"kind": "file" if ap["icon"].startswith("/") else "theme", "value": ap["icon"], "auto": True}
            if not patch:
                raise ToolError(f"key {idx}: nothing to change; give action, title, icon, ...")
            prepared.append((idx, patch))
        created = {}
        with e.at(prof, loc):
            with e.mutate():
                for idx, patch in prepared:
                    r = e.apply_key_patch(idx, patch)
                    if "folder" in r:
                        created[str(idx)] = r["folder"]
        res = {"updated": sorted({i for i, _ in prepared}), "location": where(prof, loc)}
        if created:
            res["created_folders"] = created
            res["tip"] = "Fill a new folder by passing its id as 'folder' to set_keys. Folder key 0 is always Back, use 1+."
        if warnings:
            res["warnings"] = warnings
        return res

    @tool("set_key", "Create or change one key. Only the fields you pass change (patch semantics). Assigning an action to an empty key creates it. The default icon comes from the action type, so custom icons are optional.",
          {**LOC, **KEYPOS, **PATCH}, level="edit")
    def set_key(self, a):
        item = {k: v for k, v in a.items() if k not in ("profile", "page", "folder")}
        return self._apply(_loc_args(a), [item])

    @tool("set_keys", "Change many keys at once as ONE undo step (all-or-nothing validation). Prefer this for building a whole page or folder.",
          {**LOC, "keys": {"type": "array", "description": "Each item: index (or row+col) plus any set_key fields.",
                           "items": {"type": "object", "properties": {**KEYPOS, **PATCH}}}}, required=["keys"], level="edit")
    def set_keys(self, a):
        if not isinstance(a["keys"], list) or not a["keys"]:
            raise ToolError("keys must be a non-empty array")
        return self._apply(_loc_args(a), a["keys"])

    @tool("clear_keys", "Empty one or more keys (or the whole page/folder with all=true). Undoable.",
          {**LOC, "indices": {"type": "array", "items": {"type": "integer"}}, "all": {"type": "boolean"}}, level="edit", destructive=True)
    def clear_keys(self, a):
        e = self.e
        prof, loc = resolve(e, _loc_args(a))
        in_f = model.in_folder(prof, loc)
        if a.get("all"):
            idxs = list(range(e.n_keys))
        else:
            idxs = a.get("indices") or []
            if not idxs:
                raise ToolError("give indices or all=true")
            for i in idxs:
                if not isinstance(i, int) or not 0 <= i < e.n_keys:
                    raise ToolError(f"index {i} out of range 0..{e.n_keys - 1}")
        idxs = [i for i in idxs if not (in_f and i == 0)]
        with e.at(prof, loc):
            with e.mutate():
                for i in idxs:
                    model.container(prof, loc)["keys"].pop(str(i), None)
        return {"cleared": idxs}

    @tool("move_key", "Move a key to another slot (swaps if the target is occupied) or copy it (copy=true, folders are duplicated too).",
          {**LOC, "from_index": {"type": "integer"}, "to_index": {"type": "integer"}, "copy": {"type": "boolean"}},
          required=["from_index", "to_index"], level="edit")
    def move_key(self, a):
        e = self.e
        prof, loc = resolve(e, _loc_args(a))
        s, d = key_index(e, a, name="from_index"), key_index(e, a, name="to_index")
        if model.in_folder(prof, loc) and 0 in (s, d):
            raise ToolError("key 0 inside a folder is the fixed Back key")
        with e.at(prof, loc):
            e.move_key(s, d, bool(a.get("copy")))
        return {"ok": True}

    @tool("set_wallpaper", "Set, adjust or remove the profile's wallpaper: one image spread across ALL keys (keys with a black background show their slice). "
          "Give image to set it; give only fit/zoom/focus/dim to adjust the current one; remove=true clears it. Check the result with screenshot.",
          {"profile": LOC["profile"], "image": {"type": ["object", "string"], "description": "{file:'/abs/path.png'} or {image_base64:'...'}"},
           "fit": {"type": "string", "enum": list(wallpaper.FITS)}, "zoom": {"type": "integer", "minimum": 100, "maximum": 400},
           "focus_x": {"type": "integer", "minimum": 0, "maximum": 100}, "focus_y": {"type": "integer", "minimum": 0, "maximum": 100},
           "dim": {"type": "integer", "minimum": 0, "maximum": 90, "description": "Darken percent so icons stay readable (default 35)"},
           "animate": {"type": "boolean", "description": "Play animated GIF/WebP wallpapers (default true)"},
           "fps": {"type": "integer", "minimum": 5, "maximum": 20, "description": "Animation frame rate on the deck (default 12)"},
           "remove": {"type": "boolean"}}, level="edit")
    def set_wallpaper(self, a):
        e = self.e
        prof, _ = resolve(e, {"profile": a["profile"]} if a.get("profile") else {})
        if a.get("remove"):
            with e.at(prof, {"page": 0, "folders": []}):
                e.set_wallpaper(None)
            return {"wallpaper": None}
        cfg = wallpaper.normalize(prof.get("wallpaper")) or dict(wallpaper.DEFAULTS)
        if a.get("image") is not None:
            img = a["image"]
            raw = img.get("image_base64") if isinstance(img, dict) else None
            spec = _save_animated(raw) if raw else None
            spec = spec or normalize_icon(img if isinstance(img, dict) else {"file": img})
            if not spec or spec["kind"] != "file":
                raise ToolError("image must be {file: path} or {image_base64: data}")
            cfg["file"] = spec["value"]
        if not cfg.get("file"):
            raise ToolError("no wallpaper yet: pass image")
        for src, dst, lo, hi in (("zoom", "zoom", 100, 400), ("focus_x", "fx", 0, 100), ("focus_y", "fy", 0, 100), ("dim", "dim", 0, 90)):
            if src in a:
                if not isinstance(a[src], int) or not lo <= a[src] <= hi:
                    raise ToolError(f"{src} must be an integer {lo}-{hi}")
                cfg[dst] = a[src]
        if "fit" in a:
            cfg["fit"] = a["fit"]
        if "animate" in a:
            cfg["animate"] = bool(a["animate"])
        if "fps" in a:
            if not isinstance(a["fps"], int) or not 5 <= a["fps"] <= 20:
                raise ToolError("fps must be an integer 5-20")
            cfg["fps"] = a["fps"]
        with e.at(prof, {"page": 0, "folders": []}):
            e.set_wallpaper(cfg)
        return {"wallpaper": wallpaper.normalize(prof.get("wallpaper"))}

    @tool("get_auto_switch", "Rules that switch the deck's profile when a certain app/window gets focus, plus the focused app and recently focused apps (names only, no window titles).")
    def get_auto_switch(self, a):
        e = self.e
        cfg = autoswitch.clean_config(e.settings.get("auto_switch"))

        def pname(pid):
            p = e.store.get(pid)
            return p["name"] if p else None
        w = e.windows
        return {"enabled": cfg["enabled"], "default_profile": pname(cfg["default"]) if cfg["default"] else None,
                "rules": [{"kind": r["kind"], "pattern": r["pattern"], "profile": pname(r["profile"]), "profile_id": r["profile"]} for r in cfg["rules"]],
                "supported": w.supported, "problem": w.problem or None,
                "focused_app": (w.active.get("cls") or w.active.get("name")) if w.active else None,
                "recent_apps": [x["cls"] or x["name"] or x["desktop"] for x in w.recent[:12]]}

    @tool("set_auto_switch", "Replace the auto-switch configuration. rules: [{app:'firefox', profile:'Browsing'}] or [{title:'YouTube', profile:'Media'}] (prefix a pattern with 're:' for a regular expression). First match wins. default_profile applies when nothing matches (omit/empty = keep the current profile). Only profiles matching the deck size can be used.",
          {"enabled": {"type": "boolean"}, "default_profile": {"type": "string"},
           "rules": {"type": "array", "items": {"type": "object", "properties": {"app": {"type": "string"}, "title": {"type": "string"}, "profile": {"type": "string"}}, "required": ["profile"]}}},
          level="edit")
    def set_auto_switch(self, a):
        e = self.e
        cfg = autoswitch.clean_config(e.settings.get("auto_switch"))
        if "enabled" in a:
            cfg["enabled"] = bool(a["enabled"])
        if "default_profile" in a:
            cfg["default"] = _resolve_profile(e, a["default_profile"])["id"] if a["default_profile"] else ""
        if "rules" in a:
            rules = []
            if not isinstance(a["rules"], list) or len(a["rules"]) > 100:
                raise ToolError("rules must be an array of at most 100 items")
            for r in a["rules"]:
                if not isinstance(r, dict) or ("app" in r) == ("title" in r) or "profile" not in r:
                    raise ToolError("each rule needs exactly one of app / title, plus profile")
                kind = "app" if "app" in r else "title"
                pat = str(r[kind]).strip()
                if not pat:
                    raise ToolError("a rule pattern is empty")
                if pat.lower().startswith("re:"):
                    try:
                        __import__("re").compile(pat[3:])
                    except Exception:
                        raise ToolError(f"'{pat}' is not a valid regular expression")
                p = _resolve_profile(e, r["profile"])
                if (p["cols"], p["rows"]) != (e.cols, e.rows):
                    raise ToolError(f"profile '{p['name']}' is for a different deck size")
                rules.append({"kind": kind, "pattern": pat, "profile": p["id"]})
            cfg["rules"] = rules
        e.set_auto_switch(cfg)
        return self.get_auto_switch({})

    @tool("list_templates", "Ready-made page templates (media, streaming, productivity, developer, monitor) you can add with add_template_page.")
    def list_templates(self, a):
        return [{"id": t, "name": n, "description": d} for t, n, d, _g in templates.names()]

    @tool("add_template_page", "Append a page built from a template to a profile (fits the deck size). Shows it on the deck unless the profile is not active.",
          {"template": {"type": "string"}, "profile": LOC["profile"]}, required=["template"], level="edit")
    def add_template_page(self, a):
        e = self.e
        if a["template"] not in templates.TEMPLATES:
            raise ToolError(f"unknown template; choose from {list(templates.TEMPLATES)}")
        prof, _ = resolve(e, {"profile": a["profile"]} if a.get("profile") else {})
        with e.at(prof, {"page": 0, "folders": []}):
            e.add_template_page(a["template"])
        return {"page": len(prof["pages"]), "pages": len(prof["pages"])}

    @tool("duplicate_page", "Duplicate a page (folders inside it are copied too) right after the original.",
          {"page": {"type": "integer"}, "profile": LOC["profile"]}, required=["page"], level="edit")
    def duplicate_page(self, a):
        e = self.e
        prof, _ = resolve(e, {"profile": a["profile"]} if a.get("profile") else {})
        if not isinstance(a["page"], int) or not 1 <= a["page"] <= len(prof["pages"]):
            raise ToolError(f"page must be 1..{len(prof['pages'])}")
        with e.at(prof, {"page": 0, "folders": []}):
            e.duplicate_page(a["page"] - 1)
        return {"pages": len(prof["pages"])}

    @tool("move_page", "Move a page earlier (direction=-1) or later (direction=1) in the page order.",
          {"page": {"type": "integer"}, "direction": {"type": "integer", "enum": [-1, 1]}, "profile": LOC["profile"]}, required=["page", "direction"], level="edit")
    def move_page(self, a):
        e = self.e
        prof, _ = resolve(e, {"profile": a["profile"]} if a.get("profile") else {})
        if not isinstance(a["page"], int) or not 1 <= a["page"] <= len(prof["pages"]) or a["direction"] not in (-1, 1):
            raise ToolError("page out of range or direction not -1/1")
        with e.at(prof, {"page": 0, "folders": []}):
            e.move_page(a["page"] - 1, a["direction"])
        return {"order": [p["name"] for p in prof["pages"]]}

    @tool("copy_page_to_profile", "Copy a page (with its folders) from the active profile into another profile for the same deck.",
          {"page": {"type": "integer"}, "to_profile": {"type": "string"}}, required=["page", "to_profile"], level="edit")
    def copy_page_to_profile(self, a):
        e = self.e
        if not isinstance(a["page"], int) or not 1 <= a["page"] <= len(e.profile["pages"]):
            raise ToolError(f"page must be 1..{len(e.profile['pages'])}")
        dst = _resolve_profile(e, a["to_profile"])
        try:
            name = e.copy_page_to_profile(a["page"] - 1, dst["id"])
        except ValueError as ex:
            raise ToolError(str(ex))
        return {"copied_to": name}

    @tool("add_page", "Append a new empty page to a profile.", {"profile": LOC["profile"], "name": {"type": "string"}}, level="edit")
    def add_page(self, a):
        e = self.e
        prof, _ = resolve(e, {"profile": a["profile"]} if a.get("profile") else {})
        with e.at(prof, {"page": 0, "folders": []}):
            with e.mutate():
                e.add_page()
                if a.get("name"):
                    prof["pages"][-1]["name"] = str(a["name"])
        return {"page": len(prof["pages"]), "pages": len(prof["pages"])}

    @tool("delete_page", "Delete a page (not the last one). Undoable on the active profile.", {"profile": LOC["profile"], "page": {"type": "integer"}},
          required=["page"], level="edit", destructive=True)
    def delete_page(self, a):
        e = self.e
        prof, _ = resolve(e, {"profile": a["profile"]} if a.get("profile") else {})
        n = len(prof["pages"])
        if n <= 1:
            raise ToolError("a profile needs at least one page")
        if not isinstance(a["page"], int) or not 1 <= a["page"] <= n:
            raise ToolError(f"page must be 1..{n}")
        with e.at(prof, {"page": 0, "folders": []}):
            e.delete_page(a["page"] - 1)
        return {"pages": len(prof["pages"])}

    @tool("rename", "Rename a page, a folder or a profile (give page, folder, or neither for the profile).",
          {"profile": LOC["profile"], "page": {"type": "integer"}, "folder": LOC["folder"], "name": {"type": "string"}},
          required=["name"], level="edit")
    def rename(self, a):
        e = self.e
        name = str(a["name"]).strip()
        if not name:
            raise ToolError("name is empty")
        prof, _ = resolve(e, {"profile": a["profile"]} if a.get("profile") else {})
        if a.get("page") is not None and not (isinstance(a["page"], int) and 1 <= a["page"] <= len(prof["pages"])):
            raise ToolError(f"page must be 1..{len(prof['pages'])}")
        fid = resolve_folder(prof, a["folder"]) if a.get("folder") is not None else None
        with e.at(prof, {"page": 0, "folders": []}):
            with e.mutate():
                if fid:
                    prof["folders"][fid]["name"] = name
                elif a.get("page") is not None:
                    prof["pages"][a["page"] - 1]["name"] = name
                else:
                    prof["name"] = name
        return {"ok": True}

    @tool("create_profile", "Create a new empty profile, or a copy of an existing one (copy_from). Switches to it unless activate=false.",
          {"name": {"type": "string"}, "copy_from": {"type": "string", "description": "Profile id or name to duplicate"}, "activate": {"type": "boolean"}},
          required=["name"], level="edit")
    def create_profile(self, a):
        e = self.e
        name = str(a["name"]).strip()
        if not name:
            raise ToolError("name is empty")
        if a.get("copy_from"):
            p = model.clone_profile(_resolve_profile(e, a["copy_from"]), name)
        else:
            p = model.new_profile(name, e.cols, e.rows)
        e.store.profiles.append(p)
        e._save_timer.start()
        if a.get("activate", True):
            e.switch_profile(p["id"])
        else:
            e.changed.emit()
        return {"id": p["id"], "name": p["name"], "active": p is e.profile}

    @tool("switch_profile", "Make a profile active (shown on the deck and in the editor).", {"profile": LOC["profile"]}, required=["profile"], level="edit")
    def switch_profile(self, a):
        p = _resolve_profile(self.e, a["profile"])
        if (p["cols"], p["rows"]) != (self.e.cols, self.e.rows):
            raise ToolError("that profile is for a different deck size")
        self.e.switch_profile(p["id"])
        return {"active": p["name"]}

    @tool("delete_profile", "Permanently delete a profile (cannot be undone). Requires confirm=true. The last profile cannot be deleted.",
          {"profile": LOC["profile"], "confirm": {"type": "boolean"}}, required=["profile", "confirm"], level="edit", destructive=True)
    def delete_profile(self, a):
        e = self.e
        if a.get("confirm") is not True:
            raise ToolError("set confirm=true to delete")
        p = _resolve_profile(e, a["profile"])
        if len(e.profiles()) <= 1:
            raise ToolError("cannot delete the last profile")
        if p is e.profile:
            e.delete_profile()
        else:
            e.store.profiles.remove(p)
            e._save_timer.start()
            e.changed.emit()
        return {"deleted": p["name"]}

    @tool("import_profile", "Add a profile from JSON produced by export_profile (object or JSON string). Becomes active if it fits the deck.",
          {"profile_json": {"type": ["object", "string"]}}, required=["profile_json"], level="edit")
    def import_profile(self, a):
        data = a["profile_json"]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                raise ToolError("profile_json is not valid JSON")
        if not isinstance(data, dict) or not all(k in data for k in ("name", "cols", "rows", "pages")):
            raise ToolError("not a Deckhand profile (needs name, cols, rows, pages)")
        before = {p["id"] for p in self.e.store.profiles}
        try:
            self.e.import_profile(data)
        except ValueError as ex:
            raise ToolError(str(ex))
        new = next((p for p in self.e.store.profiles if p["id"] not in before), None)
        return {"id": new["id"] if new else None, "name": data["name"]}

    @tool("navigate", "Change what the deck and editor show: a page, a folder, back one level, or home (page 1). Does not change any data.",
          {"page": {"type": "integer"}, "folder": LOC["folder"], "back": {"type": "boolean"}, "home": {"type": "boolean"}}, level="edit")
    def navigate(self, a):
        e = self.e
        if a.get("back"):
            e.go_back()
        elif a.get("home"):
            e.goto_page(0)
        elif a.get("folder") is not None:
            fid = resolve_folder(e.profile, a["folder"])
            ch = folder_chain(e.profile, fid)
            e.loc = {"page": ch[0] if ch else 0, "folders": ch[1] if ch else [fid]}
            e._nav_done()
        elif a.get("page") is not None:
            if not isinstance(a["page"], int) or not 1 <= a["page"] <= len(e.profile["pages"]):
                raise ToolError(f"page must be 1..{len(e.profile['pages'])}")
            e.goto_page(a["page"] - 1)
        else:
            raise ToolError("give page, folder, back or home")
        return where(e.profile, e.loc)

    @tool("set_settings", "Change deck settings: brightness (5-100), idle sleep in minutes (0 = never), key press animation.",
          {"brightness": {"type": "integer", "minimum": 5, "maximum": 100}, "sleep_minutes": {"type": "integer", "minimum": 0, "maximum": 1440},
           "pressed_effect": {"type": "boolean"}}, level="edit")
    def set_settings(self, a):
        if not a:
            raise ToolError("give at least one setting")
        e = self.e
        if "brightness" in a and (not isinstance(a["brightness"], int) or not 5 <= a["brightness"] <= 100):
            raise ToolError("brightness must be 5-100")
        if "sleep_minutes" in a and (not isinstance(a["sleep_minutes"], int) or not 0 <= a["sleep_minutes"] <= 1440):
            raise ToolError("sleep_minutes must be 0-1440")
        for k in ("brightness", "sleep_minutes"):
            if k in a:
                e.set_setting(k, a[k])
        if "pressed_effect" in a:
            e.set_setting("pressed_effect", bool(a["pressed_effect"]))
        return {k: e.settings[k] for k in ("brightness", "sleep_minutes", "pressed_effect")}

    @tool("undo", "Undo the last editing step on the active profile (same stack as the user's Ctrl+Z).", {"steps": {"type": "integer", "minimum": 1, "maximum": 50}}, level="edit")
    def undo(self, a):
        n = 0
        for _ in range(int(a.get("steps") or 1)):
            if not self.e.can_undo:
                break
            self.e.undo()
            n += 1
        return {"undone": n, "can_undo": self.e.can_undo}

    @tool("redo", "Redo undone steps.", {"steps": {"type": "integer", "minimum": 1, "maximum": 50}}, level="edit")
    def redo(self, a):
        n = 0
        for _ in range(int(a.get("steps") or 1)):
            if not self.e.can_redo:
                break
            self.e.redo()
            n += 1
        return {"redone": n, "can_redo": self.e.can_redo}

    # -- full control (user opted in via access level) ------------------------------------
    @tool("press_key", "Press a key as if the user physically pressed it: RUNS its action (launches apps, sends hotkeys, runs commands, navigates). hold=true runs the key's hold action instead.",
          {**LOC, **KEYPOS, "hold": {"type": "boolean"}}, level="full")
    def press_key(self, a):
        e = self.e
        prof, loc = resolve(e, _loc_args(a))
        idx = key_index(e, a)
        k = get_key_in(prof, loc, idx)
        act = (k.get("hold") if a.get("hold") else k.get("action")) if k else None
        if not act:
            raise ToolError(f"key {idx} has no {'hold ' if a.get('hold') else ''}action")
        if prof is e.profile and loc.get("page") == e.loc.get("page") and (loc.get("folders") or []) == e.loc.get("folders", []):
            e._run_action(idx, copy.deepcopy(act))
        else:
            e._pool.submit(e._exec, copy.deepcopy(act))
        return {"started": act["type"], "note": "runs asynchronously; failures show as a toast in Deckhand"}

    @tool("run_action", "Run any action immediately without putting it on a key (same schemas as set_key's action).",
          {"action": {"type": "object"}}, required=["action"], level="full")
    def run_action(self, a):
        warnings = []
        act = normalize_action(self.e, a["action"], warnings)
        if act["type"] == "folder":
            raise ToolError("folders only make sense on a key")
        self.e._pool.submit(self.e._exec, act)
        return {"started": act["type"], **({"warnings": warnings} if warnings else {})}


INSTRUCTIONS = """Deckhand controls an Elgato Stream Deck. Everything the user can do in the app you can do here.

Concepts: a profile has pages; a key can open a folder (a sub-page whose key 0 is a fixed Back key). Keys are indexed 0-based, left-to-right then top-to-bottom (row/col are 1-based alternatives). The UI label 'KEY n' is index n-1. Each key = one action + appearance (icon, title, colors). An action type's default icon is used unless you set one.

Workflow: get_status -> get_layout (see what exists) -> list_actions (exact params) -> set_keys (one undo step) -> screenshot (verify visually). Prefer built-in glyph icons (list_icons), dark backgrounds and short titles for legible 72px keys. Edits are live on the deck and the user can Ctrl+Z them; editing a non-active profile cannot be undone. Don't delete or overwrite the user's existing keys unless asked; add pages/profiles for new layouts. press_key/run_action execute real actions on the user's computer."""
