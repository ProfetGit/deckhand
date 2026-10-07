"""MCP end-to-end test: real stdio shim -> socket -> in-app server -> engine. Throwaway config dir, no device."""
import json, os, subprocess, sys, tempfile, threading, time
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["QT_QPA_PLATFORM"] = "offscreen"
SOCK = os.path.join(tmp, "mcp.sock")
os.environ["DECKHAND_SOCKET"] = SOCK
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication(sys.argv)
from deckhand import style, model
app.setStyleSheet(style.QSS)
from deckhand.engine import Engine
from deckhand.mcp_server import McpServer

e = Engine()
srv = McpServer(e)
assert srv.start()
fails = []
def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond: fails.append(name)

class Client:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, "-m", "deckhand", "mcp"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=os.environ.copy())
        self.n = 0
    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n").encode()); self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line: raise RuntimeError("shim closed: " + self.p.stderr.read().decode())
            m = json.loads(line)
            if m.get("id") == self.n: return m
    def notify(self, method):
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method}) + "\n").encode()); self.p.stdin.flush()
    def tool(self, _name, **args):
        r = self.rpc("tools/call", {"name": _name, "arguments": args})
        res = r["result"]; txt = res["content"][0].get("text", "")
        data = None
        if not res["isError"] and res["content"][0]["type"] == "text":
            try: data = json.loads(txt)
            except ValueError: data = txt
        return res["isError"], (data if data is not None else txt), res
    def close(self):
        self.p.stdin.close(); self.p.wait(5)

