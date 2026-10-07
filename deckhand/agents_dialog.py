"""'Connect agents' dialog: one-click MCP setup, access level and live sessions."""
import time

import threading

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from . import agentapi, icons, mcp_install, style
from .widgets import Segmented, Switch

LEVEL_HELP = {
    "read": "Agents can look at your layout and take screenshots. They cannot change anything.",
    "edit": "Agents can design pages, keys, icons and profiles (everything is undoable). They cannot run actions.",
    "full": "Agents can also press keys and run actions, but only after you approve each request.",
}


def _card():
    f = QFrame()
    f.setObjectName("card")
    return f


class AgentsDialog(QDialog):
    _done = pyqtSignal(object)

    def __init__(self, engine, server, parent=None):
        super().__init__(parent)
        self.engine, self.server = engine, server
        self._busy = False
        self._done.connect(self._finished)
        self.setWindowTitle("Connect AI agents")
        self.resize(640, 760)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(14)

        t = QLabel("Connect AI agents")
        t.setObjectName("h1")
        t.setStyleSheet("font-size:18px;font-weight:700;")
        lay.addWidget(t)
        sub = QLabel("Let Claude, Codex, Gemini and other MCP-capable agents see and design your Stream Deck. "
                     "Connecting takes one click and Deckhand starts on demand.")
        sub.setWordWrap(True)
        sub.setObjectName("muted")
        lay.addWidget(sub)

        # access
        acc = _card()
        al = QVBoxLayout(acc)
        al.setContentsMargins(16, 14, 16, 16)
        al.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(QLabel("Allow agents to connect"), 1)
        self.enable = Switch(engine.settings.get("agent_enabled", True))
        self.enable.toggled.connect(lambda v: engine.set_setting("agent_enabled", v))
        row.addWidget(self.enable)
        al.addLayout(row)
        al.addWidget(self._cap("WHAT AGENTS MAY DO"))
        self.level = Segmented([("read", "Read-only", "", False), ("edit", "Edit layout", "", False), ("full", "Full control", "", False)])
        self.level.set_value(engine.settings.get("agent_access", "edit"))
        self.level.changed.connect(self._level_changed)
        al.addWidget(self.level)
        self.level_help = QLabel()
        self.level_help.setWordWrap(True)
        self.level_help.setObjectName("muted")
        al.addWidget(self.level_help)
        lay.addWidget(acc)

        # clients
        head = QHBoxLayout()
        head.addWidget(self._cap("AGENT APPS ON THIS COMPUTER"), 1)
        self.all_btn = QPushButton("Connect all detected")
        self.all_btn.setObjectName("primary")
        self.all_btn.clicked.connect(self._connect_all)
        head.addWidget(self.all_btn)
        lay.addLayout(head)
        self.clients_box = QVBoxLayout()
        self.clients_box.setSpacing(8)
        lay.addLayout(self.clients_box)
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        self.msg.setObjectName("muted")
        lay.addWidget(self.msg)

        # live sessions
        lay.addWidget(self._cap("CONNECTED NOW"))
        self.sess_box = QVBoxLayout()
        self.sess_box.setSpacing(6)
        lay.addLayout(self.sess_box)

        # manual
        lay.addWidget(self._cap("ANY OTHER AGENT"))
        man = _card()
        ml = QVBoxLayout(man)
        ml.setContentsMargins(16, 14, 16, 16)
        ml.setSpacing(8)
        info = QLabel("Add this as a stdio MCP server in the agent's settings:")
        info.setObjectName("muted")
        ml.addWidget(info)
        cmd, args, _ = mcp_install.server_command()
        self.snippet = QPlainTextEdit(mcp_install.config_snippet())
        self.snippet.setReadOnly(True)
        self.snippet.setStyleSheet("font-family: monospace; font-size: 12px;")
        self.snippet.setFixedHeight(130)
        ml.addWidget(self.snippet)
        r = QHBoxLayout()
        c1 = QPushButton("Copy JSON")
        c1.clicked.connect(lambda: self._copy(mcp_install.config_snippet(), "JSON copied"))
        c2 = QPushButton("Copy command")
        c2.clicked.connect(lambda: self._copy(" ".join([cmd, *args]), "Command copied"))
        r.addWidget(c1)
        r.addWidget(c2)
        r.addStretch(1)
        ml.addLayout(r)
        lay.addWidget(man)
        lay.addStretch(1)

        self._level_changed(self.level_value(), save=False)
        self._fill_clients()
        self._fill_sessions()
        server.sessions_changed.connect(self._fill_sessions)
        self._t = QTimer(self, interval=2000)
        self._t.timeout.connect(self._fill_sessions)
        self._t.start()

    def _cap(self, text):
        l = QLabel(text)
        l.setObjectName("cardTitle")
        return l

    def level_value(self):
        return self.engine.settings.get("agent_access", "edit")

    def _level_changed(self, v, save=True):
        if save:
            self.engine.set_setting("agent_access", v)
        self.level.set_value(v)
        self.level_help.setText(LEVEL_HELP[v])

    def _copy(self, text, note):
        QGuiApplication.clipboard().setText(text)
        self.msg.setText(note)

    def _clear(self, lay):
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _fill_clients(self):
        self._clear(self.clients_box)
        detected = 0
        for c in mcp_install.all_clients():
            inst, det = c.installed(), c.detected()
            if not (inst or det):
                continue
            detected += 1
            card = _card()
            h = QHBoxLayout(card)
            h.setContentsMargins(14, 10, 12, 10)
            ic = QLabel()
            ic.setPixmap(icons.glyph_pixmap("bot", 20, "#cfcfd8"))
            h.addWidget(ic)
            h.addWidget(QLabel(c.name), 1)
            chip = QLabel("Connected" if inst else "Not connected")
            chip.setStyleSheet(f"color:{style.OK if inst else style.MUTED};font-size:12px;")
            h.addWidget(chip)
            b = QPushButton("Remove" if inst else "Connect")
            if not inst:
                b.setObjectName("primary")
            b.clicked.connect(lambda _=False, c=c, inst=inst: self._toggle(c, inst))
            h.addWidget(b)
            self.clients_box.addWidget(card)
        if not detected:
            n = QLabel("No supported agent apps found. Use the snippet below for yours.")
            n.setObjectName("muted")
            self.clients_box.addWidget(n)
        self.all_btn.setEnabled(any(not c.installed() and c.detected() for c in mcp_install.all_clients()))

    def _work(self, jobs):
        """Run installs on a worker thread (some agents' CLIs take seconds) and keep the UI alive."""
        if self._busy:
            return
        self._busy = True
        self.all_btn.setEnabled(False)
        self.msg.setStyleSheet(f"color:{style.MUTED};")
        self.msg.setText("Connecting…" if len(jobs) > 1 or not jobs[0][1] else "Disconnecting…")
        for w in self.findChildren(QPushButton):
            if w.text() in ("Connect", "Remove"):
                w.setEnabled(False)

        def run():
            out = []
            for c, inst in jobs:
                try:
                    ok, msg = c.uninstall() if inst else c.install()
                except Exception as e:
                    ok, msg = False, str(e)
                out.append((ok, f"{c.name}: {msg}" + ("" if not ok or inst else "  Restart it to pick up the new server.")))
            self._done.emit(out)
        threading.Thread(target=run, daemon=True).start()

    def _finished(self, results):
        self._busy = False
        self.msg.setText("\n".join(("" if ok else "FAILED  ") + m for ok, m in results))
        self.msg.setStyleSheet(f"color:{style.MUTED if all(ok for ok, _ in results) else style.DANGER};")
        self._fill_clients()

    def _toggle(self, c, inst):
        self._work([(c, inst)])

    def _connect_all(self):
        jobs = [(c, False) for c in mcp_install.all_clients() if c.detected() and not c.installed()]
        if jobs:
            self._work(jobs)

    def _fill_sessions(self):
        self._clear(self.sess_box)
        live = [s for s in self.server.sessions if s.ready]
        if not live:
            n = QLabel("No agent is connected right now.")
            n.setObjectName("muted")
            self.sess_box.addWidget(n)
            return
        for s in live:
            card = _card()
            h = QHBoxLayout(card)
            h.setContentsMargins(14, 10, 12, 10)
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background:{style.OK};border-radius:4px;")
            h.addWidget(dot)
            ago = int(time.time() - s.last)
            h.addWidget(QLabel(f"{s.client}"), 1)
            info = QLabel(f"{s.calls} calls  ·  active {ago}s ago" + ("  ·  runs allowed" if s.trusted else ""))
            info.setObjectName("muted")
            h.addWidget(info)
            if s.trusted:
                rv = QPushButton("Ask again")
                rv.clicked.connect(lambda _=False, s=s: (setattr(s, "trusted", False), self._fill_sessions()))
                h.addWidget(rv)
            dc = QPushButton("Disconnect")
            dc.clicked.connect(lambda _=False, s=s: s.sock.disconnectFromServer())
            h.addWidget(dc)
            self.sess_box.addWidget(card)
