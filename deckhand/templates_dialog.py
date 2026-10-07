"""Gallery of ready-made pages."""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from . import icons, render, style, templates


def preview(engine, tid, px=44):
    cols, rows = engine.cols, engine.rows
    page = templates.build_page(tid, cols, rows)
    gap = 5
    W, H = cols * px + (cols - 1) * gap + 16, rows * px + (rows - 1) * gap + 16
    pm = QPixmap(W * 2, H * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(QColor("#1a1a1d"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for i in range(cols * rows):
        x, y = 8 + (i % cols) * (px + gap), 8 + (i // cols) * (px + gap)
        img = render.render_key(page["keys"].get(str(i)), px * 2)
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(2)
        p.drawPixmap(x, y, pix)
    p.end()
    return pm


class TemplatesDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.chosen = None
        self.setWindowTitle("Add a page from a template")
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        t = QLabel("Start from a template")
        t.setObjectName("h1")
        t.setStyleSheet("font-size:17px;font-weight:700;")
        lay.addWidget(t)
        sub = QLabel("Adds a new page with ready-made keys. Everything can be changed afterwards, and Ctrl+Z removes the page again.")
        sub.setWordWrap(True)
        sub.setObjectName("muted")
        lay.addWidget(sub)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setSpacing(12)
        for n, (tid, name, desc, glyph) in enumerate(templates.names()):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 14)
            head = QHBoxLayout()
            ic = QLabel()
            ic.setPixmap(icons.glyph_pixmap(glyph, 18, "#cfcfd8"))
            head.addWidget(ic)
            nm = QLabel(name)
            nm.setObjectName("h1")
            head.addWidget(nm, 1)
            cl.addLayout(head)
            pv = QLabel()
            pv.setPixmap(preview(engine, tid))
            cl.addWidget(pv, 0, Qt.AlignmentFlag.AlignHCenter)
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setObjectName("muted")
            cl.addWidget(d)
            b = QPushButton("Add this page")
            b.setObjectName("primary")
            b.clicked.connect(lambda _=False, tid=tid: self._pick(tid))
            cl.addWidget(b)
            grid.addWidget(card, n // 2, n % 2)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Cancel")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)

    def _pick(self, tid):
        self.chosen = tid
        self.accept()
