"""Bottom panel: edits the selected key's appearance and action."""
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QBoxLayout, QComboBox, QMenu, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                             QStackedLayout, QVBoxLayout, QWidget)

from . import actions, forms, icons, model, render, style, sysinfo
from .iconpicker import pick_icon
from . import motion
from .widgets import ColorButton, ElidedLabel, Segmented, Switch, compact_combo, fit_combo, icon_btn


def card(title, right=None):
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(8)
    t = QLabel(title.upper())
    t.setObjectName("cardTitle")
    if right is None:
        lay.addWidget(t)
    else:
        h = QHBoxLayout()
        h.addWidget(t, 1)
        h.addWidget(right)
        lay.addLayout(h)
    return f, lay


class ResponsiveRow(QWidget):
    """Lays cards side by side when they fit and stacks them when they do not (never scroll sideways)."""

    def __init__(self, spacing=14):
        super().__init__()
        self.lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(spacing)
        self.items = []

    def add(self, w, stretch):
        self.items.append((w, stretch))
        self.lay.addWidget(w, stretch)

    def _need(self):
        return sum(w.minimumSizeHint().width() for w, _ in self.items) + self.lay.spacing() * (len(self.items) - 1)

    def minimumSizeHint(self):
        return QSize(max(w.minimumSizeHint().width() for w, _ in self.items), self.lay.minimumSize().height())

    def resizeEvent(self, ev):
        d = QBoxLayout.Direction.LeftToRight if self.width() >= self._need() else QBoxLayout.Direction.TopToBottom
        if d != self.lay.direction():
            self.lay.setDirection(d)
            for n, (_, st) in enumerate(self.items):
                self.lay.setStretch(n, st if d == QBoxLayout.Direction.LeftToRight else 0)
            self.updateGeometry()
        super().resizeEvent(ev)


