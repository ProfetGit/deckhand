"""F1 cheat sheet."""
from PyQt6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout

from . import style

SHORTCUTS = [
    ("Ctrl+K", "Command palette: jump to anything"), ("Ctrl+Z / Ctrl+Shift+Z", "Undo / redo"),
    ("Ctrl+C / Ctrl+X / Ctrl+V", "Copy, cut, paste the selected key"), ("Ctrl+D", "Duplicate the selected key"),
    ("Delete", "Clear the selected key"), ("Arrow keys", "Move between keys"), ("Ctrl+1 … 9", "Go to page 1 … 9"),
    ("Drag a key", "Rearrange (Ctrl-drag copies)"), ("Drag a key onto a page tab", "Move it to that page"),
    ("Right-click a key / page tab", "More options"), ("F1", "This list"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(12)
        t = QLabel("Keyboard shortcuts")
        t.setObjectName("h1")
        t.setStyleSheet("font-size:17px;font-weight:700;")
        lay.addWidget(t)
        g = QGridLayout()
        g.setHorizontalSpacing(24)
        g.setVerticalSpacing(8)
        for n, (k, d) in enumerate(SHORTCUTS):
            kl = QLabel(k)
            kl.setStyleSheet(f"background:{style.CARD};border-radius:6px;padding:3px 9px;font-weight:600;")
            g.addWidget(kl, n, 0)
            g.addWidget(QLabel(d), n, 1)
        lay.addLayout(g)
        b = QPushButton("Close")
        b.setObjectName("primary")
        b.clicked.connect(self.accept)
        lay.addWidget(b)
