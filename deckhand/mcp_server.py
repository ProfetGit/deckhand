"""MCP server hosted inside the app. Speaks newline-delimited JSON-RPC over a user-only Unix socket;
`deckhand mcp` (mcp_cli.py) bridges an agent's stdio to it. Runs on the Qt main thread."""
import json
import time
import traceback
import sys

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer

from . import agentapi
from .agentapi import INSTRUCTIONS, LEVELS, TOOLS, Content, ToolError, Tools
from .mcp_cli import socket_path

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
APPROVAL_TIMEOUT_S = 120
MAX_MESSAGE = 24 * 1024 * 1024   # bytes per JSON-RPC line
MAX_SESSIONS = 16


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


class Approval(QObject):
    """A pending request to run something on the user's computer."""
    done = pyqtSignal()

    def __init__(self, session, summary, finish):
        super().__init__()
        self.session, self.summary, self._finish = session, summary, finish
        self.client = session.client
        self.decided = False
        self._timer = QTimer(self, singleShot=True, interval=APPROVAL_TIMEOUT_S * 1000)
        self._timer.timeout.connect(lambda: self.resolve("deny", "timed out"))
        self._timer.start()

    def resolve(self, decision, why=""):
        if self.decided:
            return
        self.decided = True
        self._timer.stop()
        self._finish(decision, why)
        self.done.emit()


class Session(QObject):
    def __init__(self, server, sock):
        super().__init__(server)
        self.server, self.sock = server, sock
        self.buf = bytearray()
        self.client = "Unknown agent"
        self.ready = False
        self.trusted = False
        self.since = time.time()
        self.last = self.since
        self.calls = 0
        self.approvals = []
        sock.readyRead.connect(self._read)
        sock.disconnected.connect(self._closed)

    def info(self):
        return {"client": self.client, "since": self.since, "last": self.last, "calls": self.calls, "trusted": self.trusted}

    def send(self, obj):
        if self.sock.state() == self.sock.LocalSocketState.ConnectedState:
            self.sock.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode() + b"\n")

    def notify(self, method):
        self.send({"jsonrpc": "2.0", "method": method})

    def _closed(self):
        for a in list(self.approvals):
            a.resolve("deny", "agent disconnected")
        self.server._drop(self)

    def _read(self):
        self.buf += bytes(self.sock.readAll())
        if len(self.buf) > MAX_MESSAGE:
            self.buf.clear()
            self.sock.disconnectFromServer()
            return
        while True:
            i = self.buf.find(b"\n")
            if i < 0:
                break
            line, self.buf = bytes(self.buf[:i]).strip(), self.buf[i + 1:]
            if line:
                self._line(line)

    def _line(self, line):
        try:
            msg = json.loads(line)
        except ValueError:
            self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            return
        for m in (msg if isinstance(msg, list) else [msg]):
            self._message(m)

    def _reply(self, id_, result=None, error=None):
        if error is not None:
            self.send({"jsonrpc": "2.0", "id": id_, "error": {"code": error[0], "message": error[1]}})
        else:
            self.send({"jsonrpc": "2.0", "id": id_, "result": result})

    def _message(self, m):
        if not isinstance(m, dict) or "method" not in m:
            return
        method, id_, params = m["method"], m.get("id"), m.get("params") or {}
        self.last = time.time()
        if id_ is None:
            return
        try:
            if method == "tools/call":
                self._tools_call(id_, params)
                return
            self._reply(id_, self._dispatch(method, params))
        except RpcError as e:
            self._reply(id_, error=(e.code, e.message))
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self._reply(id_, error=(-32603, "internal error"))

    def _dispatch(self, method, p):
        e = self.server
        if method == "initialize":
            if not e.engine.settings.get("agent_enabled", True):
                raise RpcError(-32000, "Agent access is turned off in Deckhand (Connect agents). Ask the user to enable it.")
            ci = p.get("clientInfo") or {}
            self.client = (ci.get("title") or ci.get("name") or "Unknown agent") + (f" {ci['version']}" if ci.get("version") else "")
            want = p.get("protocolVersion")
            self.ready = True
            e.sessions_changed.emit()
            return {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": True}, "resources": {}},
                    "serverInfo": {"name": "deckhand", "title": "Deckhand (Stream Deck)", "version": agentapi.VERSION},
                    "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if not self.ready:
            raise RpcError(-32002, "not initialized")
        if method == "tools/list":
            return {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"],
                               "annotations": t["annotations"]} for t in e.tools.visible()]}
        if method == "resources/list":
            return {"resources": [
                {"uri": "deckhand://status", "name": "Deck status", "mimeType": "application/json"},
                {"uri": "deckhand://actions", "name": "Action catalog", "mimeType": "application/json"},
                {"uri": "deckhand://layout", "name": "Current page layout", "mimeType": "application/json"}]}
        if method == "resources/templates/list":
            return {"resourceTemplates": []}
        if method == "resources/read":
            uri = p.get("uri")
            tool = {"deckhand://status": "get_status", "deckhand://actions": "list_actions", "deckhand://layout": "get_layout"}.get(uri)
            if not tool:
                raise RpcError(-32002, f"unknown resource {uri}")
            data = e.tools.call(tool, {})
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(data, ensure_ascii=False)}]}
        raise RpcError(-32601, f"method not found: {method}")

    # -- tools/call ----------------------------------------------------------------------
    def _tools_call(self, id_, p):
        if not self.ready:
            raise RpcError(-32002, "not initialized")
        name, args = p.get("name"), p.get("arguments") or {}
        e = self.server
        if not e.engine.settings.get("agent_enabled", True):
            self._reply(id_, self._result_error("Agent access is turned off in Deckhand."))
            return
        tool = TOOLS.get(name)
        try:
            if tool and tool["level"] == "full" and LEVELS[tool["level"]] <= LEVELS.get(e.tools.level, 0):
                summary = e.tools.prepare(name, args)
                if not self.trusted:
                    ap = Approval(self, summary, lambda d, why="": self._decided(id_, name, args, d, why))
                    self.approvals.append(ap)
                    ap.done.connect(lambda ap=ap: self.approvals.remove(ap) if ap in self.approvals else None)
                    e.request_approval(ap)
                    return
        except ToolError as ex:
            self._reply(id_, self._result_error(str(ex)))
            return
        self._execute(id_, name, args)

    def _decided(self, id_, name, args, decision, why):
        if decision == "deny":
            self._reply(id_, self._result_error("The user denied this request" + (f" ({why})." if why else ".") +
                                               " Do not retry; ask the user what they want instead."))
            return
        if decision == "session":
            self.trusted = True
            self.server.sessions_changed.emit()
        self._execute(id_, name, args)

    def _execute(self, id_, name, args):
        self.calls += 1
        try:
            out = self.server.tools.call(name, args)
            content = out if isinstance(out, Content) else [{"type": "text", "text": out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, separators=(",", ":"))}]
            res = {"content": content, "isError": False}
            if TOOLS.get(name, {}).get("level") != "read":
                self.server.activity.emit(f"{self.client}: {name.replace('_', ' ')}")
        except ToolError as ex:
            res = self._result_error(str(ex))
        except Exception as ex:
            traceback.print_exc(file=sys.stderr)
            res = self._result_error(f"internal error: {ex.__class__.__name__}: {ex}")
        self.server.sessions_changed.emit()
        self._reply(id_, res)

    @staticmethod
    def _result_error(text):
        return {"content": [{"type": "text", "text": text}], "isError": True}


