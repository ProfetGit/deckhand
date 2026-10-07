"""Left panel: searchable, draggable action list."""
from PyQt6.QtCore import QMimeData, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QFont, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from . import actions, icons, render, style
from .widgets import MIME_ACTION

ROLE = Qt.ItemDataRole.UserRole


class ActionTree(QTreeWidget):
    def startDrag(self, supported):
        it = self.currentItem()
        aid = it.data(0, ROLE) if it else None
        if not aid:
            return
        d = QDrag(self)
        m = QMimeData()
        m.setData(MIME_ACTION, aid.encode())
        d.setMimeData(m)
        if aid.startswith("app:"):
            ap = icons.find_app(aid[4:])
            key = {"action": actions.default_action("app"), "bg": "#000000"}
            if ap and ap["icon"]:
                key["icon"] = {"kind": "file" if ap["icon"].startswith("/") else "theme", "value": ap["icon"]}
        else:
            key = {"action": actions.default_action(aid), "bg": "#000000"}
        img = render.render_key(key, 144)
        px = QPixmap.fromImage(img)
        px.setDevicePixelRatio(2)
        d.setPixmap(px)
        d.setHotSpot(QPoint(36, 36))
        d.exec(Qt.DropAction.CopyAction)


class Sidebar(QWidget):
    activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setContentsMargins(16, 0, 16, 0)
        t = QLabel("Actions")
        t.setObjectName("h1")
        head.addWidget(t)
        lay.addLayout(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search actions")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.glyph_icon("search", 16, style.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        w = QWidget()
        wl = QHBoxLayout(w)
        wl.setContentsMargins(12, 0, 12, 0)
        wl.addWidget(self.search)
        lay.addWidget(w)

        self.tree = ActionTree()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(0)
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(self._double)
        lay.addWidget(self.tree, 1)

        hint = QLabel("Drag an action onto a key, or double-click to add it to the selected key.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setContentsMargins(16, 6, 16, 12)
        hint.setStyleSheet(f"font-size:11px;color:{style.MUTED};")
        lay.addWidget(hint)
        self._build()

    def _build(self):
        self.tree.clear()
        for cat, ids in actions.CATEGORIES:
            top = QTreeWidgetItem([cat.upper()])
            f = QFont()
            f.setPixelSize(11)
            f.setBold(True)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
            top.setFont(0, f)
            top.setForeground(0, QColor(style.MUTED))
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            top.setSizeHint(0, QSize(0, 32))
            self.tree.addTopLevelItem(top)
            for aid in ids:
                a = actions.ACTIONS[aid]
                it = QTreeWidgetItem([a["name"]])
                it.setIcon(0, icons.glyph_icon(a["glyph"], 20, "#cfcfd8"))
                it.setData(0, ROLE, aid)
                it.setToolTip(0, a["desc"])
                it.setSizeHint(0, QSize(0, 36))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                top.addChild(it)
            top.setExpanded(True)
        self.apps_top = QTreeWidgetItem(["APPS"])
        f2 = QFont()
        f2.setPixelSize(11)
        f2.setBold(True)
        f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        self.apps_top.setFont(0, f2)
        self.apps_top.setForeground(0, QColor(style.MUTED))
        self.apps_top.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.apps_top.setSizeHint(0, QSize(0, 32))
        self.tree.insertTopLevelItem(0, self.apps_top)
        self.apps_top.setHidden(True)

    def _fill_apps(self, q):
        self.apps_top.takeChildren()
        hits = []
        if len(q) >= 2:
            hits = [a for a in icons.installed_apps() if q in a["name"].lower()][:8]
        for a in hits:
            it = QTreeWidgetItem([f"Open {a['name']}"])
            ic = icons.app_icon(a["icon"])
            it.setIcon(0, ic if not ic.isNull() else icons.glyph_icon("grid", 20, "#cfcfd8"))
            it.setData(0, ROLE, "app:" + a["id"])
            it.setToolTip(0, f"Add a key that launches {a['name']}")
            it.setSizeHint(0, QSize(0, 36))
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            self.apps_top.addChild(it)
        self.apps_top.setHidden(not hits)
        self.apps_top.setExpanded(True)

    def _clicked(self, item, _col):
        if not item.data(0, ROLE):
            item.setExpanded(not item.isExpanded())

    def _double(self, item, _col):
        aid = item.data(0, ROLE)
        if aid:
            self.activated.emit(aid)

    def _filter(self, text):
        q = text.strip().lower()
        self._fill_apps(q)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top is self.apps_top:
                continue
            vis = 0
            for j in range(top.childCount()):
                c = top.child(j)
                a = actions.ACTIONS[c.data(0, ROLE)]
                hit = not q or q in a["name"].lower() or q in a["desc"].lower()
                c.setHidden(not hit)
                vis += hit
            top.setHidden(vis == 0)
            if q:
                top.setExpanded(True)
