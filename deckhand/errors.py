"""Central error pipeline: friendly wording, a capped log file, and one signal the UI listens to.

Anything that can go wrong at runtime should end up in `report()` rather than a bare traceback:
the user gets a short plain-language toast, and the details go to errors.log.
"""
import errno
import os
import time
import traceback

from PyQt6.QtCore import QObject, pyqtSignal

from .model import CONFIG_DIR

LOG_FILE = os.path.join(CONFIG_DIR, "errors.log")
MAX_LOG = 256 * 1024

# command -> package that provides it on Arch (for "X isn't installed" messages)
TOOL_PACKAGES = {
    "konsole": "konsole", "wl-copy": "wl-clipboard", "wl-paste": "wl-clipboard", "pactl": "libpulse",
    "wpctl": "wireplumber", "spectacle": "spectacle", "xdg-open": "xdg-utils", "gio": "glib2",
    "loginctl": "systemd", "systemctl": "systemd", "busctl": "systemd", "nvidia-smi": "nvidia-utils", "sh": "bash",
}


class Notifier(QObject):
    message = pyqtSignal(str, str)  # level ("error" | "warn" | "info" | "ok"), text


notifier = Notifier()
_last = {}


def log(text):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG:
            os.replace(LOG_FILE, LOG_FILE + ".1")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%F %T')}\n{text.rstrip()}\n")
    except OSError:
        pass


def explain(exc, what=""):
    """Turn an exception into one short sentence a person can act on."""
    pre = f"{what}: " if what else ""
    if isinstance(exc, FileNotFoundError):
        name = getattr(exc, "filename", None)
        if name and os.path.basename(str(name)) in TOOL_PACKAGES:
            b = os.path.basename(str(name))
            return f"{pre}'{b}' isn't installed (Arch package: {TOOL_PACKAGES[b]})"
        if name:
            return f"{pre}{name} was not found"
        return f"{pre}file not found"
    if isinstance(exc, PermissionError):
        return f"{pre}permission denied" + (f" for {exc.filename}" if getattr(exc, "filename", None) else "")
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return f"{pre}the disk is full"
    if isinstance(exc, OSError) and exc.errno == errno.EROFS:
        return f"{pre}the folder is read-only"
    if isinstance(exc, TimeoutError):
        return f"{pre}timed out"
    msg = str(exc).strip()
    return f"{pre}{msg}" if msg else f"{pre}{exc.__class__.__name__}"


def report(text, level="error", exc=None, once_key=None, cooldown=30.0):
    """Log and surface a problem. `once_key` rate-limits repeats (e.g. a failing live widget)."""
    if once_key:
        now = time.monotonic()
        if now - _last.get(once_key, -1e9) < cooldown:
            return
        _last[once_key] = now
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else ""
    log(f"[{level}] {text}\n{detail}")
    notifier.message.emit(level, text)


def guard(fn, what="", default=None, level="error"):
    """Run fn(); on failure report a friendly message and return default."""
    try:
        return fn()
    except Exception as e:
        report(explain(e, what), level, exc=e)
        return default
