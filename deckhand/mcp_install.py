"""One-step MCP setup for agent clients. Stdlib only (also used by the `deckhand mcp` CLI)."""
import json
import os
import re
import shutil
import subprocess
import sys

NAME = "deckhand"
PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.expanduser("~/.local/bin/deckhand")


def home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)


def launcher_path():
    """The command that starts Deckhand: the per-user launcher, else a system-installed one, else a new per-user launcher."""
    if os.path.isfile(LAUNCHER) and os.access(LAUNCHER, os.X_OK):
        return LAUNCHER
    system = shutil.which("deckhand")
    if system and system.startswith(("/usr/", "/opt/", "/app/")):
        return system
    os.makedirs(os.path.dirname(LAUNCHER), exist_ok=True)
    with open(LAUNCHER, "w") as f:
        f.write(f'#!/bin/sh\ncd "{PKG_ROOT}" && exec python3 -m deckhand "$@"\n')
    os.chmod(LAUNCHER, 0o755)
    return LAUNCHER


def ensure_launcher():
    launcher_path()


def server_command():
    """(command, args, env) that starts the stdio MCP server."""
    return launcher_path(), ["mcp"], {}


def config_snippet():
    cmd, args, env = server_command()
    entry = {"command": cmd, "args": args}
    return json.dumps({"mcpServers": {NAME: entry}}, indent=2)


def _read_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    if not txt.strip():
        return {}
    return json.loads(txt)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and not os.path.exists(path + ".deckhand-backup"):
        shutil.copyfile(path, path + ".deckhand-backup")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


class Client:
    id = ""
    name = ""
    glyph = "bot"

    def detected(self):
        return False

    def installed(self):
        return False

    def install(self):
        raise NotImplementedError

    def uninstall(self):
        raise NotImplementedError

    def manual_hint(self):
        return ""


class JsonClient(Client):
    """Clients configured through one JSON file holding a dict of servers."""

    def __init__(self, cid, name, path, key="mcpServers", entry=None, detect_dirs=(), binary=None):
        self.id, self.name, self.path, self.key = cid, name, path, key
        self._entry = entry or (lambda cmd, args, env: {"command": cmd, "args": args, **({"env": env} if env else {})})
        self.detect_dirs, self.binary = detect_dirs, binary

    def detected(self):
        return bool(self.binary and shutil.which(self.binary)) or os.path.exists(self.path) or any(os.path.isdir(d) for d in self.detect_dirs)

    def installed(self):
        try:
            return NAME in (_read_json(self.path).get(self.key) or {})
        except (ValueError, OSError):
            return False

    def install(self):
        try:
            data = _read_json(self.path)
        except ValueError:
            return False, f"{self.path} is not plain JSON (comments?). Add the snippet manually."
        servers = data.setdefault(self.key, {})
        servers[NAME] = self._entry(*server_command())
        _write_json(self.path, data)
        return True, f"Added to {self.path}"

    def uninstall(self):
        try:
            data = _read_json(self.path)
        except ValueError:
            return False, f"{self.path} is not plain JSON; remove '{NAME}' manually."
        if NAME in (data.get(self.key) or {}):
            del data[self.key][NAME]
            _write_json(self.path, data)
        return True, f"Removed from {self.path}"