class McpServer(QObject):
    sessions_changed = pyqtSignal()
    activity = pyqtSignal(str)
    approval_requested = pyqtSignal(object)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.tools = Tools(engine)
        self.sessions = []
        self.auto_decision = None  # tests only
        self._level = self.tools.level
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        engine.settings_changed.connect(self._settings_changed)

    def start(self):
        path = socket_path()
        QLocalServer.removeServer(path)
        if not self.server.listen(path):
            print(f"deckhand: MCP socket unavailable: {self.server.errorString()}", file=sys.stderr)
            return False
        return True

    def stop(self):
        for s in list(self.sessions):
            s.sock.disconnectFromServer()
        self.server.close()

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            if len(self.sessions) >= MAX_SESSIONS:
                sock.disconnectFromServer()
                continue
            self.sessions.append(Session(self, sock))

    def _drop(self, s):
        if s in self.sessions:
            self.sessions.remove(s)
        self.sessions_changed.emit()

    def disconnect_all(self):
        for s in list(self.sessions):
            s.sock.disconnectFromServer()

    def request_approval(self, ap):
        if self.auto_decision:
            QTimer.singleShot(0, lambda: ap.resolve(self.auto_decision))
            return
        self.approval_requested.emit(ap)

    def _settings_changed(self):
        lv = self.tools.level
        if lv != self._level:
            self._level = lv
            for s in self.sessions:
                if s.ready:
                    s.notify("notifications/tools/list_changed")
        if not self.engine.settings.get("agent_enabled", True):
            self.disconnect_all()
        self.sessions_changed.emit()

    def revoke_trust(self):
        for s in self.sessions:
            s.trusted = False
        self.sessions_changed.emit()
