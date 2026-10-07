"""Approval prompt shown before an agent may run something on the user's computer."""
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from . import icons, mcp_server, motion, style


class ApprovalDialog(QDialog):
    def __init__(self, ap, parent=None):
        super().__init__(parent)
        self.ap = ap
        self.setWindowTitle("Deckhand - agent request")
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._deadline = time.monotonic() + mcp_server.APPROVAL_TIMEOUT_S
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.glyph_pixmap("bot", 28, style.ACCENT, 1.8))
        head.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(f"{ap.client} wants to run an action")
        t.setObjectName("h1")
        col.addWidget(t)
        s = QLabel("This happens on your computer, as you. Only allow it if you expect it.")
        s.setObjectName("muted")
        col.addWidget(s)
        head.addLayout(col, 1)
        lay.addLayout(head)

        box = QPlainTextEdit(ap.summary)
        box.setReadOnly(True)
        box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        box.setStyleSheet("font-family: monospace;")
        box.setMinimumHeight(110)
        box.setMaximumHeight(260)
        lay.addWidget(box)

        self.timer_lbl = QLabel()
        self.timer_lbl.setObjectName("muted")
        lay.addWidget(self.timer_lbl)

        row = QHBoxLayout()
        deny = QPushButton("Deny")
        deny.setDefault(True)
        deny.clicked.connect(lambda: self._decide("deny"))
        once = QPushButton("Allow once")
        once.setObjectName("primary")
        once.clicked.connect(lambda: self._decide("once"))
        sess = QPushButton("Allow for this session")
        sess.setToolTip("Stop asking until this agent disconnects")
        sess.clicked.connect(lambda: self._decide("session"))
        row.addWidget(sess)
        row.addStretch(1)
        row.addWidget(deny)
        row.addWidget(once)
        lay.addLayout(row)

        self._tick = QTimer(self, interval=1000)
        self._tick.timeout.connect(self._update)
        self._tick.start()
        self._update()
        ap.done.connect(self.close)
        motion.fade_in(self, 140)

    def _update(self):
        left = max(0, int(self._deadline - time.monotonic()))
        self.timer_lbl.setText(f"Denied automatically in {left}s")

    def _decide(self, decision):
        self.ap.resolve(decision)
        self.close()

    def closeEvent(self, ev):
        self.ap.resolve("deny", "dismissed")
        super().closeEvent(ev)
