"""Command palette (Ctrl+K): type to jump to a profile, page, folder, action or command."""
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from . import icons, motion, style

ROLE = Qt.ItemDataRole.UserRole


def score(query, text):
    """Fuzzy score: 0 = no match. Prefix and word-start matches rank higher, then in-order subsequences."""
    q, t = query.lower().strip(), text.lower()
    if not q:
        return 1
    if t.startswith(q):
        return 1000 - len(t)
    if q in t:
        return 600 - t.index(q) - len(t) // 4
    i = 0
    for ch in t:
        if i < len(q) and ch == q[i]:
            i += 1
    return 200 - len(t) // 4 if i == len(q) else 0


class CommandPalette(QDialog):
    def __init__(self, items, parent=None):
        """items: [(title, subtitle, glyph, callback)]"""
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.items = items
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setObjectName("palette")
        self.setStyleSheet(f"#palette{{background:{style.PANEL2};border:1px solid {style.BORDER};border-radius:14px;}}")
        self.setFixedWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Type a command, profile, page or action…")
        self.edit.addAction(icons.glyph_icon("search", 16, style.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setFixedHeight(340)
        self.list.itemActivated.connect(self._run)
        self.list.itemClicked.connect(self._run)
        lay.addWidget(self.list)
        hint = QLabel("↑↓ to move  ·  Enter to run  ·  Esc to close")
        hint.setStyleSheet(f"color:{style.MUTED};font-size:11px;")
        lay.addWidget(hint)
        self._filter("")

    def _filter(self, text):
        self.list.clear()
        ranked = []
        for title, sub, glyph, fn in self.items:
            s = max(score(text, title), score(text, sub) // 2 if sub else 0)
            if s:
                ranked.append((s, title, sub, glyph, fn))
        ranked.sort(key=lambda r: -r[0])
        for _s, title, sub, glyph, fn in ranked[:60]:
            it = QListWidgetItem(icons.glyph_icon(glyph, 18, "#cfcfd8"), title + (f"    {sub}" if sub else ""))
            it.setData(ROLE, fn)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run(self, item):
        fn = item.data(ROLE)
        self.close()
        if fn:
            fn()

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress:
            k = ev.key()
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if k == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.list.currentItem():
                self._run(self.list.currentItem())
                return True
        return super().eventFilter(obj, ev)

    def show_over(self, window):
        self.adjustSize()
        g = window.geometry()
        self.move(window.mapToGlobal(g.topLeft()).x() - g.left() + (g.width() - self.width()) // 2, window.mapToGlobal(g.topLeft()).y() - g.top() + 90)
        self.show()
        self.edit.setFocus()
        motion.fade_in(self, 100)
