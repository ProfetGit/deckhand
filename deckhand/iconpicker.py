"""Icon picker dialog: built-in glyphs, installed-app icons, system icon theme, or an image file."""
import os
import shutil

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from . import icons, model, style

ROLE = Qt.ItemDataRole.UserRole
MAX_SHOWN = 600


def import_image(path):
    """Copy an image into the config icon dir so the key keeps working if the original moves."""
    os.makedirs(model.ICON_DIR, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(path))
    dest = os.path.join(model.ICON_DIR, f"{base}-{model.new_id()}{ext.lower()}")
    shutil.copyfile(path, dest)
    return {"kind": "file", "value": dest}


def _grid():
    lw = QListWidget()
    lw.setViewMode(QListWidget.ViewMode.IconMode)
    lw.setResizeMode(QListWidget.ResizeMode.Adjust)
    lw.setMovement(QListWidget.Movement.Static)
    lw.setIconSize(QSize(34, 34))
    lw.setGridSize(QSize(92, 78))
    lw.setWordWrap(True)
    lw.setUniformItemSizes(True)
    lw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    lw.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    lw.setSpacing(2)
    return lw


class IconPicker(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose an icon")
        self.resize(700, 540)
        self.result_spec = None
        self._sys_names = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search icons")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.glyph_icon("search", 16, style.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._fill_current)
        lay.addWidget(self.search)

        self.tabs = QTabWidget()
        self.glyphs, self.apps, self.system = _grid(), _grid(), _grid()
        for g in (self.glyphs, self.apps, self.system):
            g.itemDoubleClicked.connect(lambda *_: self.accept())
            g.itemSelectionChanged.connect(self._sel)
        self.tabs.addTab(self.glyphs, "Glyphs")
        self.tabs.addTab(self.apps, "Apps")
        self.tabs.addTab(self.system, "System")
        self.tabs.currentChanged.connect(lambda _: self._fill_current())
        lay.addWidget(self.tabs, 1)

        row = QHBoxLayout()
        self.file_btn = QPushButton("Use an image file…")
        self.file_btn.setIcon(icons.glyph_icon("image", 16, "#d0d0d8"))
        self.file_btn.clicked.connect(self._file)
        row.addWidget(self.file_btn)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Use icon")
        self.ok.setObjectName("primary")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self._fill_current()

    def _fill_current(self, *_):
        q = self.search.text().strip().lower()
        i = self.tabs.currentIndex()
        if i == 0:
            self.glyphs.clear()
            for n in icons.GLYPH_NAMES:
                if q in n:
                    it = QListWidgetItem(icons.glyph_icon(n, 34, "#ffffff"), n)
                    it.setData(ROLE, {"kind": "glyph", "value": n})
                    self.glyphs.addItem(it)
        elif i == 1:
            self.apps.clear()
            for a in icons.installed_apps():
                if a["icon"] and (q in a["name"].lower()):
                    ic = icons.app_icon(a["icon"])
                    if ic.isNull():
                        continue
                    it = QListWidgetItem(ic, a["name"])
                    it.setToolTip(a["name"])
                    kind = "file" if os.path.isabs(a["icon"]) else "theme"
                    it.setData(ROLE, {"kind": kind, "value": a["icon"]})
                    self.apps.addItem(it)
        else:
            self.system.clear()
            if not icons.theme_names_ready() and icons._theme_started:
                ph = QListWidgetItem("Loading system icons…")
                ph.setFlags(Qt.ItemFlag.NoItemFlags)
                self.system.addItem(ph)
                QTimer.singleShot(250, self._fill_current)
                return
            if self._sys_names is None:
                self._sys_names = icons.theme_icon_names()
            n = 0
            for name in self._sys_names:
                if q in name:
                    ic = QIcon.fromTheme(name)
                    if ic.isNull():
                        continue
                    it = QListWidgetItem(ic, name)
                    it.setToolTip(name)
                    it.setData(ROLE, {"kind": "theme", "value": name})
                    self.system.addItem(it)
                    n += 1
                    if n >= MAX_SHOWN:
                        break
        self._sel()

    def _sel(self):
        g = self.tabs.currentWidget()
        self.ok.setEnabled(bool(g.selectedItems()))

    def _file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose an image", os.path.expanduser("~/Pictures"),
                                              "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg)")
        if path:
            try:
                if icons.file_image(path) is None:
                    raise ValueError("that file is not an image Deckhand can read")
                self.result_spec = import_image(path)
            except (OSError, ValueError) as e:
                from . import errors
                QMessageBox.warning(self, "Could not use that image", errors.explain(e))
                return
            super().accept()

    def accept(self):
        g = self.tabs.currentWidget()
        items = g.selectedItems()
        if items:
            self.result_spec = items[0].data(ROLE)
            super().accept()


def pick_icon(parent):
    d = IconPicker(parent)
    if d.exec() == QDialog.DialogCode.Accepted:
        return d.result_spec
    return None