def scenario():
    try:
        c = Client()
        r = c.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test-agent", "version": "1"}})
        check("initialize", r["result"]["serverInfo"]["name"] == "deckhand" and r["result"]["protocolVersion"] == "2025-06-18")
        c.notify("notifications/initialized")
        names = {t["name"] for t in c.rpc("tools/list")["result"]["tools"]}
        check("edit level hides press_key/run_action", "set_keys" in names and "press_key" not in names and "run_action" not in names, names)
        err, d, _ = c.tool("get_status")
        check("get_status", not err and d["grid"]["cols"] == 5 and d["agent_access"] == "edit", d)
        err, d, _ = c.tool("list_actions")
        check("list_actions", not err and any(a["type"] == "hotkey" for a in d))
        # build a page: new profile, folder, keys
        err, d, _ = c.tool("create_profile", name="Agent test")
        check("create_profile switches", not err and e.profile["name"] == "Agent test", d)
        err, d, _ = c.tool("set_keys", keys=[
            {"index": 0, "action": {"type": "hotkey", "params": {"hotkey": "ctrl+shift+m"}}, "title": "Mute", "icon": {"glyph": "mic-off"}, "background": "#102030"},
            {"row": 1, "col": 2, "action": {"type": "website", "params": {"url": "https://example.com"}}, "icon": "globe"},
            {"index": 2, "action": {"type": "folder", "params": {"name": "Tools"}}},
            {"index": 3, "action": {"type": "multi", "params": {"steps": [{"type": "hotkey", "params": {"hotkey": "ctrl+c"}}, {"type": "delay", "params": {"ms": 100}}, {"type": "lock"}]}}},
        ])
        check("set_keys ok", not err and d["updated"] == [0, 1, 2, 3] and "2" in d["created_folders"], d)
        fid = d["created_folders"]["2"] if not err else None
        hk = e.get_key(0)["action"]["params"]["hotkey"]
        check("hotkey parsed to evdev", hk["code"] == 50 and hk["mods"] == ["ctrl", "shift"], hk)
        err, d, _ = c.tool("set_keys", folder=fid, keys=[{"index": 1, "action": {"type": "playpause"}}, {"index": 2, "title": "Hi"}])
        check("fill folder", not err and e.profile["folders"][fid]["keys"]["1"]["action"]["type"] == "playpause", d)
        check("view not moved by edits", not e.in_folder)
        err, d, _ = c.tool("set_key", folder=fid, index=0, title="x")
        check("folder key 0 protected", err)
        err, d, _ = c.tool("get_layout")
        check("get_layout", not err and len(d["keys"]) == 4 and d["folders"][0]["id"] == fid and d["keys"][0]["action"]["params"]["hotkey"] == "ctrl+shift+m", d)
        err, d, res = c.tool("screenshot")
        check("screenshot returns png", not err and res["content"][0]["type"] == "image" and len(res["content"][0]["data"]) > 500)
        err, d, _ = c.tool("list_audio_devices")
        check("list_audio_devices", not err and "microphones" in d, d)
        if not err and d["microphones"]:
            dev = d["microphones"][0]
            err, d2, _ = c.tool("set_key", index=7, action={"type": "micmute", "params": {"device": dev["description"][:12]}})
            ok = not err and e.get_key(7)["action"]["params"]["device"].startswith(("alsa_", "bluez_", "usb"))
            check("mic device resolved from description", ok or "ambiguous" in str(d2), d2)
        err, d2, _ = c.tool("set_key", index=7, action={"type": "micmute", "params": {"device": "no such mic"}})
        check("unknown audio device rejected", err)
        err, d2, _ = c.tool("set_key", index=7, action={"type": "playpause"}, alt={"icon": {"glyph": "pause"}, "background": "#102030"})
        check("alt via MCP", not err and e.get_key(7)["alt"]["bg"] == "#102030", d2)
        e.clear_key(7)
        import base64 as _b64
        from PyQt6.QtGui import QImage as _QI
        _im = _QI(64, 64, _QI.Format.Format_RGB32); _im.fill(0xff2060c0)
        _p = os.path.join(tmp, "w.png"); _im.save(_p); _b = _b64.b64encode(open(_p, "rb").read()).decode()
        err, d, _ = c.tool("set_wallpaper", image={"image_base64": _b}, dim=20, fit="stretch")
        check("set_wallpaper via MCP", not err and e.profile["wallpaper"]["fit"] == "stretch" and e.profile["wallpaper"]["dim"] == 20, d)
        err, d, _ = c.tool("set_wallpaper", dim=500)
        check("set_wallpaper validates", err)
        err, d, _ = c.tool("get_layout"); check("get_layout reports wallpaper", not err and d["wallpaper"]["fit"] == "stretch")
        err, d, _ = c.tool("set_wallpaper", remove=True); check("remove wallpaper via MCP", not err and "wallpaper" not in e.profile)
        # one undo step reverts a whole set_keys
        n_before = len(e._undo)
        c.tool("set_keys", keys=[{"index": 5, "title": "A"}, {"index": 6, "title": "B"}])
        check("set_keys is one undo step", len(e._undo) == n_before + 1)
        e.undo()
        check("undo reverts batch", e.get_key(5) is None and e.get_key(6) is None)
        # validation errors
        for label, args in [("bad action", dict(index=1, action={"type": "hotkeyy"})), ("bad hotkey", dict(index=1, action={"type": "hotkey", "params": {"hotkey": "ctrl+blorp"}})),
                            ("bad param", dict(index=1, action={"type": "website", "params": {"nope": 1}})), ("bad color", dict(index=1, background="zzz")),
                            ("bad glyph", dict(index=1, icon={"glyph": "nonexistent"})), ("bad index", dict(index=99, title="x"))]:
            err, d, _ = c.tool("set_key", **args)
            check("rejects " + label, err and isinstance(d, str), d)
        err, d, _ = c.tool("set_key", index=1, bogus=1)
        check("rejects unknown argument", err)
        # other profile untouched view
        err, d, _ = c.tool("list_profiles")
        other = [p for p in d if not p["active"]][0]["id"]
        before = e.profile["id"]
        err, d, _ = c.tool("set_key", profile=other, page=1, index=14, title="far")
        check("edit non-active profile", not err and e.store.get(other)["pages"][0]["keys"]["14"]["title"] == "far" and e.profile["id"] == before, d)
        err, d, _ = c.tool("add_page", name="Second")
        check("add_page", not err and len(e.profile["pages"]) == 2 and e.loc["page"] == 0, d)
        err, d, _ = c.tool("set_settings", brightness=33)
        check("set_settings", not err and e.settings["brightness"] == 33)
        err, d, _ = c.tool("delete_profile", profile="Agent test", confirm=False)
        check("delete requires confirm", err)
        # access levels
        e.settings["agent_access"] = "read"; e.settings_changed.emit()
        err, d, _ = c.tool("set_key", index=1, title="x")
        check("read level blocks edits", err and "access level" in d, d)
        err, d, _ = c.tool("get_layout")
        check("read level allows reads", not err)
        e.settings["agent_access"] = "full"; e.settings_changed.emit()
        # approvals
        out = os.path.join(tmp, "ran.txt")
        act = {"type": "command", "params": {"cmd": f"echo ran > {out}"}}
        srv.auto_decision = "deny"
        err, d, _ = c.tool("run_action", action=act)
        time.sleep(0.4)
        check("denied run does not execute", err and "denied" in d and not os.path.exists(out), d)
        srv.auto_decision = "once"
        err, d, _ = c.tool("run_action", action=act)
        time.sleep(0.6)
        check("approved run executes", not err and os.path.exists(out), d)
        os.remove(out)
        srv.auto_decision = "session"
        c.tool("run_action", action=act); time.sleep(0.5); os.remove(out)
        srv.auto_decision = "deny"
        err, d, _ = c.tool("run_action", action=act)
        time.sleep(0.5)
        check("session approval skips prompt", not err and os.path.exists(out), d)
        e.container["keys"]["4"] = {**model.new_key(), "action": act}
        err, d, _ = c.tool("press_key", index=4)
        time.sleep(0.5)
        check("press_key obeys approval (trusted session)", not err and os.path.exists(out), d)
        c.close()
        # disabled
        e.settings["agent_enabled"] = False; e.settings_changed.emit()
        c2 = Client()
        r = c2.rpc("initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "x"}})
        check("disabled refuses initialize", "error" in r, r)
        c2.close()
    except Exception as ex:
        import traceback; traceback.print_exc()
        check("scenario crashed", False, str(ex))
    finally:
        done.append(1)

done = []
threading.Thread(target=scenario, daemon=True).start()
t = QTimer(); t.timeout.connect(lambda: app.quit() if done else None); t.start(50)
QTimer.singleShot(60000, app.quit)
app.exec()
srv.stop()
print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
