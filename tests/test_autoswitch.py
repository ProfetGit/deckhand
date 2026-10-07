"""Auto-switch by window: rule matching, engine switching, D-Bus round trip, dialog, agent tools."""
import os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DECKHAND_DBUS_SERVICE"] = f"org.deckhand.test{os.getpid()}"
os.environ["DECKHAND_SOCKET"] = os.path.join(tmp, "mcp.sock")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from deckhand import style, autoswitch as A, model
app.setStyleSheet(style.QSS)
from deckhand.engine import Engine
from PyQt6.QtDBus import QDBusConnection, QDBusInterface

fails = []
def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond: fails.append(name)
def spin(sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        app.processEvents(); time.sleep(0.004)

# ---- pure matching
cfg = A.clean_config({"enabled": True, "default": "d", "rules": [
    {"kind": "app", "pattern": "firefox", "profile": "p1"}, {"kind": "title", "pattern": "re:YouTube|Netflix", "profile": "p2"},
    {"kind": "app", "pattern": "  ", "profile": "x"}, {"kind": "bogus", "pattern": "a", "profile": "p"}, "junk", {"kind": "app", "pattern": "steam", "profile": ""}]})
check("config sanitizing drops bad rules", len(cfg["rules"]) == 2 and cfg["enabled"] and cfg["default"] == "d", cfg)
check("config from garbage is safe", A.clean_config("x") == {"enabled": False, "default": "", "rules": []} and A.clean_config({"rules": "no"})["rules"] == [])
win = lambda cls="", name="", desktop="", title="": {"cls": cls, "name": name, "desktop": desktop, "title": title}
check("app rule matches the window class (case-insensitive)", A.match_rule(cfg, win(cls="Firefox"))["profile"] == "p1")
check("app rule matches the desktop file name", A.match_rule(cfg, win(desktop="org.mozilla.firefox"))["profile"] == "p1")
check("title regex rule matches", A.match_rule(cfg, win(cls="chromium", title="Cats - YouTube"))["profile"] == "p2")
check("no rule -> None", A.match_rule(cfg, win(cls="kate", title="notes")) is None)
check("first matching rule wins", A.match_rule(cfg, win(cls="firefox", title="YouTube"))["profile"] == "p1")
check("invalid regex never matches or crashes", A.match_rule({"rules": [{"kind": "app", "pattern": "re:(", "profile": "p"}]}, win(cls="x")) is None)
check("own window is recognised", A.is_own_window(win(cls="deckhand")) and A.is_own_window(win(desktop="deckhand.desktop")) and not A.is_own_window(win(cls="firefox")))

# ---- engine
e = Engine(); e.windows.install_script = False
games = model.new_profile("Games", 5, 3); web = model.new_profile("Browsing", 5, 3); xl = model.new_profile("XL one", 8, 4)
e.store.profiles.extend([games, web, xl])
base = e.profile
switched = []; e.auto_switched.connect(switched.append)
e.set_auto_switch({"enabled": True, "default": "", "rules": [{"kind": "app", "pattern": "steam", "profile": games["id"]},
                   {"kind": "title", "pattern": "YouTube", "profile": web["id"]}, {"kind": "app", "pattern": "xlapp", "profile": xl["id"]},
                   {"kind": "app", "pattern": "ghost", "profile": "deleted-id"}]})
check("enabling starts the window watcher", e.windows.running)
check("watcher registered on D-Bus", QDBusConnection.sessionBus().interface().isServiceRegistered(A.SERVICE).value())
def focus(**kw):
    e.windows._got(kw.get("cls", ""), kw.get("name", ""), kw.get("desktop", ""), kw.get("title", "")); spin(0.3)
focus(cls="steam", title="Library")
check("focusing a matched app switches the profile", e.profile is games and switched and "Games" in switched[-1] and "steam" in switched[-1], switched)
check("switch is announced with its reason", "steam" in switched[-1])
n = len(switched); focus(cls="steam", title="Store")
check("same profile again does not re-announce", len(switched) == n)
focus(cls="chromium", title="Funny cats - YouTube")
check("title rule switches", e.profile is web)
focus(cls="deckhand", title="Deckhand")
check("Deckhand's own window never switches", e.profile is web)
focus(cls="kate", title="notes")
check("no match and no default keeps the current profile", e.profile is web)
focus(cls="xlapp")
check("profile for a different deck size is ignored", e.profile is web)
focus(cls="ghost")
check("rule pointing at a deleted profile is ignored", e.profile is web)
e.set_auto_switch({**e.settings["auto_switch"], "default": base["id"]})
focus(cls="kate", title="notes"); check("default profile applies when nothing matches", e.profile is base)
for c in ("steam", "kate", "steam", "chromium"):
    e.windows._got(c, "", "", "YouTube" if c == "chromium" else "")
spin(0.4)
check("rapid focus changes settle on the last window (debounced)", e.profile is web)
e.set_auto_switch({**e.settings["auto_switch"], "enabled": False}); spin(0.1)
focus(cls="steam"); check("disabled: nothing switches", e.profile is web)
check("disabling stops the watcher and frees the D-Bus name", not e.windows.running and not QDBusConnection.sessionBus().interface().isServiceRegistered(A.SERVICE).value())
check("rules persisted in settings.json", model.read_json(model.SETTINGS_FILE, {})["auto_switch"]["rules"][0]["pattern"] == "steam")

# ---- the real D-Bus path the KWin script uses
e.set_auto_switch({"enabled": True, "default": "", "rules": [{"kind": "app", "pattern": "steam", "profile": games["id"]}]})
iface = QDBusInterface(A.SERVICE, A.PATH, A.IFACE, QDBusConnection.sessionBus())
check("D-Bus interface is reachable", iface.isValid(), iface.lastError().message())
r = iface.call("Activated", "steam", "steam", "steam.desktop", "Steam")
spin(0.4)
check("D-Bus Activated call updates the active window", e.windows.active.get("cls") == "steam" and e.windows.active["title"] == "Steam", e.windows.active)
check("D-Bus event triggers the switch", e.profile is games)
check("recent apps are tracked (own window excluded)", e.windows.recent and e.windows.recent[0]["cls"] == "steam" and all(w["cls"] != "deckhand" for w in e.windows.recent))
check("KWin script reports through the same service", A.SERVICE in A.KWIN_SCRIPT and "windowActivated" in A.KWIN_SCRIPT and "captionChanged" in A.KWIN_SCRIPT)

# ---- dialog
from deckhand.mainwindow import MainWindow
from deckhand.autoswitch_dialog import AutoSwitchDialog
w = MainWindow(e); d = AutoSwitchDialog(e, w); d.show(); app.processEvents()
check("dialog lists the existing rules", len(d.cfg["rules"]) == 1 and d.rows.count() >= 2)
d._add("app", "firefox"); check("dialog adds a rule and persists it", len(e.settings["auto_switch"]["rules"]) == 2 and e.settings["auto_switch"]["rules"][1]["pattern"] == "firefox")
d._move(1, -1); check("dialog reorders rules", e.settings["auto_switch"]["rules"][0]["pattern"] == "firefox")
d._edit(0, pattern="re:fire.*x"); check("dialog edits a rule", e.settings["auto_switch"]["rules"][0]["pattern"] == "re:fire.*x")
d._delete(0); check("dialog deletes a rule", len(e.settings["auto_switch"]["rules"]) == 1)
d._toggle(False); check("dialog switch disables the feature", e.settings["auto_switch"]["enabled"] is False and not e.windows.running)
d._status(); d.grab()
check("dialog status text builds in every state", True)
w._on_auto_switched("Switched to X"); check("main window shows the switch in the status bar", w.status_lbl.text() == "Switched to X")

# ---- agent tools
from deckhand import agentapi
t = agentapi.Tools(e)
out = t.call("set_auto_switch", {"enabled": True, "default_profile": "Browsing", "rules": [{"app": "steam", "profile": "Games"}, {"title": "re:Docs|Notion", "profile": "Browsing"}]})
check("agent can set rules by profile name", out["enabled"] and len(out["rules"]) == 2 and out["rules"][0]["profile"] == "Games" and out["default_profile"] == "Browsing", out)
check("agent can read the configuration", t.call("get_auto_switch", {})["rules"][1]["kind"] == "title")
for bad in ({"rules": [{"app": "x", "title": "y", "profile": "Games"}]}, {"rules": [{"app": "re:(", "profile": "Games"}]},
            {"rules": [{"app": "x", "profile": "no such"}]}, {"rules": [{"app": "x", "profile": "XL one"}]}, {"rules": [{"app": " ", "profile": "Games"}]}):
    try:
        t.call("set_auto_switch", bad); check(f"agent bad rule rejected {list(bad['rules'][0])}", False)
    except agentapi.ToolError:
        check(f"agent bad rule rejected {list(bad['rules'][0])}", True)
check("agent read tool exposes no window titles", "title" not in str(t.call("get_auto_switch", {}).get("recent_apps", [])) )
e.shutdown()
print("FAILED:", fails if fails else "none"); sys.exit(1 if fails else 0)
