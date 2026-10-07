"""Backups (manual + a daily automatic one), safe restore, and a diagnostics report for bug reports."""
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import time
import zipfile

from . import errors, model

BACKUP_DIR = os.path.join(model.CONFIG_DIR, "backups")
KEEP_AUTO = 7
MAX_UNCOMPRESSED = 512 * 1024 * 1024
_NAME_OK = re.compile(r"^(manifest\.json|profiles\.json|settings\.json|recent_colors\.json|icons/[^/\\]{1,200})$")


def _add_config(z, with_icons=True):
    for fn in ("profiles.json", "settings.json", "recent_colors.json"):
        p = os.path.join(model.CONFIG_DIR, fn)
        if os.path.exists(p):
            z.write(p, fn)
    if with_icons and os.path.isdir(model.ICON_DIR):
        for fn in sorted(os.listdir(model.ICON_DIR)):
            p = os.path.join(model.ICON_DIR, fn)
            if os.path.isfile(p):
                z.write(p, "icons/" + fn)


def create_backup(dest, with_icons=True):
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({"app": "Deckhand", "format": 1, "created": time.strftime("%F %T")}))
        _add_config(z, with_icons)
    os.replace(tmp, dest)
    return dest


def auto_backup():
    """One small backup per day, newest 7 kept. Never raises."""
    try:
        if not os.path.exists(model.PROFILES_FILE):
            return None
        name = f"auto-{time.strftime('%Y%m%d')}.zip"
        dest = os.path.join(BACKUP_DIR, name)
        if os.path.exists(dest):
            return None
        create_backup(dest, with_icons=False)
        autos = sorted(f for f in os.listdir(BACKUP_DIR) if re.match(r"^auto-\d{8}\.zip$", f))
        for old in autos[:-KEEP_AUTO]:
            os.remove(os.path.join(BACKUP_DIR, old))     # only ever our own rotated auto-backups
        return dest
    except Exception as e:
        errors.log(f"auto backup failed: {e!r}")
        return None


def inspect_backup(path):
    """Validate a backup file without touching anything. Raises ValueError with a plain reason."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError("that file is not a Deckhand backup") from e
    with z:
        names = z.namelist()
        if "profiles.json" not in names:
            raise ValueError("this backup has no profiles in it")
        total = 0
        for info in z.infolist():
            if info.is_dir():
                continue
            if not _NAME_OK.match(info.filename) or ".." in info.filename:
                raise ValueError(f"the backup contains an unexpected file ({info.filename[:60]})")
            total += info.file_size
        if total > MAX_UNCOMPRESSED:
            raise ValueError("the backup is unreasonably large")
        try:
            data = json.loads(z.read("profiles.json"))
        except ValueError as e:
            raise ValueError("the profiles in this backup are damaged") from e
        profs = data.get("profiles") if isinstance(data, dict) else None
        if not isinstance(profs, list):
            raise ValueError("the profiles in this backup are damaged")
        manifest = {}
        if "manifest.json" in names:
            try:
                manifest = json.loads(z.read("manifest.json"))
            except ValueError:
                pass
        return {"profiles": len(profs), "created": manifest.get("created", "unknown date"), "icons": sum(1 for n in names if n.startswith("icons/"))}


def restore_backup(path):
    """Replace profiles/settings from a backup. The current state is saved first. Returns a summary dict."""
    info = inspect_backup(path)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    safety = create_backup(os.path.join(BACKUP_DIR, f"pre-restore-{time.strftime('%Y%m%d-%H%M%S')}.zip"))
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(path) as z:
        for info_ in z.infolist():
            if info_.is_dir() or info_.filename == "manifest.json":
                continue
            z.extract(info_, tmp)
        for fn in ("profiles.json", "settings.json", "recent_colors.json"):
            src = os.path.join(tmp, fn)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(model.CONFIG_DIR, fn + ".new"))
                os.replace(os.path.join(model.CONFIG_DIR, fn + ".new"), os.path.join(model.CONFIG_DIR, fn))
        icons_src = os.path.join(tmp, "icons")
        if os.path.isdir(icons_src):
            os.makedirs(model.ICON_DIR, exist_ok=True)
            for fn in os.listdir(icons_src):
                shutil.copyfile(os.path.join(icons_src, fn), os.path.join(model.ICON_DIR, fn))
    return {**info, "safety_copy": safety}


def diagnostics_text(engine):
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    from . import hardware, keymap
    lines = ["Deckhand diagnostics", f"Created: {time.strftime('%F %T')}", "",
             f"Python {sys.version.split()[0]}  |  Qt {QT_VERSION_STR}  |  PyQt {PYQT_VERSION_STR}",
             f"OS: {platform.platform()}", f"Session: {os.environ.get('XDG_SESSION_TYPE', '?')} / {os.environ.get('XDG_CURRENT_DESKTOP', '?')}", ""]
    try:
        info = hardware.scan(engine.settings.get("preferred_serial", ""))
        lines += ["Stream Deck", f"  state: {info['state']}  ({info['title']})", f"  detail: {info['detail']}",
                  f"  devices: {[(d['name'], d['supported']) for d in info['devices']]}", f"  rival programs: {[r['name'] for r in hardware.find_rivals()]}"]
    except Exception as e:
        lines.append(f"Stream Deck: scan failed ({e!r})")
    lines += [f"  connected now: {bool(engine.dev)}  |  grid {engine.cols}x{engine.rows}", "",
              f"/dev/uinput writable: {keymap.keyboard.available()}",
              f"Profiles: {len(engine.store.profiles)}  |  active: {engine.profile['name']}  |  pages: {len(engine.profile['pages'])}",
              f"Wallpaper animation: {engine.anim_state}", f"Window watcher: running={engine.windows.running} supported={engine.windows.supported} {engine.windows.problem}",
              f"Settings: { {k: v for k, v in engine.settings.items() if k not in ('auto_switch',)} }", "",
              "Recent errors (errors.log, last 60 lines):"]
    try:
        with open(errors.LOG_FILE, encoding="utf-8", errors="replace") as f:
            lines += ["  " + ln.rstrip() for ln in f.readlines()[-60:]]
    except OSError:
        lines.append("  (none)")
    return "\n".join(lines) + "\n"
