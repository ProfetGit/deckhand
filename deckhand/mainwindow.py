"""Main editor window."""
import copy
import json
import os

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu,
                             QMessageBox, QPushButton, QSlider, QSplitter, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)

from . import actions, errors, icons, model, style, trouble
from .iconpicker import import_image
from .inspector import Inspector
from .prefs import PrefsDialog
from .sidebar import Sidebar
from . import motion
from .statusui import HARD_TIMEOUT_S, NONE_GRACE_S, LoadingOverlay, StatusBanner, TroubleDialog
from .widgets import DeckView, StatusDot, Toast, fit_combo, icon_btn

ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")


def app_icon():
    return QIcon(os.path.join(ASSET_DIR, "deckhand.svg"))


class PageButton(QPushButton):
    """A page tab. Drop a key on it to move the key there; hovering a drag over it opens the page."""
    keyDropped = pyqtSignal(int)
    hovered = pyqtSignal()

    def __init__(self, text):
        super().__init__(text)
        self.setAcceptDrops(True)
        self._t = QTimer(self, singleShot=True, interval=550)
        self._t.timeout.connect(self.hovered.emit)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat("application/x-deckhand-key"):
            ev.acceptProposedAction()
            self._t.start()

    def dragLeaveEvent(self, ev):
        self._t.stop()

    def dropEvent(self, ev):
        self._t.stop()
        try:
            raw = bytes(ev.mimeData().data("application/x-deckhand-key")).decode()
            idx = int(json.loads(raw)["idx"]) if not raw.isdigit() else int(raw)
        except (ValueError, KeyError, TypeError):
            return
        ev.acceptProposedAction()
        self.keyDropped.emit(idx)


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self._clip = None
        self.quitting = False
        self.setWindowTitle("Deckhand")
        self.setWindowIcon(app_icon())
        self.resize(1260, 920)
        self.setMinimumSize(980, 700)

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._topbar())

        body = QHBoxLayout()
        body.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.setFixedWidth(272)
        body.addWidget(self.sidebar)
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background:{style.BORDER};")
        body.addWidget(sep)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.banner = StatusBanner(engine, self.open_trouble)
        cl.addWidget(self.banner)

        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(1)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.crumbs = QHBoxLayout()
        self.crumbs.setContentsMargins(18, 12, 18, 0)
        self.crumbs.setSpacing(2)
        tl.addLayout(self.crumbs)
        self.deck = DeckView(engine)
        tl.addWidget(self.deck, 1)
        self.hint = QLabel("Drag an action from the list onto a key to get started.")
        self.hint.setObjectName("muted")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(self.hint)
        self.pages = QHBoxLayout()
        self.pages.setContentsMargins(18, 6, 18, 14)
        self.pages.setSpacing(6)
        tl.addLayout(self.pages)
        self.split.addWidget(top)

        self.toast = Toast(self)
        self.inspector = Inspector(engine, self.toast)
        self.split.addWidget(self.inspector)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        self.split.setSizes([470, 390])
        cl.addWidget(self.split, 1)
        body.addWidget(center, 1)
        v.addLayout(body, 1)
        v.addWidget(self._statusbar())

        self._wire()
        self._shortcuts()
        self._restore_layout()
        self._tray()
        self.refresh()
        self._on_status(engine.conn_info)
        self._start_loading()
        self.deck.set_selected(0)
        self.inspector.set_key(0)

    # ---- construction --------------------------------------------------------------------
    def _topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(54)
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 0, 14, 0)
        h.setSpacing(10)

        self.chip = QPushButton()
        self.chip.setObjectName("flat")
        self.chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chip.setIcon(icons.glyph_icon("usb", 18, "#d0d0d8"))
        self.chip.setStyleSheet(f"QPushButton{{background:{style.CARD};border:1px solid {style.BORDER};border-radius:8px;padding:6px 12px 6px 10px;}}"
                                f"QPushButton:hover{{background:{style.CARD_HOVER};}}")
        self.chip.clicked.connect(self._chip_menu)
        h.addWidget(self.chip)

        self.profile_combo = fit_combo(QComboBox())
        self.profile_combo.setMinimumWidth(190)
        self.profile_combo.activated.connect(lambda i: self.engine.switch_profile(self.profile_combo.itemData(i)))
        h.addWidget(self.profile_combo)

        pm = QToolButton()
        pm.setIcon(icons.glyph_icon("more", 18, "#c9c9d2"))
        pm.setToolTip("Profile options")
        pm.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(pm)
        menu.addAction("Deck wallpaper…", self.open_wallpaper)
        menu.addAction("Auto-switch by window…", self.open_autoswitch)
        menu.addSeparator()
        menu.addAction("New profile…", self.new_profile)
        menu.addAction("Duplicate", self.engine.duplicate_profile)
        menu.addAction("Rename…", self.rename_profile)
        menu.addSeparator()
        menu.addAction("Export…", self.export_profile)
        menu.addAction("Import…", self.import_profile)
        menu.addSeparator()
        menu.addAction("Delete profile", self.delete_profile)
        pm.setMenu(menu)
        wp = icon_btn("image", "Deck wallpaper", 18)
        wp.clicked.connect(self.open_wallpaper)
        h.addWidget(wp)
        h.addWidget(pm)
        h.addStretch(1)

        self.undo_btn = icon_btn("undo", "Undo (Ctrl+Z)", 18)
        self.undo_btn.clicked.connect(self.engine.undo)
        self.redo_btn = icon_btn("redo", "Redo (Ctrl+Shift+Z)", 18)
        self.redo_btn.clicked.connect(self.engine.redo)
        h.addWidget(self.undo_btn)
        h.addWidget(self.redo_btn)
        h.addSpacing(10)
        sun = QLabel()
        sun.setPixmap(icons.glyph_pixmap("sun", 18, "#9a9aa5"))
        h.addWidget(sun)
        self.bright = QSlider(Qt.Orientation.Horizontal)
        self.bright.setRange(5, 100)
        self.bright.setFixedWidth(120)
        self.bright.setToolTip("Deck brightness")
        self.bright.valueChanged.connect(lambda v: self.engine.set_setting("brightness", v))
        h.addWidget(self.bright)
        h.addSpacing(6)
        self.agents_btn = QPushButton("  Agents")
        self.agents_btn.setIcon(icons.glyph_icon("bot", 17, "#d0d0d8"))
        self.agents_btn.setToolTip("Connect AI agents (MCP)")
        self.agents_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.agents_btn.clicked.connect(self.open_agents)
        h.addWidget(self.agents_btn)
        h.addSpacing(4)
        gear = icon_btn("settings", "Preferences", 19)
        gear.clicked.connect(self.open_prefs)
        h.addWidget(gear)
        return bar

    def _statusbar(self):
        bar = QFrame()
        bar.setObjectName("statusbar")
        bar.setFixedHeight(28)
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 0, 16, 0)
        self.dot = StatusDot()
        h.addWidget(self.dot)
        self.status_lbl = QLabel()
        self.status_lbl.setStyleSheet(f"color:{style.MUTED};font-size:12px;")
        h.addWidget(self.status_lbl)
        h.addStretch(1)
        tip = QLabel("Drag keys to rearrange  ·  Ctrl-drag to copy  ·  Ctrl+Z to undo")
        tip.setStyleSheet(f"color:{style.MUTED};font-size:11px;")
        h.addWidget(tip)
        return bar

    def _wire(self):
        e = self.engine
        e.changed.connect(self.refresh)
        e.key_changed.connect(self.deck.refresh)
        e.status.connect(self._on_status)
        e.device_changed.connect(lambda: self._on_status(e.conn_info))
        errors.notifier.message.connect(self._on_message)
        e.auto_switched.connect(self._on_auto_switched)
        e.error.connect(lambda m: self.toast.show_message(m, "error"))
        e.settings_changed.connect(self._sync_settings)
        d = self.deck
        d.selected.connect(self._select)
        d.activated.connect(self._open_key)
        d.contextRequested.connect(self._context)
        d.dropAction.connect(self._drop_action)
        d.dropKey.connect(lambda s, t, c: (e.move_key(s, t, c), self._select(t)))
        d.dropFile.connect(self._drop_file)
        self.sidebar.activated.connect(self._sidebar_add)
        self._sync_settings()

    def _shortcuts(self):
        def act(text, keys, fn, widget=None, ctx=Qt.ShortcutContext.WindowShortcut):
            a = QAction(text, widget or self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.setShortcutContext(ctx)
            a.triggered.connect(fn)
            (widget or self).addAction(a)
            return a
        act("Palette", ["Ctrl+K"], self.open_palette)
        act("Shortcuts", ["F1"], self.open_shortcuts)
        for n in range(1, 10):
            act(f"Page {n}", [f"Ctrl+{n}"], lambda _=False, n=n: self.engine.goto_page(n - 1) if n <= len(self.engine.profile["pages"]) else None)
        act("Undo", ["Ctrl+Z"], self.engine.undo)
        act("Redo", ["Ctrl+Shift+Z", "Ctrl+Y"], self.engine.redo)
        ctx = Qt.ShortcutContext.WidgetShortcut
        act("Copy", ["Ctrl+C"], self.copy_key, self.deck, ctx)
        act("Cut", ["Ctrl+X"], lambda: (self.copy_key(), self.engine.clear_key(self.deck.sel)), self.deck, ctx)
        act("Paste", ["Ctrl+V"], self.paste_key, self.deck, ctx)
        act("Duplicate", ["Ctrl+D"], self.duplicate_key, self.deck, ctx)
        act("Clear", ["Delete", "Backspace"], lambda: self.engine.clear_key(self.deck.sel), self.deck, ctx)

    def _tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("Deckhand")
        self.tray_menu = QMenu()
        self.tray_menu.aboutToShow.connect(self._tray_menu_fill)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda r: self.toggle_visible() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _tray_menu_fill(self):
        m = self.tray_menu
        m.clear()
        m.addAction("Hide window" if self.isVisible() else "Open Deckhand", self.toggle_visible)
        m.addSeparator()
        for p in self.engine.profiles():
            a = m.addAction(p["name"])
            a.setCheckable(True)
            a.setChecked(p is self.engine.profile)
            a.triggered.connect(lambda _=False, pid=p["id"]: self.engine.switch_profile(pid))
        m.addSeparator()
        m.addAction("Quit", self.quit_app)

    # ---- state sync ----------------------------------------------------------------------
    def refresh(self):
        e = self.engine
        self.deck.refresh()
        self._fill_profiles()
        self._fill_crumbs()
        self._fill_pages()
        empty = all(model.key_is_empty(e.get_key(i)) for i in range(e.n_keys) if not e.is_locked(i))
        self.hint.setVisible(empty)
        self.undo_btn.setEnabled(e.can_undo)
        self.redo_btn.setEnabled(e.can_redo)
        if self.deck.sel >= e.n_keys:
            self.deck.set_selected(0)
        if hasattr(self, "inspector"):
            self.inspector.idx = self.deck.sel

    def _sync_settings(self):
        b = self.engine.settings["brightness"]
        if self.bright.value() != b:
            self.bright.blockSignals(True)
            self.bright.setValue(b)
            self.bright.blockSignals(False)

    def _fill_profiles(self):
        c = self.profile_combo
        c.blockSignals(True)
        c.clear()
        for p in self.engine.profiles():
            c.addItem(p["name"], p["id"])
        c.setCurrentIndex(max(0, c.findData(self.engine.profile["id"])))
        c.blockSignals(False)

    def _clear_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _fill_crumbs(self):
        e = self.engine
        self._clear_layout(self.crumbs)
        names = [(e.profile["name"], 0)]
        if len(e.profile["pages"]) > 1 or True:
            names.append((e.profile["pages"][e.loc["page"]]["name"], 0))
        for i, fid in enumerate(e.loc["folders"]):
            f = e.profile["folders"].get(fid)
            names.append((f["name"] if f else "?", i + 1))
        if e.in_folder:
            back = icon_btn("arrow-left", "Back", 16)
            back.clicked.connect(e.go_back)
            self.crumbs.addWidget(back)
        for n, (name, depth) in enumerate(names):
            last = n == len(names) - 1
            if n:
                sep = QLabel("›")
                sep.setObjectName("muted")
                self.crumbs.addWidget(sep)
            b = QPushButton(name)
            b.setObjectName("crumbLast" if last else "crumb")
            b.setFlat(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if last:
                b.setStyleSheet(f"QPushButton{{font-weight:700;background:transparent;border:none;padding:3px 6px;}}")
                b.setToolTip("Click to rename")
                b.clicked.connect(self.rename_container)
            elif n == 0:
                b.clicked.connect(lambda _=False: e.go_up_to(0))
            else:
                b.clicked.connect(lambda _=False, d=depth: e.go_up_to(d))
            self.crumbs.addWidget(b)
        self.crumbs.addStretch(1)

    def _fill_pages(self):
        e = self.engine
        self._clear_layout(self.pages)
        self.pages.addStretch(1)
        n = len(e.profile["pages"])
        for i in range(n):
            b = PageButton(str(i + 1))
            b.setCheckable(True)
            b.setChecked(i == e.loc["page"] and not e.in_folder)
            b.setFixedSize(30, 26)
            b.setToolTip(e.profile["pages"][i]["name"] + "  (Ctrl+" + str(i + 1) + ")" if i < 9 else e.profile["pages"][i]["name"])
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("glowRadius", 13)
            b.setStyleSheet(f"QPushButton{{padding:0;border-radius:13px;background:{style.CARD};}}"
                            f"QPushButton:checked{{background:{style.ACCENT};border-color:{style.ACCENT};color:white;}}")
            b.clicked.connect(lambda _=False, i=i: e.goto_page(i))
            b.keyDropped.connect(lambda idx, i=i: e.move_key_to_page(idx, i))
            b.hovered.connect(lambda i=i: e.goto_page(i))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda pos, i=i, b=b: self._page_menu(i, b.mapToGlobal(pos)))
            self.pages.addWidget(b)
        add = icon_btn("plus", "Add page", 16)
        menu = QMenu(add)
        menu.addAction("Blank page", e.add_page)
        menu.addAction("From a template…", self.add_from_template)
        add.setMenu(menu)
        add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.pages.addWidget(add)
        self.pages.addStretch(1)

    def add_from_template(self):
        from .templates_dialog import TemplatesDialog
        d = TemplatesDialog(self.engine, self)
        if d.exec() == d.DialogCode.Accepted and d.chosen:
            self.engine.add_template_page(d.chosen)

    def _page_menu(self, i, pos):
        e = self.engine
        m = QMenu(self)
        m.addAction("Rename page…", lambda: self._rename_page(i))
        m.addAction("Duplicate page", lambda: e.duplicate_page(i))
        l = m.addAction("Move left", lambda: e.move_page(i, -1))
        l.setEnabled(i > 0)
        r = m.addAction("Move right", lambda: e.move_page(i, 1))
        r.setEnabled(i < len(e.profile["pages"]) - 1)
        sub = m.addMenu("Copy to profile")
        others = [p for p in e.profiles() if p is not e.profile]
        sub.setEnabled(bool(others))
        for p in others:
            sub.addAction(p["name"], lambda pid=p["id"]: self._copy_page(i, pid))
        m.addSeparator()
        d = m.addAction("Delete page", lambda: e.delete_page(i))
        d.setEnabled(len(e.profile["pages"]) > 1)
        m.exec(pos)

    def _copy_page(self, i, pid):
        try:
            name = self.engine.copy_page_to_profile(i, pid)
            self.toast.show_message(f"Page copied to {name}", "ok")
        except ValueError as ex:
            self.toast.show_message(str(ex).capitalize(), "error")

    def _rename_page(self, i):
        e = self.engine
        name, ok = QInputDialog.getText(self, "Rename page", "Page name", text=e.profile["pages"][i]["name"])
        if ok and name.strip():
            with e.mutate():
                e.profile["pages"][i]["name"] = name.strip()

    def _on_status(self, info):
        e = self.engine
        dev = e.dev
        st = info.get("state")
        if dev:
            self.chip.setText(f"  {dev.model.name}")
            self.dot.set_color(style.OK, ping=not getattr(self, "_was_connected", False))
            self._was_connected = True
            self.status_lbl.setText(f"Connected  ·  {dev.model.cols}×{dev.model.rows} keys" + (f"  ·  serial {dev.serial}" if dev.serial else ""))
            self.banner.hide()
        else:
            self._was_connected = False
            g = trouble.guide(info)
            self.chip.setText("  " + ("Looking for deck…" if st == "scanning" else info.get("title") if st in ("busy", "denied", "unsupported") else "No Stream Deck"))
            self.dot.set_color({"warn": style.WARN, "error": style.DANGER}.get(g["level"], style.MUTED))
            self.status_lbl.setText(info.get("title") or "No Stream Deck")
            self.banner.update_for(info)
        if self.tray:
            self.tray.setToolTip("Deckhand: " + (info.get("title") or ""))
        self._loading_check(info)

    def _chip_menu(self):
        e = self.engine
        m = QMenu(self)
        devs = [d for d in e.conn_info.get("devices", []) if d.get("supported")]
        if len(devs) > 1:
            for d in devs:
                a = m.addAction(f"{d['name']}  ·  {d['serial'] or 'unknown serial'}")
                a.setCheckable(True)
                a.setChecked(bool(e.dev and e.dev.serial == d["serial"]))
                a.triggered.connect(lambda _=False, s=d["serial"]: e.choose_device(s))
            m.addSeparator()
        m.addAction("Retry connection", e.retry_device)
        if not e.dev:
            m.addAction("Troubleshooting…", self.open_trouble)
        m.addSeparator()
        m.addAction("Preferences…", self.open_prefs)
        m.exec(self.chip.mapToGlobal(self.chip.rect().bottomLeft()))

    def open_trouble(self):
        TroubleDialog(self.engine, self).exec()

    # ---- loading screen & messages ---------------------------------------------------------------
    def _start_loading(self):
        self._overlay = LoadingOverlay(self.centralWidget())
        self._overlay.setGeometry(self.centralWidget().rect())
        self._overlay.set_text("Looking for your Stream Deck…")
        self._overlay.finished.connect(self._after_loading)
        self._load_timer = QTimer(self, interval=150)
        self._load_timer.timeout.connect(lambda: self._loading_check(self.engine.conn_info))
        self._load_timer.start()

    def _loading_check(self, info):
        ov = getattr(self, "_overlay", None)
        if ov is None or ov._done:
            return
        st, t = info.get("state"), ov.elapsed
        if st == "scanning" or st is None:
            ov.set_text("Looking for your Stream Deck…")
        elif st == "none":
            ov.set_text("Still looking…" if t > 1.5 else "Looking for your Stream Deck…")
        if st == "ok" or st in ("busy", "denied", "unsupported", "nolib", "error") or (st == "none" and t >= NONE_GRACE_S) or t >= HARD_TIMEOUT_S:
            ov.finish()

    def _after_loading(self):
        self._load_timer.stop()
        self._overlay = None
        notes = self.engine.startup_notices()
        bad = [t for lv, t in notes if lv == "error"]
        if bad:
            box = QMessageBox(QMessageBox.Icon.Warning, "Deckhand could not read some saved data", "\n\n".join(t for _l, t in notes), parent=self)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            box.open()
            self._startup_box = box
        else:
            for lv, t in notes:
                self.toast.show_message(t, lv, 6000)

    def _on_message(self, level, text):
        self.toast.show_message(text, level, 7000 if level in ("error", "warn") else 3200)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        ov = getattr(self, "_overlay", None)
        if ov is not None:
            ov.setGeometry(self.centralWidget().rect())

    # ---- interactions --------------------------------------------------------------------
    def _select(self, idx):
        self.deck.set_selected(idx)
        self.inspector.set_key(idx)

    def _open_key(self, idx):
        """Double-click: a folder key opens its folder, the Back key goes back."""
        e = self.engine
        k = e.get_key(idx)
        a = (k or {}).get("action") or {}
        if a.get("type") == "folder" and a.get("params", {}).get("folder") in e.profile["folders"]:
            e.open_folder(a["params"]["folder"])
            self._select(0)
        elif a.get("type") == "back" and e.in_folder:
            e.go_back()
            self._select(0)

    def _drop_action(self, idx, aid):
        if aid.startswith("app:"):
            self.engine.assign_app(idx, aid[4:])
        else:
            self.engine.assign_action(idx, aid)
        self._select(idx)

    def _drop_file(self, idx, path):
        try:
            self.engine.edit_key(idx, icon=import_image(path))
            self._select(idx)
        except OSError as ex:
            self.toast.show_message(f"Could not import image: {ex}", "error")

    def _sidebar_add(self, aid):
        e = self.engine
        idx = self.deck.sel
        if idx < 0 or e.is_locked(idx) or (e.get_key(idx) and e.get_key(idx).get("action")):
            free = [i for i in range(e.n_keys) if not e.is_locked(i) and not e.get_key(i)]
            if free:
                idx = free[0]
            elif idx < 0 or e.is_locked(idx):
                self.toast.show_message("No free key on this page", "error")
                return
        self._drop_action(idx, aid)

    def duplicate_key(self):
        e = self.engine
        i = self.deck.sel
        k = e.get_key(i)
        if i < 0 or model.key_is_empty(k) or e.is_locked(i):
            return
        free = next((j for j in range(i + 1, e.n_keys) if not e.get_key(j)), None) or next((j for j in range(e.n_keys) if not e.is_locked(j) and not e.get_key(j)), None)
        if free is None:
            self.toast.show_message("No free key to put the copy on", "warn")
            return
        e.paste_key(free, k)
        self._select(free)

    def open_shortcuts(self):
        from .shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

    def open_palette(self):
        from .palette import CommandPalette
        e = self.engine
        items = [("Undo", "Ctrl+Z", "undo", e.undo), ("Redo", "Ctrl+Shift+Z", "redo", e.redo),
                 ("Add a blank page", "", "plus", e.add_page), ("Add a page from a template…", "", "grid", self.add_from_template),
                 ("Deck wallpaper…", "", "image", self.open_wallpaper), ("Auto-switch by window…", "", "layers", self.open_autoswitch),
                 ("Connect AI agents…", "", "bot", self.open_agents), ("Preferences…", "", "settings", self.open_prefs),
                 ("Keyboard shortcuts", "F1", "keyboard", self.open_shortcuts), ("New profile…", "", "plus", self.new_profile),
                 ("Export profile…", "", "download", self.export_profile), ("Import profile…", "", "download", self.import_profile),
                 ("Retry deck connection", "", "refresh", e.retry_device),
                 ("Turn animations " + ("off" if e.settings["animations"] else "on"), "", "zap", lambda: e.set_setting("animations", not e.settings["animations"]))]
        if not e.dev:
            items.append(("Troubleshoot the Stream Deck…", "", "usb", self.open_trouble))
        for p in e.profiles():
            if p is not e.profile:
                items.append((f"Switch to profile: {p['name']}", "", "layers", lambda pid=p["id"]: e.switch_profile(pid)))
        for n, pg in enumerate(e.profile["pages"]):
            items.append((f"Go to page {n + 1}: {pg['name']}", "", "grid", lambda n=n: e.goto_page(n)))
        for fid, f in e.profile["folders"].items():
            ch = None
            from .agentapi import folder_chain
            ch = folder_chain(e.profile, fid)
            if ch:
                items.append((f"Open folder: {f['name']}", "", "folder", lambda ch=ch: (setattr(e, "loc", {"page": ch[0], "folders": list(ch[1])}), e._nav_done())))
        for aid, a in actions.ACTIONS.items():
            if aid in ("back", "delay", "counter_reset", "timer_reset"):
                continue
            items.append((f"Add action: {a['name']}", "to the selected key", a["glyph"], lambda aid=aid: self._sidebar_add(aid)))
        items.append(("Quit Deckhand", "", "power", self.quit_app))
        CommandPalette(items, self).show_over(self)

    def copy_key(self):
        k = self.engine.get_key(self.deck.sel)
        if k and not model.key_is_empty(k):
            self._clip = (copy.deepcopy(k), self.engine.profile["id"], copy.deepcopy(self.engine.profile["folders"]))
            self.toast.show_message("Key copied", "ok", 1200)

    def paste_key(self):
        if not self._clip:
            return
        key, pid, folders = self._clip
        e = self.engine
        if pid != e.profile["id"]:
            tmp = {"folders": folders}
            key = model.clone_key(tmp, key)
            for fid, f in tmp["folders"].items():
                e.profile["folders"].setdefault(fid, f)
        e.paste_key(self.deck.sel, key)

    def _context(self, idx, pos):
        e = self.engine
        k = e.get_key(idx)
        m = QMenu(self)
        locked = e.is_locked(idx)
        if k and k.get("action"):
            m.addAction("Test action", lambda: e.trigger(idx))
            m.addSeparator()
        c = m.addAction("Copy", self.copy_key)
        c.setEnabled(not model.key_is_empty(k) and not locked)
        x = m.addAction("Cut", lambda: (self.copy_key(), e.clear_key(idx)))
        x.setEnabled(c.isEnabled())
        p = m.addAction("Paste", self.paste_key)
        p.setEnabled(bool(self._clip) and not locked)
        m.addSeparator()
        d = m.addAction("Clear key", lambda: e.clear_key(idx))
        d.setEnabled(c.isEnabled())
        m.exec(pos)

    # ---- profiles --------------------------------------------------------------------------
    def new_profile(self):
        name, ok = QInputDialog.getText(self, "New profile", "Profile name")
        if ok and name.strip():
            self.engine.new_profile(name.strip())

    def rename_profile(self):
        name, ok = QInputDialog.getText(self, "Rename profile", "Profile name", text=self.engine.profile["name"])
        if ok and name.strip():
            self.engine.rename_profile(name.strip())

    def rename_container(self):
        e = self.engine
        cur = e.crumbs()[-1]
        name, ok = QInputDialog.getText(self, "Rename", "Name", text=cur)
        if ok and name.strip():
            if not e.in_folder and len(e.profile["pages"]) >= 1:
                with e.mutate():
                    e.container["name"] = name.strip()
            else:
                e.rename_container(name.strip())

    def delete_profile(self):
        e = self.engine
        if len(e.profiles()) <= 1:
            self.toast.show_message("You need at least one profile", "error")
            return
        r = QMessageBox.question(self, "Delete profile", f"Delete “{e.profile['name']}” and all its keys?")
        if r == QMessageBox.StandardButton.Yes:
            e.delete_profile()

    def export_profile(self):
        e = self.engine
        path, _ = QFileDialog.getSaveFileName(self, "Export profile", os.path.expanduser(f"~/{e.profile['name']}.deckhand"), "Deckhand profile (*.deckhand)")
        if path:
            try:
                model.write_json(path, e.profile)
                self.toast.show_message("Profile exported", "ok")
            except OSError as ex:
                self.toast.show_message(errors.explain(ex, "Could not export"), "error")

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import profile", os.path.expanduser("~"), "Deckhand profile (*.deckhand *.json)")
        if not path:
            return
        data = model.read_json(path, None)
        if not isinstance(data, dict) or "pages" not in data or "cols" not in data:
            self.toast.show_message("That file is not a Deckhand profile", "error")
            return
        try:
            self.engine.import_profile(data)
        except ValueError as ex:
            self.toast.show_message(str(ex).capitalize(), "error")
            return
        self.toast.show_message("Profile imported", "ok")

    # ---- agents (MCP) ----------------------------------------------------------------------
    def attach_agents(self, server):
        self.mcp = server
        self._approvals = []
        server.activity.connect(lambda t: (self.toast.show_message(t, "info", 2200), self._agent_pulse()))
        server.sessions_changed.connect(self._agents_changed)
        server.approval_requested.connect(self._approval)

    def _agent_pulse(self):
        """Brief glow on the Agents button: something just changed because an agent acted."""
        def upd(a):
            self.agents_btn.setStyleSheet(f"QPushButton{{border-color:rgba(61,220,132,{int(255 * a)});background:rgba(61,220,132,{int(40 * a)});}}")

        def done():
            self._agents_changed()
        motion.value_anim(self, 1.0, 0.0, 900, upd, on_done=done)

    def _agents_changed(self):
        n = len([s for s in self.mcp.sessions if s.ready])
        self.agents_btn.setText(f"  Agents ({n})" if n else "  Agents")
        self.agents_btn.setStyleSheet(f"QPushButton{{border-color:{style.OK};}}" if n else "")

    def _approval(self, ap):
        from .approval import ApprovalDialog
        dlg = ApprovalDialog(ap)
        self._approvals.append(dlg)
        dlg.destroyed.connect(lambda *_: self._approvals.remove(dlg) if dlg in self._approvals else None)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        if self.tray and not self.isVisible():
            self.tray.showMessage("Deckhand", f"{ap.client} is asking to run an action", QSystemTrayIcon.MessageIcon.Warning, 6000)

    def open_agents(self):
        from .agents_dialog import AgentsDialog
        AgentsDialog(self.engine, self.mcp, self).exec()

    def open_autoswitch(self):
        from .autoswitch_dialog import AutoSwitchDialog
        AutoSwitchDialog(self.engine, self).exec()

    def _on_auto_switched(self, text):
        self.status_lbl.setText(text)
        QTimer.singleShot(4500, lambda: self._on_status(self.engine.conn_info))

    def open_wallpaper(self):
        from .wallpaper_dialog import WallpaperDialog
        WallpaperDialog(self.engine, self).exec()

    def open_prefs(self):
        PrefsDialog(self.engine, self).exec()

    # ---- window lifecycle ---------------------------------------------------------------
    def toggle_visible(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_front()

    def show_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self.quitting = True
        QApplication.quit()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.engine.ui_visible = True

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.engine.ui_visible = False

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == ev.Type.WindowStateChange:
            self.engine.ui_visible = self.isVisible() and not self.isMinimized()

    def _layout_file(self):
        return os.path.join(model.CONFIG_DIR, "window.json")

    def _restore_layout(self):
        d = model.read_json(self._layout_file(), {})
        try:
            if isinstance(d, dict) and all(isinstance(d.get(k), int) for k in ("w", "h")):
                scr = QApplication.primaryScreen().availableGeometry()
                self.resize(max(self.minimumWidth(), min(d["w"], scr.width())), max(self.minimumHeight(), min(d["h"], scr.height())))
            sizes = d.get("split") if isinstance(d, dict) else None
            if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(x, int) and x > 80 for x in sizes):
                self.split.setSizes(sizes)
        except Exception:
            pass

    def _save_layout(self):
        try:
            model.write_json(self._layout_file(), {"w": self.width(), "h": self.height(), "split": self.split.sizes()})
        except OSError:
            pass

    def closeEvent(self, ev):
        self._save_layout()
        if not self.quitting and self.tray and self.engine.settings["close_to_tray"]:
            ev.ignore()
            self.hide()
            if not getattr(self, "_told", False):
                self._told = True
                self.tray.showMessage("Deckhand is still running", "Your Stream Deck keeps working. Use the tray icon to reopen or quit.",
                                      QSystemTrayIcon.MessageIcon.Information, 3500)
            return
        super().closeEvent(ev)