class FaceButton(QPushButton):
    """Live preview of the key; clicking it opens the icon picker."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(96, 96)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Change icon")
        self.setStyleSheet(f"QPushButton{{border:1px solid {style.BORDER};border-radius:12px;padding:0;background:#000;}}"
                           f"QPushButton:hover{{border-color:{style.ACCENT};}}")
        self.setIconSize(QSize(88, 88))

    def set_face(self, img):
        px = QPixmap.fromImage(img)
        px.setDevicePixelRatio(2)
        from PyQt6.QtGui import QIcon
        self.setIcon(QIcon(px))


class Inspector(QWidget):
    def __init__(self, engine, toast):
        super().__init__()
        self.setObjectName("inspector")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.engine, self.toast = engine, toast
        self.idx = -1
        self._editing = False
        self._built_for = None
        self._rev = 0
        self.tab = "base"
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)

        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        ic = QLabel()
        ic.setPixmap(icons.glyph_pixmap("grid", 40, style.MUTED, 1.6))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(ic)
        msg = QLabel("Select a key to edit it")
        msg.setObjectName("muted")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(msg)
        el.addStretch(1)
        self.stack.addWidget(empty)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stack.addWidget(self.scroll)

        engine.changed.connect(self._on_changed)
        engine.key_changed.connect(self._on_key_changed)
        engine.wall_frame.connect(lambda: self._update_face() if self.idx >= 0 and engine.key_uses_wallpaper(self.idx) else None)

    # ---- external API ---------------------------------------------------------------
    def set_key(self, idx):
        if idx != self.idx:
            self.tab = "base"
        self.idx = idx
        self._built_for = None
        self.rebuild()

    def _on_changed(self):
        if self._editing:
            self._update_face()
            return
        self._built_for = None
        self.rebuild()

    def _on_key_changed(self, i):
        if i == self.idx:
            self._update_face()

    # ---- building ---------------------------------------------------------------
    def rebuild(self):
        e = self.engine
        if self.idx < 0 or self.idx >= e.n_keys:
            self.stack.setCurrentIndex(0)
            return
        key = e.get_key(self.idx)
        sig = (self.idx, self.tab, bool(key and key.get("alt")), key["action"]["type"] if key and key.get("action") else None, tuple(e.loc["folders"]), e.loc["page"], id(e.profile))
        if sig == self._built_for:
            self._update_face()
            return
        self._built_for = sig
        self.stack.setCurrentIndex(1)
        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(12)
        locked = e.is_locked(self.idx)
        outer.addLayout(self._header(key, locked))
        if locked:
            note = QLabel("This key always goes back to the previous level.")
            note.setObjectName("muted")
            outer.addWidget(note)
            outer.addStretch(1)
        else:
            row = ResponsiveRow()
            row.add(self._appearance(key or model.new_key()), 5)
            row.add(self._action_card(key), 6)
            outer.addWidget(row)
            outer.addStretch(1)
        self.scroll.setWidget(body)
        motion.fade_in(body, 150)
        self._update_face()

    def _header(self, key, locked):
        e = self.engine
        h = QHBoxLayout()
        a = key.get("action") if key else None
        meta = actions.ACTIONS.get(a["type"]) if a else None
        badge = QLabel(f"KEY {self.idx + 1}")
        badge.setStyleSheet(f"background:{style.CARD};color:{style.MUTED};font-weight:700;font-size:11px;letter-spacing:1px;padding:4px 9px;border-radius:6px;")
        h.addWidget(badge)
        self.h_title = QLabel(meta["name"] if meta else "Empty key")
        self.h_title.setObjectName("h1")
        h.addWidget(self.h_title)
        self.h_sub = ElidedLabel(actions.describe(a) if a else "Drag an action here, or pick one on the right")
        self.h_sub.setObjectName("muted")
        h.addWidget(self.h_sub, 1)
        if a:
            test = QPushButton("  Test")
            test.setIcon(icons.glyph_icon("play", 14, "#d0d0d8"))
            test.setToolTip("Run this key's action now")
            test.clicked.connect(lambda: e.trigger(self.idx))
            h.addWidget(test)
        if not locked and (key and not model.key_is_empty(key)):
            clear = QPushButton("  Clear")
            clear.setIcon(icons.glyph_icon("trash", 14, style.DANGER))
            clear.clicked.connect(lambda: e.clear_key(self.idx))
            h.addWidget(clear)
        return h

    def _edit_key(self, coalesce, **fields):
        self._editing = True
        self.engine.quiet_flash = bool(coalesce)
        try:
            self.engine.edit_key(self.idx, coalesce=f"k:{self.idx}:{coalesce}" if coalesce else None, **fields)
        finally:
            self._editing = False
            self.engine.quiet_flash = False

    # State-aware editing: on the "Active" tab, look fields are stored in key["alt"].
    def _state_meta(self, key):
        a = key.get("action") if key else None
        return actions.ACTIONS.get(a["type"], {}).get("state") if a else None

    def _ensure_alt(self):
        e = self.engine
        k = e.get_key(self.idx) or {}
        if k.get("alt"):
            return
        st = self._state_meta(k)
        with e.mutate():
            if st and not (k.get("icon") and k["icon"].get("value")):
                e.edit_key(self.idx, icon={"kind": "glyph", "value": st["off"]["glyph"]})
                on = st["on"]
                seed = {"icon": {"kind": "glyph", "value": on["glyph"]}}
                seed.update({f: on[f] for f in ("bg", "icon_color", "title_color") if f in on})
                e.edit_alt(self.idx, **seed)
            else:
                e.edit_alt(self.idx, bg="#14315c")

    def _edit(self, coalesce, **fields):
        """Edit look fields on the current tab (default look or active look)."""
        if self.tab == "alt":
            self._editing = True
            self.engine.quiet_flash = bool(coalesce)
            try:
                self._ensure_alt()
                rm = [f for f, v in fields.items() if v is None or (f == "title" and v == "")]
                vals = {f: v for f, v in fields.items() if f not in rm}
                self.engine.edit_alt(self.idx, coalesce=f"a:{self.idx}:{coalesce}" if coalesce else None, remove=rm, **vals)
            finally:
                self._editing = False
                self.engine.quiet_flash = False
        else:
            self._edit_key(coalesce, **fields)

    def _look(self, key, field, default):
        """Value of a look field as shown on the current tab."""
        if self.tab == "alt":
            alt = key.get("alt") or {}
            if field in alt:
                return alt[field]
            eff = render.effective(key, True)
            return eff.get(field, default)
        return key.get(field, default)

    def _appearance(self, key):
        H = 34
        a = key.get("action")
        st = self._state_meta(key)
        if st and a and a.get("params", {}).get("device"):
            kind = "source" if a["type"] == "micmute" else "sink"
            desc = next((d["description"] for d in sysinfo.audio_devices(kind) if d["name"] == a["params"]["device"]), a["params"]["device"])
            st = {**st, "follows": desc}
        has_alt = bool(key.get("alt"))
        stateful = render.has_states(key)
        if not stateful:
            self.tab = "base"
        right = None
        if stateful:
            right = Segmented([("base", "Default", "How the key normally looks", False), ("alt", "Active", "How the key looks when active", False)])
            right.set_value(self.tab)
            right.setFixedHeight(30)
            right.changed.connect(self._set_tab)
        elif a:
            right = QPushButton("  Add active look")
            right.setIcon(icons.glyph_icon("plus", 14, "#d0d0d8"))
            right.setToolTip("Show a different icon when the key is toggled (it flips each time you press it)")
            right.clicked.connect(self._add_alt)
        alt_tab = self.tab == "alt"
        f, lay = card("Appearance", right)
        lay.setSpacing(12)
        if stateful:
            if st:
                note = f"Active look is shown while {st['follows']} is {st['label']}. It updates by itself."
            else:
                note = "Active look is shown after you press the key; each press toggles it."
            nl = QHBoxLayout()
            nlab = QLabel(note if alt_tab else (f"Follows {st['follows']}." if st else "Toggles on every press."))
            nlab.setObjectName("muted")
            nlab.setWordWrap(True)
            nl.addWidget(nlab, 1)
            if has_alt:
                rm = QPushButton("Remove")
                rm.setObjectName("danger")
                rm.setToolTip("Remove the active look")
                rm.clicked.connect(self._remove_alt)
                nl.addWidget(rm)
            lay.addLayout(nl)

        top = QHBoxLayout()
        top.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(6)
        self.face = FaceButton()
        self.face.clicked.connect(self._choose_icon)
        left.addWidget(self.face)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        for glyph, tip, fn in (("image", "Choose icon…", self._choose_icon), ("undo", "Use the default icon" if not alt_tab else "Same icon as the default look", self._reset_icon)):
            b = QPushButton()
            b.setIcon(icons.glyph_icon(glyph, 16, "#d0d0d8"))
            b.setToolTip(tip)
            b.setFixedHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            btns.addWidget(b)
        left.addLayout(btns)
        top.addLayout(left)

        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(forms.muted("TITLE"))
        head.addStretch(1)
        sl = QLabel("Show")
        sl.setStyleSheet(f"color:{style.MUTED};font-size:12px;")
        head.addWidget(sl)
        head.addSpacing(6)
        self.show_title = Switch(key.get("show_title", True))
        self.show_title.setEnabled(not alt_tab)
        self.show_title.toggled.connect(lambda v: self._edit_key(None, show_title=v))
        head.addWidget(self.show_title)
        right_col.addLayout(head)
        alt_title = (key.get("alt") or {}).get("title", "")
        self.title = QPlainTextEdit(alt_title if alt_tab else key.get("title", ""))
        self.title.setPlaceholderText("Same as the default look" if alt_tab else "Add a title")
        self.title.textChanged.connect(lambda: self._edit("title", title=self.title.toPlainText()))
        self.title.setFixedHeight(102)
        right_col.addWidget(self.title)
        top.addLayout(right_col, 1)
        lay.addLayout(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{style.BORDER};")
        lay.addWidget(sep)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.pos = Segmented([("top", "arrow-up", "Title at top", True), ("middle", "more", "Title in the middle", True),
                              ("bottom", "arrow-down", "Title at bottom", True)])
        self.pos.setFixedHeight(H)
        self.pos.set_value(key.get("title_pos", "bottom"))
        self.pos.changed.connect(lambda v: self._edit_key(None, title_pos=v))
        row.addWidget(self.pos, 3)
        self.size = QSpinBox()
        self.size.setRange(8, 40)
        self.size.setSuffix(" px")
        self.size.setFixedHeight(H)
        self.size.setValue(key.get("title_size", 14))
        self.size.setToolTip("Title size")
        self.size.valueChanged.connect(lambda v: self._edit_key("size", title_size=v))
        row.addWidget(self.size, 2)
        self.bold = QPushButton("B")
        self.bold.setCheckable(True)
        self.bold.setChecked(key.get("bold", True))
        self.bold.setFixedSize(H, H)
        self.bold.setToolTip("Bold title")
        self.bold.setStyleSheet(f"QPushButton{{font-weight:800;padding:0;}}QPushButton:checked{{background:{style.ACCENT};border-color:{style.ACCENT};color:white;}}")
        self.bold.toggled.connect(lambda v: self._edit_key(None, bold=v))
        row.addWidget(self.bold)
        if alt_tab:
            for w in (self.pos, self.size, self.bold):
                w.setEnabled(False)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        for label, field, tip in (("Text", "title_color", "Title color"), ("Icon", "icon_color", "Icon color"), ("Background", "bg", "Background color")):
            cell = QFrame()
            cell.setFixedHeight(H)
            cell.setStyleSheet(f"QFrame{{background:{style.BG};border:1px solid {style.BORDER};border-radius:8px;}}QLabel{{border:none;color:{style.MUTED};}}")
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(10, 0, 6, 0)
            cl.addWidget(QLabel(label))
            cl.addStretch(1)
            cb = ColorButton(self._look(key, field, "#ffffff" if field != "bg" else "#000000"), tip, compact=True)
            cb.changed.connect(lambda c, field=field: self._edit(field, **{field: c}))
            cl.addWidget(cb)
            row2.addWidget(cell, 3 if field == "bg" else 2)
        lay.addLayout(row2)
        lay.addStretch(1)
        return f

    def _set_tab(self, v):
        self.tab = v
        self._built_for = None
        self.rebuild()

    def _add_alt(self):
        self._ensure_alt()
        self.tab = "alt"
        self._built_for = None
        self.rebuild()

    def _remove_alt(self):
        self.engine.edit_key(self.idx, alt=None)
        self.tab = "base"

    def _action_card(self, key):
        f, lay = card("Action")
        a = key.get("action") if key else None
        pick = fit_combo(QComboBox())
        pick.addItem("Choose an action…" if not a else "", None)
        for cat, ids in actions.CATEGORIES:
            for aid in ids:
                m = actions.ACTIONS[aid]
                pick.addItem(icons.glyph_icon(m["glyph"], 16, "#cfcfd8"), m["name"], aid)
        if a:
            pick.removeItem(0)
            pick.setCurrentIndex(max(0, pick.findData(a["type"])))
        pick.activated.connect(lambda i: self._set_action(pick.itemData(i)))
        compact_combo(pick, 200)
        lay.addWidget(pick, 0, Qt.AlignmentFlag.AlignLeft)
        if a and a["type"] in actions.ACTIONS:
            meta = actions.ACTIONS[a["type"]]
            if meta["fields"]:
                lay.addSpacing(4)
                lay.addWidget(forms.build_form(a, self._param, self.engine))
            elif a["type"] == "folder":
                fid = a["params"].get("folder")
                n = len(self.engine.profile["folders"].get(fid, {}).get("keys", {}))
                open_btn = QPushButton("  Open folder")
                open_btn.setIcon(icons.glyph_icon("folder", 16, "#d0d0d8"))
                open_btn.clicked.connect(lambda: self.engine.open_folder(fid))
                inside = QLabel(f"{n} key{'s' if n != 1 else ''} inside. Open it to arrange the keys within.")
                inside.setWordWrap(True)
                lay.addWidget(inside)
                lay.addWidget(open_btn)
            else:
                d = QLabel(meta["desc"])
                d.setObjectName("muted")
                d.setWordWrap(True)
                lay.addWidget(d)
        if a and self.idx >= 0 and not self.engine.is_locked(self.idx):
            lay.addSpacing(6)
            lay.addWidget(self._hold_section(key))
        lay.addStretch(1)
        return f

    def _hold_section(self, key):
        """Optional second action that runs when the key is held instead of tapped."""
        e = self.engine
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(6)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{style.BORDER};")
        v.addWidget(sep)
        h = (key or {}).get("hold")
        ms = e.settings.get("hold_ms", 500)
        if not h:
            b = QPushButton("  Add hold action")
            b.setIcon(icons.glyph_icon("plus", 14, "#d0d0d8"))
            b.setToolTip(f"Run a second action when you hold the key for {ms / 1000:.1f} s. A quick tap still runs the main action.")
            m = QMenu(b)
            for cat, ids in actions.CATEGORIES:
                for aid in ids:
                    meta = actions.ACTIONS[aid]
                    if meta["multi"]:
                        m.addAction(icons.glyph_icon(meta["glyph"], 16, "#d0d0d8"), meta["name"]).triggered.connect(lambda _=False, aid=aid: self._set_hold(aid))
            b.setMenu(m)
            v.addWidget(b)
            return box
        head = QHBoxLayout()
        head.addWidget(forms.muted(f"WHEN HELD ({ms / 1000:.1f} S)"), 1)
        test = icon_btn("play", "Run the hold action now", 14)
        test.clicked.connect(lambda: e.trigger_hold(self.idx))
        head.addWidget(test)
        rm = icon_btn("x", "Remove the hold action", 14)
        rm.clicked.connect(lambda: e.set_hold(self.idx, None))
        head.addWidget(rm)
        v.addLayout(head)
        pick = fit_combo(QComboBox())
        for cat, ids in actions.CATEGORIES:
            for aid in ids:
                meta = actions.ACTIONS[aid]
                if meta["multi"]:
                    pick.addItem(icons.glyph_icon(meta["glyph"], 16, "#cfcfd8"), meta["name"], aid)
        if h["type"] in ("counter_reset", "timer_reset"):
            pick.addItem(icons.glyph_icon("refresh", 16, "#cfcfd8"), actions.ACTIONS[h["type"]]["name"], h["type"])
        pick.setCurrentIndex(max(0, pick.findData(h["type"])))
        pick.activated.connect(lambda i: self._set_hold(pick.itemData(i)))
        v.addWidget(pick)
        meta = actions.ACTIONS.get(h["type"], {})
        if meta.get("fields"):
            v.addWidget(forms.build_form(h, self._hold_param, e))
        return box

    def _set_hold(self, aid):
        if aid:
            self.engine.set_hold(self.idx, actions.default_action(aid))

    def _hold_param(self, key, value):
        self._editing = True
        self.engine.quiet_flash = True
        try:
            self.engine.edit_hold_params(self.idx, coalesce=f"h:{self.idx}:{key}", **{key: value})
        finally:
            self._editing = False
            self.engine.quiet_flash = False

    # ---- edits --------------------------------------------------------------------
    def _set_action(self, aid):
        if aid:
            self.engine.assign_action(self.idx, aid)

    def _param(self, key, value):
        self._editing = True
        self.engine.quiet_flash = True
        try:
            self.engine.edit_params(self.idx, coalesce=f"p:{self.idx}:{key}", **{key: value})
            k = self.engine.get_key(self.idx)
            if key == "app" and k:
                self._auto_icon_for_app(value, k)
        finally:
            self._editing = False
            self.engine.quiet_flash = False
        k = self.engine.get_key(self.idx)
        if k and k.get("action") and hasattr(self, "h_sub"):
            self.h_sub.setText(actions.describe(k["action"]))

    def _auto_icon_for_app(self, app_id, k):
        ic = k.get("icon")
        if ic and not ic.get("auto"):
            return
        a = icons.find_app(app_id)
        if a and a["icon"]:
            kind = "file" if a["icon"].startswith("/") else "theme"
            self.engine.edit_key(self.idx, coalesce=f"k:{self.idx}:icon", icon={"kind": kind, "value": a["icon"], "auto": True})
        else:
            self.engine.edit_key(self.idx, coalesce=f"k:{self.idx}:icon", icon=None)

    def _choose_icon(self):
        spec = pick_icon(self.window())
        if spec:
            self._edit(None, icon=spec)
            self._built_for = None
            self.rebuild()

    def _reset_icon(self):
        self._edit(None, icon=None)
        self._built_for = None
        self.rebuild()

    def _update_face(self):
        if hasattr(self, "face") and self.idx >= 0 and self.stack.currentIndex() == 1:
            try:
                self.face.set_face(self.engine.render(self.idx, 176, state=(True if self.tab == "alt" else (False if render.has_states(self.engine.get_key(self.idx)) else None))))
            except RuntimeError:
                pass