class ClaudeCode(Client):
    id, name = "claude-code", "Claude Code"
    path = home(".claude.json")

    def detected(self):
        return bool(shutil.which("claude")) or os.path.exists(self.path)

    def installed(self):
        try:
            return NAME in (_read_json(self.path).get("mcpServers") or {})
        except (ValueError, OSError):
            return False

    def install(self):
        cmd, args, env = server_command()
        exe = shutil.which("claude")
        if exe:
            subprocess.run([exe, "mcp", "remove", NAME, "--scope", "user"], capture_output=True, timeout=30)
            r = subprocess.run([exe, "mcp", "add", "--scope", "user", NAME, "--", cmd, *args], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return True, "Added with `claude mcp add` (user scope)"
            return False, (r.stderr or r.stdout).strip()[:300]
        data = _read_json(self.path)
        data.setdefault("mcpServers", {})[NAME] = {"type": "stdio", "command": cmd, "args": args, "env": env}
        _write_json(self.path, data)
        return True, f"Added to {self.path}"

    def uninstall(self):
        exe = shutil.which("claude")
        if exe:
            subprocess.run([exe, "mcp", "remove", NAME, "--scope", "user"], capture_output=True, timeout=30)
            return True, "Removed with `claude mcp remove`"
        try:
            data = _read_json(self.path)
            data.get("mcpServers", {}).pop(NAME, None)
            _write_json(self.path, data)
        except (ValueError, OSError) as e:
            return False, str(e)
        return True, "Removed"


class Codex(Client):
    id, name = "codex", "Codex"
    path = home(".codex", "config.toml")
    _hdr = re.compile(r"^\[mcp_servers\.(?:deckhand|\"deckhand\")\]\s*$", re.M)

    def detected(self):
        return bool(shutil.which("codex")) or os.path.isdir(home(".codex"))

    def _text(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def installed(self):
        return bool(self._hdr.search(self._text()))

    def _strip(self, txt):
        m = self._hdr.search(txt)
        if not m:
            return txt
        nxt = re.search(r"^\[", txt[m.end():], re.M)
        end = m.end() + nxt.start() if nxt else len(txt)
        return (txt[:m.start()].rstrip("\n") + "\n\n" + txt[end:].lstrip("\n")).strip("\n") + "\n"

    def _write(self, txt):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.exists(self.path) and not os.path.exists(self.path + ".deckhand-backup"):
            shutil.copyfile(self.path, self.path + ".deckhand-backup")
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(txt)
        os.replace(tmp, self.path)

    def install(self):
        cmd, args, _env = server_command()
        txt = self._strip(self._text())
        block = f'\n[mcp_servers.{NAME}]\ncommand = {json.dumps(cmd)}\nargs = {json.dumps(args)}\nstartup_timeout_sec = 30\n'
        self._write(txt.rstrip("\n") + "\n" + block if txt.strip() else block.lstrip("\n"))
        return True, f"Added to {self.path}"

    def uninstall(self):
        if self.installed():
            self._write(self._strip(self._text()))
        return True, f"Removed from {self.path}"


def _opencode_entry(cmd, args, env):
    return {"type": "local", "command": [cmd, *args], "enabled": True}


def _zed_entry(cmd, args, env):
    return {"source": "custom", "command": cmd, "args": args, "env": env}


def _vscode_entry(cmd, args, env):
    return {"type": "stdio", "command": cmd, "args": args}


def all_clients():
    return [
        ClaudeCode(),
        JsonClient("claude-desktop", "Claude Desktop", home(".config", "Claude", "claude_desktop_config.json"), detect_dirs=[home(".config", "Claude")]),
        Codex(),
        JsonClient("gemini", "Gemini CLI", home(".gemini", "settings.json"), detect_dirs=[home(".gemini")], binary="gemini"),
        JsonClient("cursor", "Cursor", home(".cursor", "mcp.json"), detect_dirs=[home(".cursor")], binary="cursor"),
        JsonClient("windsurf", "Windsurf", home(".codeium", "windsurf", "mcp_config.json"), detect_dirs=[home(".codeium", "windsurf")]),
        JsonClient("vscode", "VS Code (Copilot)", home(".config", "Code", "User", "mcp.json"), key="servers", entry=_vscode_entry,
                   detect_dirs=[home(".config", "Code", "User")], binary="code"),
        JsonClient("zed", "Zed", home(".config", "zed", "settings.json"), key="context_servers", entry=_zed_entry,
                   detect_dirs=[home(".config", "zed")], binary="zed"),
        JsonClient("opencode", "opencode", home(".config", "opencode", "opencode.json"), key="mcp", entry=_opencode_entry,
                   detect_dirs=[home(".config", "opencode")], binary="opencode"),
    ]


def get(cid):
    for c in all_clients():
        if c.id == cid:
            return c
    return None


def run_cli(argv):
    """deckhand mcp install|uninstall|status|config [client ...]"""
    cmd = argv[0] if argv else "status"
    names = [a for a in argv[1:] if not a.startswith("--")]
    clients = all_clients()
    if cmd == "config":
        print(config_snippet())
        return 0
    if cmd == "status":
        for c in clients:
            tag = "connected" if c.installed() else ("detected" if c.detected() else "not found")
            print(f"{c.id:15} {c.name:20} {tag}")
        return 0
    if cmd in ("install", "uninstall"):
        if names:
            sel = []
            for n in names:
                c = get(n)
                if not c:
                    print(f"unknown client '{n}'. Known: {', '.join(x.id for x in clients)}", file=sys.stderr)
                    return 2
                sel.append(c)
        else:
            sel = [c for c in clients if (c.detected() if cmd == "install" else c.installed())]
        if not sel:
            print("no supported agent clients detected; use `deckhand mcp config` for a generic snippet")
            return 1
        rc = 0
        for c in sel:
            try:
                ok, msg = c.install() if cmd == "install" else c.uninstall()
            except Exception as e:
                ok, msg = False, str(e)
            print(f"{'ok  ' if ok else 'FAIL'} {c.name}: {msg}")
            rc |= 0 if ok else 1
        return rc
    print("usage: deckhand mcp [install|uninstall|status|config] [client ...]\n       deckhand mcp   (no args: run the stdio MCP server)", file=sys.stderr)
    return 2
