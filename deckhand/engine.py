"""Central controller: profile state, navigation, undo, device sync and key dispatch."""
import copy
import json
import os
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter

from . import actions, autoswitch, backup, errors, hardware, model, motion, render, sounds, sysinfo, templates, trouble, wallpaper


class Engine(QObject):
    changed = pyqtSignal()            # structure or location changed: rebuild views
    key_changed = pyqtSignal(int)     # one key face changed
    device_changed = pyqtSignal()
    status = pyqtSignal(object)       # device info dict (see hardware._info)
    key_state = pyqtSignal(int, bool)
    error = pyqtSignal(str)
    settings_changed = pyqtSignal()
    request = pyqtSignal(str, object)
    agent_event = pyqtSignal(str)
    auto_switched = pyqtSignal(str)   # human text: what was switched and why
    hold_fired = pyqtSignal(int)      # a key was held long enough to run its hold action
    wall_frame = pyqtSignal()         # the animated wallpaper advanced one frame
    anim_changed = pyqtSignal()       # animation loading state changed

    _s_connect = pyqtSignal(object)
    _s_disconnect = pyqtSignal()
    _s_key = pyqtSignal(int, bool)
    _s_status = pyqtSignal(object)
    _s_live = pyqtSignal(object)
    _s_anim = pyqtSignal(int, object, str)

    def __init__(self):
        super().__init__()
        self.settings = model.Settings()
        motion.set_enabled(self.settings.get("animations", True))
        self.quiet_flash = False
        self.store = model.Store()
        self.dev = None
        self.alive = True
        ld = self.settings.get("last_deck") or {}
        self.cols, self.rows = int(ld.get("cols", 5)), int(ld.get("rows", 3))
        self._had_connection = False
        self.profile = self.store.ensure(self.cols, self.rows)
        self.loc = {"page": 0, "folders": []}
        self._undo, self._redo = [], []
        self._last_coalesce, self._last_t = None, 0.0
        self._sent = {}
        self._pending = {}
        self._cv = threading.Condition()
        self._pool = ThreadPoolExecutor(max_workers=4)
        self._pressed = set()
        self._asleep = False
        self._last_activity = time.monotonic()
        self._depth = 0
        self._quiet = 0
        self._timers, self._hold_timers, self._held, self._down_at = {}, {}, set(), {}
        self._timer_flash, self._timer_alarms = {}, {}
        self._anim, self._anim_sig, self._anim_gen, self._anim_idx = None, None, 0, 0
        self._anim_t0 = time.monotonic()
        self.anim_state = {"state": "none"}
        self._overlay_cache = {}
        self.ui_visible = True
        self.live = {}
        self._live_wanted = set()
        self._live_evt = threading.Event()
        self._toggled = {}
        self.firmware = ""

        self._save_failed = False
        self._save_timer = QTimer(self, singleShot=True, interval=300)
        self._save_timer.timeout.connect(self._save)
        self._tick = QTimer(self, interval=1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self._s_connect.connect(self._on_connect)
        self._s_disconnect.connect(self._on_disconnect)
        self._s_key.connect(self._on_key)
        self._s_status.connect(self._on_status)
        self._s_live.connect(self._on_live)
        self._s_anim.connect(self._on_anim)
        self._anim_timer = QTimer(self, interval=83)
        self._anim_timer.timeout.connect(self._anim_tick)
        self.request.connect(self._on_request)
        self.conn_info = dict(trouble.SCANNING)

        threading.Thread(target=self._writer, daemon=True).start()
        threading.Thread(target=self._live_loop, daemon=True).start()
        self.windows = autoswitch.WindowWatcher()
        self._win_timer = QTimer(self, singleShot=True, interval=140)
        self._win_timer.timeout.connect(self._apply_window)
        self.windows.activeChanged.connect(lambda _w: self._win_timer.start())
        self._sync_watcher()
        self.manager = hardware.Manager(self._s_connect.emit, self._s_disconnect.emit, self._s_key.emit, self._s_status.emit)

    def _save(self):
        try:
            self.store.save()
            if self._save_failed:
                self._save_failed = False
                errors.report("Saved. Your changes are safe again.", "ok")
        except Exception as e:
            if not self._save_failed:
                errors.report(errors.explain(e, "Could not save your changes") + ". Deckhand will keep retrying.", "error", exc=e)
            self._save_failed = True
            self._save_timer.start(10000)

    def startup_notices(self):
        """Problems found while loading data; shown once the window is up."""
        out = []
        for p in (self.store.problem, getattr(self.settings, "problem", None)):
            if p:
                out.append(("error", p + " Started with fresh defaults."))
        out += [("warn", n) for n in self.store.notes]
        return out

    def start(self):
        self.manager.start()

    def shutdown(self):
        self.alive = False
        self._save_timer.stop()
        self._anim_gen += 1
        self._anim_timer.stop()
        self.windows.stop()
        try:
            self.store.save()
            self.settings.save()
        except Exception as e:
            errors.log(f"final save failed: {e!r}")
        dev = self.dev
        self.manager.stop()
        if dev:
            try:
                dev.reset()
            except Exception:
                pass

    # ---- accessors -------------------------------------------------------------------
    @property
    def container(self):
        return model.container(self.profile, self.loc)

    @property
    def in_folder(self):
        return model.in_folder(self.profile, self.loc)

    @property
    def n_keys(self):
        return self.cols * self.rows

    def get_key(self, idx):
        if self.in_folder and idx == 0:
            return model.BACK_KEY
        return self.container["keys"].get(str(idx))

    def is_locked(self, idx):
        return self.in_folder and idx == 0

    def _with_runtime(self, idx, k):
        """Copy of the key with live runtime values (timer clock) merged into its action params."""
        a = (k or {}).get("action")
        if a and a["type"] == "nowplaying":
            k2 = dict(k)
            k2["action"] = {"type": "nowplaying", "params": {**a["params"], "_np": self.live.get("nowplaying") or {}}}
            return k2
        if not a or a["type"] != "timer":
            return k
        v = self._timer_value(idx, a["params"])
        k2 = dict(k)
        k2["action"] = {"type": "timer", "params": {**a["params"], "_run": v}}
        return k2

    DONE_FLASH_S = 3.0

    @staticmethod
    def _timer_total(params):
        """Countdown length in seconds (never less than one)."""
        try:
            return max(1, int(params.get("minutes", 25)) * 60 + int(params.get("seconds", 0)))
        except (TypeError, ValueError):
            return 25 * 60

    def _timer_value(self, idx, params):
        return self._tv(self._tkey(idx), params)

    def _tv(self, tk, params):
        now = time.monotonic()
        t = self._timers.get(tk)
        elapsed = (t["acc"] + (now - t["t0"] if t["t0"] is not None else 0.0)) if t else 0.0
        running = bool(t and t["t0"] is not None)
        if params.get("mode") == "countdown":
            total = self._timer_total(params)
            if self._timer_flash.get(tk, 0) > now or (running and elapsed >= total):
                return {"seconds": 0, "running": False, "done": True, "idle": False}
            idle = not running and elapsed == 0
            return {"seconds": total if idle else max(0.0, total - elapsed), "running": running, "done": False, "idle": idle}
        return {"seconds": elapsed, "running": running, "done": False, "idle": not running and elapsed == 0}

    # -- countdown completion: sound, notice, then the timer resets itself ----------------------
    def _arm_alarm(self, tk):
        self._disarm(tk)
        tm = self._timers.get(tk)
        p = (tm or {}).get("params") or {}
        if not tm or tm["t0"] is None or p.get("mode") != "countdown":
            return
        remaining = self._timer_total(p) - tm["acc"] - (time.monotonic() - tm["t0"])
        t = QTimer(self, singleShot=True)
        t.timeout.connect(lambda: self._alarm_fired(tk))
        self._timer_alarms[tk] = t
        t.start(max(0, int(remaining * 1000) + 30))

    def _disarm(self, tk):
        t = self._timer_alarms.pop(tk, None)
        if t:
            t.stop()
            t.deleteLater()

    def _alarm_fired(self, tk):
        tm = self._timers.get(tk)
        if not tm or tm["t0"] is None:
            return
        p = tm.get("params") or {}
        if tm["acc"] + time.monotonic() - tm["t0"] >= self._timer_total(p) - 0.005:
            self._finish_timer(tk)
        else:
            self._arm_alarm(tk)

    def _finish_timer(self, tk):
        tm = self._timers.pop(tk, None)
        self._disarm(tk)
        if not tm:
            return
        p = tm.get("params") or {}
        self._timer_flash[tk] = time.monotonic() + self.DONE_FLASH_S
        QTimer.singleShot(int(self.DONE_FLASH_S * 1000) + 60, self._refresh_timer_keys)
        if not sounds.play(p.get("sound", "default"), p.get("volume", 80)):
            errors.report("The timer finished, but no sound could be played (no audio output found).", "warn", once_key="timer-sound", cooldown=120)
        _, missing = sounds.resolve(p.get("sound", "default"))
        if missing:
            errors.report("The timer's custom sound file is gone, so the default chime played instead.", "warn", once_key="timer-sound-missing", cooldown=120)
        errors.report("Timer finished", "ok", once_key=f"timer-done-{tk}", cooldown=1.0)
        self._refresh_timer_keys()

    def _refresh_timer_keys(self):
        for i in range(self.n_keys):
            k = self.get_key(i)
            if k and (k.get("action") or {}).get("type") == "timer":
                self.push_key(i)
                self.key_changed.emit(i)

    def render(self, idx, size=72, pressed=False, state=None):
        k = self._with_runtime(idx, self.get_key(idx))
        try:
            st = self.look_state(idx) if state is None else state
            if self._anim and not pressed and self.key_uses_wallpaper(idx, st):
                return self._render_anim(idx, size, k, st)
            return render.render_key(k, size, pressed, st, self._backdrop(idx, size))
        except Exception as e:
            errors.report(f"Key {idx + 1} could not be drawn ({e.__class__.__name__}); it was replaced by a warning tile.",
                          "warn", exc=e, once_key=f"render-{self.profile['id']}-{idx}")
            return render.error_tile(size)

    # ---- animated wallpaper -----------------------------------------------------------------
    def key_uses_wallpaper(self, idx, state=None):
        if not self.profile.get("wallpaper"):
            return False
        k = self.get_key(idx)
        eff = render.effective(k, self.look_state(idx) if state is None else state) if k else None
        return str((eff or {}).get("bg", "#000000")).lower() == "#000000"

    def _anim_px(self):
        return self.dev.model.px if self.dev else 72

    def _anim_slice(self, idx, size):
        a = self._anim
        frame = a.frames[self._anim_idx % len(a.frames)]
        px = self._anim_px()
        gap = round(px * wallpaper.GAP_RATIO)
        c, r = idx % self.cols, idx // self.cols
        sl = frame.copy(c * (px + gap), r * (px + gap), px, px)
        if size != px:
            sl = sl.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return sl

    def _render_anim(self, idx, size, k, st):
        sl = self._anim_slice(idx, size)
        k = self._with_runtime(idx, k)
        a = (k or {}).get("action")
        dyn = bool(a and actions.ACTIONS.get(a["type"], {}).get("dynamic"))
        ck = (idx, size, json.dumps(k, sort_keys=True, default=str), st, int(time.time()) if dyn else 0)
        ov = self._overlay_cache.get(ck)
        if ov is None:
            ov = render.render_key(k, size, False, st, overlay=True)
            if len(self._overlay_cache) > 400:
                self._overlay_cache.clear()
            self._overlay_cache[ck] = ov
        p = QPainter(sl)
        p.drawImage(0, 0, ov)
        p.end()
        return sl

    def _sync_animation(self):
        """(Re)load the animated wallpaper when it, the deck size or its settings change."""
        wp = wallpaper.normalize(self.profile.get("wallpaper"))
        animated = bool(wp and wallpaper.animation_info(wp["file"])[0])
        want = wp if (wp and animated and wp["animate"]) else None
        px = self._anim_px()
        sig = None
        if want:
            try:
                mt = os.stat(want["file"]).st_mtime_ns
            except OSError:
                mt = 0
            sig = (want["file"], mt, want["fit"], want["zoom"], want["fx"], want["fy"], want["dim"], want["fps"], self.cols, self.rows, px)
        if sig == self._anim_sig:
            if not want:
                st = {"state": "paused" if animated else "none"}
                if st != self.anim_state:
                    self.anim_state = st
                    self.anim_changed.emit()
            return
        self._anim_sig = sig
        self._anim_gen += 1
        self._anim = None
        self._overlay_cache.clear()
        self._anim_timer.stop()
        if not want:
            self.anim_state = {"state": "paused" if animated else "none"}
            self.anim_changed.emit()
            return
        self.anim_state = {"state": "loading"}
        self.anim_changed.emit()
        gen, cols, rows = self._anim_gen, self.cols, self.rows

        def work():
            try:
                a = wallpaper.load_animation(want, cols, rows, px, lambda: gen != self._anim_gen)
                self._s_anim.emit(gen, a, "" if a else "The animation could not be decoded.")
            except Exception as e:
                self._s_anim.emit(gen, None, errors.explain(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_anim(self, gen, anim, err):
        if gen != self._anim_gen:
            return
        if anim is None:
            self.anim_state = {"state": "error", "error": err}
            errors.report(f"Animated wallpaper: {err} The first frame is shown instead.", "warn", once_key=f"anim-{self.profile['id']}", cooldown=120)
            self.anim_changed.emit()
            return
        self._anim, self._anim_idx, self._anim_t0 = anim, 0, time.monotonic()
        self.anim_state = {"state": "ready", "frames": len(anim.frames), "seconds": round(anim.loop_s, 1), "fps": anim.fps,
                           "truncated": anim.truncated, "source_frames": anim.source_frames}
        self._anim_timer.setInterval(max(20, int(1000 / anim.fps)))
        self._anim_timer.start()
        self.anim_changed.emit()
        self.push_all()
        self.wall_frame.emit()

    def _anim_tick(self):
        a = self._anim
        if not a:
            return
        on_deck = bool(self.dev) and not self._asleep
        if not (on_deck or self.ui_visible):
            return
        idx = int((time.monotonic() - self._anim_t0) * a.fps) % len(a.frames)
        if idx == self._anim_idx:
            return
        self._anim_idx = idx
        if on_deck and not self._pending:           # still sending the last frame: skip, never queue up lag
            for i in range(self.n_keys):
                if self.key_uses_wallpaper(i):
                    self.push_key(i, i in self._pressed and self.settings["pressed_effect"], quality=82)
        if self.ui_visible:
            self.wall_frame.emit()

    def _backdrop(self, idx, size):
        wp = self.profile.get("wallpaper")
        if not wp:
            return None
        if self._anim:
            return self._anim_slice(idx, size)
        bd = wallpaper.slice_for(wp, idx, self.cols, self.rows, size)
        if bd is None:
            errors.report("The deck wallpaper image can't be read any more; keys show plain backgrounds. Open Wallpaper to pick another.",
                          "warn", once_key=f"wp-{self.profile['id']}", cooldown=120)
        return bd

    def set_wallpaper(self, cfg, coalesce=None):
        """Set (dict) or remove (None) this profile's wallpaper. One undo step."""
        with self.mutate(coalesce):
            norm = wallpaper.normalize(cfg) if cfg else None
            if norm:
                self.profile["wallpaper"] = norm
            else:
                self.profile.pop("wallpaper", None)

    # ---- key states (live system state or press-toggled) -----------------------------
    def _tkey(self, idx):
        return (self.profile["id"], self.container["id"], idx)

    def look_state(self, idx):
        k = self.get_key(idx)
        if not render.has_states(k):
            return False
        src = actions.live_source(k.get("action"))
        if src:
            return bool(self.live.get(src, False))
        return self._toggled.get(self._tkey(idx), False)

    def _update_live_wanted(self):
        want = set()
        for i in range(self.n_keys):
            k = self.get_key(i)
            src = actions.live_source(k.get("action")) if k else None
            if src and render.has_states(k):
                want.add(src)
            if k and (k.get("action") or {}).get("type") == "nowplaying":
                want.add("nowplaying")
        if want and not self._live_wanted:
            self._live_evt.set()
        self._live_wanted = want

    def _live_loop(self):
        while self.alive:
            self._live_evt.wait(0.8)
            self._live_evt.clear()
            want = set(self._live_wanted)
            if not want or not self.alive:
                continue
            self._s_live.emit({n: sysinfo.read_live(n) for n in want})

    def _on_live(self, vals):
        changed = {n for n, v in vals.items() if self.live.get(n) != v}
        self.live.update(vals)
        if not changed:
            return
        for i in range(self.n_keys):
            k = self.get_key(i)
            if k and (actions.live_source(k.get("action")) in changed
                      or ((k.get("action") or {}).get("type") == "nowplaying" and "nowplaying" in changed)):
                self.push_key(i)
                self.key_changed.emit(i)

    def edit_alt(self, idx, coalesce=None, remove=(), **fields):
        """Patch the key's alternate ("active") look; alt=None removes it."""
        if self.is_locked(idx):
            return
        with self.mutate(coalesce):
            k = self.container["keys"].get(str(idx))
            if not k:
                return
            alt = dict(k.get("alt") or {})
            alt.update(fields)
            for f in remove:
                alt.pop(f, None)
            k["alt"] = alt or None
            if not alt:
                k.pop("alt", None)

    def crumbs(self):
        out = [self.profile["name"]]
        pages = self.profile["pages"]
        out.append(pages[self.loc["page"]]["name"] if len(pages) > 1 else None)
        for fid in self.loc["folders"]:
            f = self.profile["folders"].get(fid)
            out.append(f["name"] if f else "?")
        return [c for c in out if c]

    # ---- mutation / undo ---------------------------------------------------------------
    @contextmanager
    def mutate(self, coalesce=None):
        """One undo step. Nested calls fold into the outermost one."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        now = time.monotonic()
        if not (coalesce and coalesce == self._last_coalesce and now - self._last_t < 1.5):
            self._undo.append((json.dumps(self.profile), copy.deepcopy(self.loc)))
            del self._undo[:-100]
            self._redo.clear()
        self._last_coalesce, self._last_t = coalesce, now
        self._depth = 1
        try:
            yield
        finally:
            self._depth = 0
            model.gc_folders(self.profile)
            self._touched()

    @contextmanager
    def at(self, profile, loc):
        """Temporarily edit another profile/page/folder without moving the user's view or the deck."""
        saved = (self.profile, self.loc, self._undo, self._redo)
        other = profile is not self.profile
        self.profile, self.loc = profile, copy.deepcopy(loc)
        if other:
            self._undo, self._redo = [], []
        self._quiet += 1
        try:
            yield
        finally:
            self._quiet -= 1
            if other:
                self._undo, self._redo = saved[2], saved[3]
            self.profile, self.loc = saved[0], saved[1]
            self._fix_loc()
            self._touched()

    def _touched(self, full=True):
        self._save_timer.start()
        if self._quiet:
            return
        self.push_all()
        if full:
            self.changed.emit()

    def _restore(self, snap):
        data, loc = snap
        self.profile.clear()
        self.profile.update(json.loads(data))
        self.loc = loc
        self._fix_loc()
        self._touched()

    def undo(self):
        if not self._undo:
            return
        self._redo.append((json.dumps(self.profile), copy.deepcopy(self.loc)))
        self._restore(self._undo.pop())
        self._last_coalesce = None

    def redo(self):
        if not self._redo:
            return
        self._undo.append((json.dumps(self.profile), copy.deepcopy(self.loc)))
        self._restore(self._redo.pop())
        self._last_coalesce = None

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def _fix_loc(self):
        self.loc["folders"] = [f for f in self.loc["folders"] if f in self.profile["folders"]]
        self.loc["page"] = max(0, min(self.loc["page"], len(self.profile["pages"]) - 1))

    # ---- key editing -------------------------------------------------------------------
    def set_key(self, idx, key, coalesce=None):
        if self.is_locked(idx):
            return
        with self.mutate(coalesce):
            if model.key_is_empty(key):
                self.container["keys"].pop(str(idx), None)
            else:
                self.container["keys"][str(idx)] = key

    def edit_key(self, idx, coalesce=None, **fields):
        """Patch top-level fields on a key (creating it if needed)."""
        if self.is_locked(idx):
            return
        with self.mutate(coalesce):
            k = self.container["keys"].get(str(idx)) or model.new_key()
            k.update(fields)
            if model.key_is_empty(k):
                self.container["keys"].pop(str(idx), None)
            else:
                self.container["keys"][str(idx)] = k

    def edit_params(self, idx, coalesce=None, **params):
        with self.mutate(coalesce):
            k = self.container["keys"].get(str(idx))
            if k and k.get("action"):
                k["action"]["params"].update(params)

    def assign_action(self, idx, aid):
        if self.is_locked(idx):
            return
        with self.mutate():
            k = self.container["keys"].get(str(idx)) or model.new_key()
            old = k.get("action")
            k["action"] = actions.default_action(aid)
            self._auto_hold(k, aid)
            if aid == "folder":
                fid = model.new_id()
                self.profile["folders"][fid] = {"id": fid, "name": "Folder", "keys": {}}
                k["action"]["params"]["folder"] = fid
                if not k.get("title"):
                    k["title"] = "Folder"
            elif old and old.get("type") == "folder" and k.get("title") == "Folder":
                k["title"] = ""
            self.container["keys"][str(idx)] = k

    KEY_FIELDS = ("alt", "hold", "title", "show_title", "title_pos", "title_size", "title_color", "bold", "icon", "icon_color", "bg")

    def apply_key_patch(self, idx, patch):
        """Atomic, pre-validated key edit used by agents. Returns {"folder": id} if a folder was created."""
        out = {}
        with self.mutate():
            k = self.container["keys"].get(str(idx)) or model.new_key()
            if "action" in patch:
                a = patch["action"]
                if a is None:
                    k["action"] = None
                else:
                    a = {"type": a["type"], "params": dict(a.get("params", {}))}
                    if a["type"] == "folder":
                        fid = a["params"].pop("folder", None)
                        name = a["params"].pop("name", None)
                        if fid not in self.profile["folders"]:
                            fid = model.new_id()
                            self.profile["folders"][fid] = {"id": fid, "name": name or patch.get("title") or k.get("title") or "Folder", "keys": {}}
                            out["folder"] = fid
                        elif name:
                            self.profile["folders"][fid]["name"] = name
                        a["params"] = {"folder": fid}
                        if not k.get("title") and "title" not in patch:
                            k["title"] = self.profile["folders"][fid]["name"]
                    k["action"] = a
                    self._auto_hold(k, a["type"])
            for f in self.KEY_FIELDS:
                if f in patch:
                    k[f] = patch[f]
            if model.key_is_empty(k):
                self.container["keys"].pop(str(idx), None)
            else:
                self.container["keys"][str(idx)] = k
        return out

    @staticmethod
    def _auto_hold(k, aid):
        """Counter/timer keys get a hold-to-reset by default; switching away removes that default."""
        h = k.get("hold")
        if aid in ("counter", "timer"):
            if not h:
                k["hold"] = {"type": aid + "_reset", "params": {}}
        elif h and h.get("type") in ("counter_reset", "timer_reset"):
            k["hold"] = None

    def set_hold(self, idx, action, coalesce=None):
        """Set (dict) or remove (None) the hold action of a key."""
        if self.is_locked(idx):
            return
        with self.mutate(coalesce):
            k = self.container["keys"].get(str(idx)) or model.new_key()
            k["hold"] = action
            if model.key_is_empty(k):
                self.container["keys"].pop(str(idx), None)
            else:
                self.container["keys"][str(idx)] = k

    def edit_hold_params(self, idx, coalesce=None, **params):
        with self.mutate(coalesce):
            k = self.container["keys"].get(str(idx))
            if k and k.get("hold"):
                k["hold"]["params"].update(params)

    def assign_app(self, idx, app_id):
        """A key that launches an installed app, with the app's own icon."""
        from . import icons
        ap = icons.find_app(app_id)
        if self.is_locked(idx) or not ap:
            return
        with self.mutate():
            k = self.container["keys"].get(str(idx)) or model.new_key()
            k["action"] = actions.default_action("app")
            k["action"]["params"]["app"] = app_id
            self._auto_hold(k, "app")
            if ap["icon"] and not (k.get("icon") and not k["icon"].get("auto")):
                k["icon"] = {"kind": "file" if ap["icon"].startswith("/") else "theme", "value": ap["icon"], "auto": True}
            self.container["keys"][str(idx)] = k

    def clear_key(self, idx):
        if self.get_key(idx) and not self.is_locked(idx):
            self.set_key(idx, None)

    def move_key(self, src, dst, copy_it=False):
        if src == dst or self.is_locked(src) or self.is_locked(dst):
            return
        with self.mutate():
            keys = self.container["keys"]
            a, b = keys.get(str(src)), keys.get(str(dst))
            if copy_it:
                if a:
                    keys[str(dst)] = model.clone_key(self.profile, a)
                return
            for i, v in ((dst, a), (src, b)):
                if v:
                    keys[str(i)] = v
                else:
                    keys.pop(str(i), None)

    def paste_key(self, idx, key):
        if self.is_locked(idx) or not key:
            return
        with self.mutate():
            self.container["keys"][str(idx)] = model.clone_key(self.profile, key)

    def rename_container(self, name):
        with self.mutate("rename-container"):
            if self.in_folder:
                self.profile["folders"][self.loc["folders"][-1]]["name"] = name
            else:
                self.container["name"] = name

    # ---- pages / profiles -------------------------------------------------------------
    def add_page(self):
        with self.mutate():
            self.profile["pages"].append(model.new_page(f"Page {len(self.profile['pages']) + 1}"))
            self.loc = {"page": len(self.profile["pages"]) - 1, "folders": []}

    def add_template_page(self, tid):
        if tid not in templates.TEMPLATES:
            raise ValueError(f"unknown template '{tid}'")
        with self.mutate():
            self.profile["pages"].append(templates.build_page(tid, self.cols, self.rows))
            self.loc = {"page": len(self.profile["pages"]) - 1, "folders": []}

    def duplicate_page(self, i):
        with self.mutate():
            src = self.profile["pages"][i]
            new = model.copy_page(self.profile, src, self.profile)
            new["name"] = src["name"] + " copy"
            self.profile["pages"].insert(i + 1, new)
            self.loc = {"page": i + 1, "folders": []}

    def move_page(self, i, d):
        j = i + d
        pages = self.profile["pages"]
        if not 0 <= j < len(pages):
            return
        with self.mutate():
            pages[i], pages[j] = pages[j], pages[i]
            if not self.in_folder and self.loc["page"] == i:
                self.loc["page"] = j

    def copy_page_to_profile(self, i, pid):
        dst = self.store.get(pid)
        if not dst or dst is self.profile or (dst["cols"], dst["rows"]) != (self.cols, self.rows):
            raise ValueError("pick another profile made for this deck")
        src = self.profile["pages"][i]
        with self.at(dst, {"page": 0, "folders": []}):
            with self.mutate():
                new = model.copy_page(self.profile_of(src), src, dst)
                new["name"] = src["name"]
                dst["pages"].append(new)
        return dst["name"]

    def profile_of(self, page):
        for p in self.store.profiles:
            if any(pg is page for pg in p["pages"]):
                return p
        return self.profile

    def move_key_from(self, src_loc, src_idx, dst_idx, copy_it=False):
        """Move/copy a key between containers of the current profile (drag a key to another page)."""
        src = model.container(self.profile, src_loc)
        if self.is_locked(dst_idx) or (model.in_folder(self.profile, src_loc) and src_idx == 0):
            return
        with self.mutate():
            keys = src["keys"]
            a = keys.get(str(src_idx))
            if not a:
                return
            dst = self.container["keys"]
            b = dst.get(str(dst_idx))
            dst[str(dst_idx)] = model.clone_key(self.profile, a) if copy_it else a
            if not copy_it:
                if b:
                    keys[str(src_idx)] = b
                else:
                    keys.pop(str(src_idx), None)

    def move_key_to_page(self, idx, page_i):
        """Drop a key on a page tab: it goes to the first free slot of that page."""
        pages = self.profile["pages"]
        if not 0 <= page_i < len(pages) or self.is_locked(idx):
            return False
        target = pages[page_i]
        free = next((s for s in range(self.n_keys) if str(s) not in target["keys"]), None)
        if free is None:
            errors.report(f"Page {page_i + 1} is full.", "warn")
            return False
        with self.mutate():
            k = self.container["keys"].pop(str(idx), None)
            if k:
                target["keys"][str(free)] = k
        return True

    def delete_page(self, i):
        if len(self.profile["pages"]) <= 1:
            return
        with self.mutate():
            del self.profile["pages"][i]
            self._fix_loc()

    def goto_page(self, i):
        self.loc = {"page": max(0, min(i, len(self.profile["pages"]) - 1)), "folders": []}
        self._nav_done()

    def step_page(self, d):
        if not self.in_folder:
            self.goto_page(self.loc["page"] + d)

    def open_folder(self, fid):
        if fid in self.profile["folders"]:
            self.loc["folders"].append(fid)
            self._nav_done()

    def go_back(self):
        if self.loc["folders"]:
            self.loc["folders"].pop()
            self._nav_done()

    def go_up_to(self, depth):
        del self.loc["folders"][depth:]
        self._nav_done()

    def _nav_done(self):
        self.push_all()
        self.changed.emit()

    def switch_profile(self, pid):
        p = self.store.get(pid)
        if not p or p is self.profile:
            return
        if (p["cols"], p["rows"]) != (self.cols, self.rows):
            return
        self.profile = p
        self.store.data["current"] = pid
        self.loc = {"page": 0, "folders": []}
        self._undo.clear()
        self._redo.clear()
        self._save_timer.start()
        self.push_all()
        self.changed.emit()

    def profiles(self):
        return self.store.for_size(self.cols, self.rows)

    def new_profile(self, name):
        p = model.new_profile(name, self.cols, self.rows)
        self.store.profiles.append(p)
        self.switch_profile(p["id"])

    def duplicate_profile(self):
        p = model.clone_profile(self.profile, self.profile["name"] + " copy")
        self.store.profiles.append(p)
        self.switch_profile(p["id"])

    def rename_profile(self, name):
        self.profile["name"] = name
        self._save_timer.start()
        self.changed.emit()

    def delete_profile(self):
        sibs = self.profiles()
        if len(sibs) <= 1:
            return False
        victim = self.profile
        other = next(p for p in sibs if p is not victim)
        self.switch_profile(other["id"])
        self.store.profiles.remove(victim)
        self._save_timer.start()
        self.changed.emit()
        return True

    def import_profile(self, data):
        p = model.sanitize_profile(data, {x["id"] for x in self.store.profiles})
        if p is None:
            raise ValueError("this is not a valid Deckhand profile")
        p["id"] = model.new_id()
        self.store.profiles.append(p)
        if (p["cols"], p["rows"]) == (self.cols, self.rows):
            self.switch_profile(p["id"])
        else:
            self._save_timer.start()
            self.changed.emit()

    # ---- settings ----------------------------------------------------------------------
    def set_setting(self, key, value):
        self.settings[key] = value
        errors.guard(self.settings.save, "Could not save settings")
        if key == "animations":
            motion.set_enabled(value)
        if key in ("brightness", "night"):
            self._apply_brightness()
        self.settings_changed.emit()

    # ---- device ------------------------------------------------------------------------
    def _dev_call(self, fn):
        dev = self.dev
        if dev:
            threading.Thread(target=lambda: self._safe(fn, dev), daemon=True).start()

    @staticmethod
    def _safe(fn, dev):
        try:
            fn(dev)
        except Exception:
            pass

    @property
    def conn_state(self):
        return (self.conn_info.get("state", "scanning"), self.conn_info.get("title", ""))

    def _on_status(self, info):
        self.conn_info = info
        self.status.emit(info)

    # ---- auto-switch by window -------------------------------------------------------------
    def _sync_watcher(self):
        if self.settings["auto_switch"]["enabled"]:
            self.windows.start()
        else:
            self.windows.stop()

    def set_auto_switch(self, cfg):
        self.settings["auto_switch"] = autoswitch.clean_config(cfg)
        errors.guard(self.settings.save, "Could not save settings")
        self._sync_watcher()
        self.settings_changed.emit()
        if self.settings["auto_switch"]["enabled"]:
            self._win_timer.start()

    def _apply_window(self):
        cfg = self.settings["auto_switch"]
        win = self.windows.active
        if not cfg["enabled"] or not win or autoswitch.is_own_window(win):
            return
        rule = autoswitch.match_rule(cfg, win)
        pid = rule["profile"] if rule else cfg.get("default", "")
        target = self.store.get(pid) if pid else None
        if not target or target is self.profile or (target["cols"], target["rows"]) != (self.cols, self.rows):
            return
        self.switch_profile(target["id"])
        self.auto_switched.emit(f"Switched to {target['name']}  ·  {autoswitch.window_label(win)}")

    def retry_device(self):
        self.manager.retry()

    def choose_device(self, serial):
        self.settings["preferred_serial"] = serial
        errors.guard(self.settings.save, "Could not save settings")
        self.manager.preferred = serial
        self.manager.reconnect()

    def close_rival(self, pid):
        """Politely ask another Stream Deck program (that holds the deck) to quit."""
        import os
        import signal
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as e:
            errors.report(errors.explain(e, "Could not close it"), "error", exc=e)
        QTimer.singleShot(1200, self.manager.retry)
        QTimer.singleShot(3000, self.manager.retry)

    def _on_connect(self, dev):
        self.dev = dev
        m = dev.model
        self.settings["last_deck"] = {"cols": m.cols, "rows": m.rows, "model": m.name}
        errors.guard(self.settings.save, "Could not save settings")
        if self._had_connection:
            errors.report("Stream Deck reconnected.", "ok")
        self._had_connection = True
        if (m.cols, m.rows) != (self.cols, self.rows):
            self.cols, self.rows = m.cols, m.rows
            self.profile = self.store.ensure(m.cols, m.rows)
            self.loc = {"page": 0, "folders": []}
            self._undo.clear()
            self._redo.clear()
        self._sent.clear()
        self._asleep = False
        self._last_activity = time.monotonic()
        self.firmware = ""
        self._applied_bright = self.effective_brightness()
        self._dev_call(lambda d: d.set_brightness(self._applied_bright))
        self.push_all()
        self.device_changed.emit()
        self.changed.emit()

    def _on_disconnect(self):
        if self.dev is not None and self.alive:
            errors.report("Stream Deck disconnected. Deckhand reconnects automatically when it is back.", "warn")
        self.dev = None
        with self._cv:
            self._pending.clear()
        self.device_changed.emit()

    def _writer(self):
        while True:
            with self._cv:
                while not self._pending:
                    self._cv.wait()
                batch, self._pending = self._pending, {}
            dev = self.dev
            if not dev:
                continue
            failed = False
            for idx, jpeg in batch.items():
                if failed:
                    self._sent.pop(idx, None)
                    continue
                try:
                    dev.set_key_image(idx, jpeg)
                except Exception:
                    failed = True
                    self._sent.pop(idx, None)

    def push_key(self, idx, pressed=False, force=False, quality=92):
        if not self.dev or idx >= self.dev.model.keys:
            return
        img = self.render(idx, self.dev.model.px, pressed)
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        sig = (zlib.crc32(bytes(ptr)), pressed)
        if not force and self._sent.get(idx) == sig:
            return
        self._sent[idx] = sig
        jpeg = render.to_jpeg(img, quality)
        with self._cv:
            self._pending[idx] = jpeg
            self._cv.notify()

    def push_all(self):
        self._overlay_cache.clear()
        self._sync_animation()
        self._update_live_wanted()
        if self._asleep:
            return
        for i in range(self.n_keys):
            self.push_key(i, i in self._pressed and self.settings["pressed_effect"])

    def _on_tick(self):
        now = time.monotonic()
        for tk, tm in list(self._timers.items()):          # safety net in case an alarm was missed (e.g. after suspend)
            p = tm.get("params") or {}
            if tm["t0"] is not None and p.get("mode") == "countdown" and tm["acc"] + now - tm["t0"] >= self._timer_total(p):
                self._finish_timer(tk)
        dyn = False
        for i in range(self.n_keys):
            k = self.get_key(i)
            a = k.get("action") if k else None
            if a and actions.ACTIONS.get(a["type"], {}).get("dynamic"):
                dyn = True
                self.push_key(i)
                self.key_changed.emit(i)
        self._apply_brightness()
        mins = self.settings["sleep_minutes"]
        if self.dev and mins and not self._asleep and time.monotonic() - self._last_activity > mins * 60:
            self._asleep = True
            self._dev_call(lambda d: d.set_brightness(0))

    def effective_brightness(self):
        n = self.settings["night"]
        if n["enabled"]:
            lt = time.localtime()
            cur = lt.tm_hour * 60 + lt.tm_min
            s = int(n["start"][:2]) * 60 + int(n["start"][3:])
            e = int(n["end"][:2]) * 60 + int(n["end"][3:])
            inside = (s <= cur < e) if s <= e else (cur >= s or cur < e)
            if inside:
                return n["brightness"]
        return self.settings["brightness"]

    def _apply_brightness(self):
        b = self.effective_brightness()
        if b != getattr(self, "_applied_bright", None) and self.dev and not self._asleep:
            self._applied_bright = b
            self._dev_call(lambda d: d.set_brightness(b))

    def apply_restore(self, path):
        """Restore from a backup file and reload everything live."""
        self._save_timer.stop()
        info = backup.restore_backup(path)
        self.reload()
        return info

    def reload(self):
        """Re-read profiles and settings from disk (after a restore)."""
        self._save_timer.stop()
        self.store = model.Store()
        fresh = model.Settings()
        self.settings.clear()
        self.settings.update(fresh)
        motion.set_enabled(self.settings.get("animations", True))
        self.profile = self.store.ensure(self.cols, self.rows)
        self.loc = {"page": 0, "folders": []}
        self._undo.clear()
        self._redo.clear()
        self._sync_watcher()
        self.push_all()
        self.settings_changed.emit()
        self.changed.emit()

    def _wake(self):
        self._asleep = False
        self._last_activity = time.monotonic()
        b = self.effective_brightness()
        self._applied_bright = b
        self._dev_call(lambda d: d.set_brightness(b))
        self.push_all()

    # ---- key events --------------------------------------------------------------------
    def _on_key(self, idx, down):
        self._last_activity = time.monotonic()
        if self._asleep:
            if down:
                self._wake()
            return
        self.key_state.emit(idx, down)
        if down:
            self._pressed.add(idx)
        else:
            self._pressed.discard(idx)
        if self.settings["pressed_effect"]:
            self.push_key(idx, down)
        k = self.get_key(idx)
        has_hold = bool(k and (k.get("hold") or self._builtin_hold(k)))
        if down:
            self._down_at[idx] = time.monotonic()
            if has_hold:
                t = QTimer(self, singleShot=True, interval=int(self.settings.get("hold_ms", 500)))
                t.timeout.connect(lambda i=idx: self._fire_hold(i))
                self._hold_timers[idx] = t
                t.start()
            else:
                self.trigger(idx)
        else:
            t = self._hold_timers.pop(idx, None)
            if t:
                t.stop()
                t.deleteLater()
            if idx in self._held:
                self._held.discard(idx)
            elif has_hold and idx in self._down_at:
                self.trigger(idx)             # a quick tap on a key that also has a hold action
            self._down_at.pop(idx, None)

    def _fire_hold(self, idx):
        if idx not in self._pressed:
            return
        self._held.add(idx)
        self.trigger_hold(idx)
        self.hold_fired.emit(idx)

    @staticmethod
    def _builtin_hold(k):
        """Now Playing keys skip to the next track on hold unless turned off or given their own hold action."""
        a = k.get("action") or {}
        if a.get("type") == "nowplaying" and a.get("params", {}).get("hold_next", True):
            return {"type": "next", "params": {}}
        return None

    def trigger_hold(self, idx):
        k = self.get_key(idx)
        h = (k.get("hold") or self._builtin_hold(k)) if k else None
        if h:
            self._run_action(idx, copy.deepcopy(h))

    LOCAL = ("counter", "timer", "counter_reset", "timer_reset")

    def _local(self, idx, a):
        """Counter and timer live in the editor's data, so they run on the main thread."""
        t, k = a["type"], self.get_key(idx)
        if not k:
            return
        act = k.get("action") or {}
        p = act.get("params", {})
        if t == "counter":
            lo, hi = -1000000, 1000000
            p["value"] = max(lo, min(hi, int(p.get("value", 0)) + int(p.get("step", 1))))
        elif t == "counter_reset" and act.get("type") == "counter":
            p["value"] = 0
        elif t == "timer":
            tk = self._tkey(idx)
            tm = self._timers.setdefault(tk, {"acc": 0.0, "t0": None})
            tm["params"] = p
            self._timer_flash.pop(tk, None)
            if tm["t0"] is None:
                tm["t0"] = time.monotonic()
                self._arm_alarm(tk)
            else:
                tm["acc"] += time.monotonic() - tm["t0"]
                tm["t0"] = None
                self._disarm(tk)
        elif t == "timer_reset":
            tk = self._tkey(idx)
            self._timers.pop(tk, None)
            self._timer_flash.pop(tk, None)
            self._disarm(tk)
        self._save_timer.start()
        self.push_key(idx)
        self.key_changed.emit(idx)

    def _run_action(self, idx, a):
        if a["type"] in self.LOCAL:
            self._local(idx, a)
        else:
            self._pool.submit(self._exec, a)

    def trigger(self, idx):
        k = self.get_key(idx)
        a = k.get("action") if k else None
        if a and k.get("alt") and not actions.live_source(a):
            tk = self._tkey(idx)
            self._toggled[tk] = not self._toggled.get(tk, False)
            self.push_key(idx)
            self.key_changed.emit(idx)
        elif a and actions.live_source(a):
            QTimer.singleShot(250, self._live_evt.set)
            QTimer.singleShot(900, self._live_evt.set)
        if a:
            self._run_action(idx, copy.deepcopy(a))

    def _exec(self, action):
        try:
            actions.run(action, self)
        except Exception as e:
            errors.report(errors.explain(e), "error", exc=e)

    def _on_request(self, name, p):
        if name == "folder":
            self.open_folder(p.get("folder", ""))
        elif name == "back":
            self.go_back()
        elif name == "nextpage":
            self.step_page(1)
        elif name == "prevpage":
            self.step_page(-1)
        elif name == "profile":
            self.switch_profile(p.get("profile", ""))
        elif name == "brightness":
            cur = self.settings["brightness"]
            v = p.get("value", 10)
            mode = p.get("mode", "up")
            self.set_setting("brightness", max(5, min(100, cur + v if mode == "up" else cur - v if mode == "down" else v)))
