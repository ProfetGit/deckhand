"""Auto-switch profiles by the active window.

Wayland gives apps no way to ask "which window is active?", so a tiny KWin script (loaded only while
the feature is on) reports window activations to Deckhand over D-Bus. Rules map an app or a window
title to a profile; the first matching rule wins.
"""
import os
import re
import time

from PyQt6.QtCore import QObject, QTimer, pyqtClassInfo, pyqtSignal, pyqtSlot
from PyQt6.QtDBus import QDBusAbstractAdaptor, QDBusConnection, QDBusInterface, QDBusServiceWatcher

from . import errors, model

SERVICE = os.environ.get("DECKHAND_DBUS_SERVICE", "org.deckhand.Deckhand")
PATH = "/Windows"
IFACE = "org.deckhand.Windows"
SCRIPT_NAME = "deckhand-windows"
SCRIPT_FILE = os.path.join(os.path.expanduser("~/.local/share/deckhand"), "kwin-windows.js")

KWIN_SCRIPT = f"""// Written by Deckhand. Reports the active window so profiles can switch automatically.
var seen = {{}};
function report(w) {{
  if (!w) return;
  callDBus("{SERVICE}", "{PATH}", "{IFACE}", "Activated",
           String(w.resourceClass || ""), String(w.resourceName || ""), String(w.desktopFileName || ""), String(w.caption || ""));
}}
function hook(w) {{
  if (!w) return;
  report(w);
  var id = String(w.internalId);
  if (!seen[id]) {{
    seen[id] = true;
    w.captionChanged.connect(function () {{ if (workspace.activeWindow === w) report(w); }});
  }}
}}
workspace.windowActivated.connect(hook);
hook(workspace.activeWindow);
"""

DEFAULT_CONFIG = {"enabled": False, "default": "", "rules": []}


def clean_config(cfg):
    out = {"enabled": False, "default": "", "rules": []}
    if not isinstance(cfg, dict):
        return out
    out["enabled"] = bool(cfg.get("enabled", False))
    out["default"] = cfg["default"][:40] if isinstance(cfg.get("default"), str) else ""
    for r in (cfg.get("rules") if isinstance(cfg.get("rules"), list) else [])[:100]:
        if isinstance(r, dict) and r.get("kind") in ("app", "title") and isinstance(r.get("pattern"), str) and r["pattern"].strip() \
                and isinstance(r.get("profile"), str) and r["profile"]:
            out["rules"].append({"kind": r["kind"], "pattern": r["pattern"].strip()[:200], "profile": r["profile"][:40]})
    return out


def _matches(pattern, value):
    pattern, value = pattern.strip(), value or ""
    if not pattern:
        return False
    if pattern.lower().startswith("re:"):
        try:
            return re.search(pattern[3:], value, re.I) is not None
        except re.error:
            return False
    return pattern.lower() in value.lower()


def match_rule(cfg, win):
    """The first rule matching this window dict {cls, name, desktop, title}, or None."""
    for r in cfg.get("rules", []):
        if r["kind"] == "app":
            if any(_matches(r["pattern"], win.get(k, "")) for k in ("cls", "name", "desktop")):
                return r
        elif _matches(r["pattern"], win.get("title", "")):
            return r
    return None


def is_own_window(win):
    return "deckhand" in " ".join(str(win.get(k, "")) for k in ("cls", "name", "desktop")).lower()


def window_label(win):
    app = win.get("cls") or win.get("name") or win.get("desktop") or "unknown"
    return f"{app} - {win['title']}" if win.get("title") else app


@pyqtClassInfo("D-Bus Interface", IFACE)
class _Adaptor(QDBusAbstractAdaptor):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    @pyqtSlot(str, str, str, str)
    def Activated(self, cls, name, desktop, caption):
        self.owner._got(cls, name, desktop, caption)


class WindowWatcher(QObject):
    """Receives window activations from KWin and keeps a short in-memory history."""
    activeChanged = pyqtSignal(dict)
    stateChanged = pyqtSignal()

    def __init__(self, install_script=True):
        super().__init__()
        self.install_script = install_script
        self.active = {}
        self.recent = []          # [{cls, name, desktop, title, t}] newest first, unique by app
        self.supported = True
        self.problem = ""
        self.running = False
        self._adaptor = None
        self._bus = QDBusConnection.sessionBus()
        self._kwin_watch = None

    # ---- lifecycle ------------------------------------------------------------------
    def start(self):
        if self.running:
            return True
        if not self._bus.isConnected():
            return self._fail("No D-Bus session bus is available.")
        if self._adaptor is None:
            self._adaptor = _Adaptor(self)
        if not self._bus.registerService(SERVICE):
            return self._fail("Another Deckhand already owns the window-watching service.")
        if not self._bus.registerObject(PATH, self, QDBusConnection.RegisterOption.ExportAdaptors):
            self._bus.unregisterService(SERVICE)
            return self._fail("Could not publish the window-watching service on D-Bus.")
        self.running = True
        self.problem = ""
        if self.install_script:
            self._kwin_watch = QDBusServiceWatcher("org.kde.KWin", self._bus, QDBusServiceWatcher.WatchModeFlag.WatchForRegistration, self)
            self._kwin_watch.serviceRegistered.connect(lambda _n: QTimer.singleShot(800, self._load_script))
            self._load_script()
        self.stateChanged.emit()
        return True

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.install_script:
            self._call_kwin("unloadScript", SCRIPT_NAME)
        self._bus.unregisterObject(PATH)
        self._bus.unregisterService(SERVICE)
        self.active = {}
        self.stateChanged.emit()

    def _fail(self, msg):
        self.supported = False
        self.problem = msg
        errors.log("window watcher: " + msg)
        self.stateChanged.emit()
        return False

    def _call_kwin(self, method, *args):
        iface = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", self._bus)
        if not iface.isValid():
            return None
        return iface.call(method, *args)

    def _load_script(self):
        if not self.running:
            return
        try:
            os.makedirs(os.path.dirname(SCRIPT_FILE), exist_ok=True)
            with open(SCRIPT_FILE, "w") as f:
                f.write(KWIN_SCRIPT)
        except OSError as e:
            self._fail(errors.explain(e, "Could not write the KWin script"))
            return
        self._call_kwin("unloadScript", SCRIPT_NAME)
        r = self._call_kwin("loadScript", SCRIPT_FILE, SCRIPT_NAME)
        if r is None:
            self._fail("KWin's scripting service is not available: auto-switching needs KDE Plasma.")
            return
        self._call_kwin("start")
        self.supported = True
        self.problem = ""
        self.stateChanged.emit()

    # ---- events -----------------------------------------------------------------------
    def _got(self, cls, name, desktop, caption):
        win = {"cls": cls, "name": name, "desktop": desktop, "title": caption, "t": time.time()}
        self.active = win
        if not is_own_window(win):
            key = (cls or name or desktop).lower()
            self.recent = [w for w in self.recent if (w["cls"] or w["name"] or w["desktop"]).lower() != key]
            self.recent.insert(0, win)
            del self.recent[15:]
        self.activeChanged.emit(win)
        self.stateChanged.emit()
