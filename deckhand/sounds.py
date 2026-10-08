"""Sounds for timers: a built-in chime (synthesised, no asset file), custom sound import, and playback.

Playback prefers Qt Multimedia (the default audio output); if that is unavailable it falls back to
whichever of pw-play / paplay / ffplay is installed, so it keeps working on minimal setups.
"""
import math
import os
import shutil
import struct
import subprocess
import wave

from . import model

SOUND_DIR = os.path.join(model.CONFIG_DIR, "sounds")
CACHE_DIR = os.path.expanduser("~/.cache/deckhand")
EXTS = (".wav", ".mp3", ".ogg", ".oga", ".opus", ".flac", ".m4a", ".aac")
MAX_BYTES = 10 * 1024 * 1024
RATE = 44100

_live = []   # keeps Qt players alive until they finish


# ---- the default chime -----------------------------------------------------------------------
def _bell(freq, length, rate=RATE):
    """One struck-bell note: a few inharmonic partials with different decay speeds and a 4 ms attack."""
    n = int(length * rate)
    out = []
    for i in range(n):
        t = i / rate
        s = 0.0
        for mult, amp, decay in ((1.0, 1.0, 3.2), (2.0, 0.45, 4.6), (2.76, 0.25, 6.5), (5.4, 0.08, 11.0)):
            s += amp * math.sin(2 * math.pi * freq * mult * t) * math.exp(-decay * t)
        out.append(s * min(1.0, t / 0.004))
    return out


def chime_samples():
    """Three ascending notes (E5, G5, C6), softly overlapping, normalised and faded out."""
    notes = ((659.25, 0.0), (783.99, 0.28), (1046.5, 0.56))
    total = int(RATE * 1.9)
    mix = [0.0] * total
    for f, at in notes:
        start = int(at * RATE)
        for i, v in enumerate(_bell(f, 1.3)):
            if start + i < total:
                mix[start + i] += v
    peak = max(abs(x) for x in mix) or 1.0
    fade = int(0.08 * RATE)
    for i in range(total):
        g = 0.8 / peak
        if i > total - fade:
            g *= (total - i) / fade
        mix[i] *= g
    return mix


def default_chime_path():
    """The chime as a WAV in the cache folder, (re)generated whenever it is missing."""
    path = os.path.join(CACHE_DIR, "timer-chime.wav")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    os.makedirs(CACHE_DIR, exist_ok=True)
    data = chime_samples()
    tmp = path + ".part"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, x)) * 32767)) for x in data))
    os.replace(tmp, path)
    return path


# ---- custom sounds ---------------------------------------------------------------------------
def import_sound(path):
    """Copy a user's sound into the config folder (so it survives the original moving). Returns the new path."""
    path = os.path.expanduser(str(path))
    if not os.path.isfile(path):
        raise ValueError("that file does not exist")
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXTS:
        raise ValueError(f"unsupported sound type '{ext or 'none'}'; use " + ", ".join(e[1:] for e in EXTS))
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError("that sound is larger than 10 MB")
    if os.path.getsize(path) == 0:
        raise ValueError("that sound file is empty")
    os.makedirs(SOUND_DIR, exist_ok=True)
    stem = "".join(c for c in os.path.splitext(os.path.basename(path))[0] if c.isalnum() or c in "-_ ")[:40].strip() or "sound"
    dest = os.path.join(SOUND_DIR, f"{stem}-{model.new_id()}{ext}")
    shutil.copyfile(path, dest)
    return dest


def label(spec):
    """Human name for a sound setting."""
    if spec in ("none", None):
        return "No sound"
    if spec in ("default", ""):
        return "Default chime"
    return os.path.splitext(os.path.basename(spec))[0].rsplit("-", 1)[0] or "Custom sound"


def resolve(spec):
    """(path or None, missing) for a sound setting: 'default', 'none' or a file path."""
    if spec in ("none", None):
        return None, False
    if spec in ("default", ""):
        return default_chime_path(), False
    if os.path.isfile(spec):
        return spec, False
    return default_chime_path(), True            # custom file vanished: fall back to the chime


# ---- playback --------------------------------------------------------------------------------
def _subprocess_play(path, vol):
    for cmd in (["pw-play", f"--volume={vol / 100:.2f}", path], ["paplay", f"--volume={int(65536 * vol / 100)}", path],
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", str(int(vol)), path]):
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return True
            except OSError:
                continue
    return False


def _qt_play(path, vol):
    try:
        from PyQt6.QtCore import QTimer, QUrl
        from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer, QSoundEffect
    except ImportError:
        return False
    if not QMediaDevices.audioOutputs():
        return False
    if path.lower().endswith(".wav"):
        fx = QSoundEffect()
        fx.setSource(QUrl.fromLocalFile(path))
        fx.setVolume(vol / 100.0)
        _live.append(fx)

        def done():
            if fx in _live:
                _live.remove(fx)

        def status():
            if fx.status() == QSoundEffect.Status.Error:
                done()
                _subprocess_play(path, vol)
        fx.statusChanged.connect(status)
        fx.playingChanged.connect(lambda: done() if not fx.isPlaying() and fx.status() == QSoundEffect.Status.Ready else None)
        fx.play()
        QTimer.singleShot(30000, done)
        return True
    player, out = QMediaPlayer(), QAudioOutput()
    player.setAudioOutput(out)
    out.setVolume(vol / 100.0)
    player.setSource(QUrl.fromLocalFile(path))
    entry = (player, out)
    _live.append(entry)

    def finish(*_):
        if entry in _live:
            _live.remove(entry)

    def media(st):
        if st in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            finish()
            if st == QMediaPlayer.MediaStatus.InvalidMedia:
                _subprocess_play(path, vol)
    player.mediaStatusChanged.connect(media)
    player.errorOccurred.connect(lambda *_: (finish(), _subprocess_play(path, vol)))
    player.play()
    QTimer.singleShot(120000, finish)
    return True


def play(spec="default", volume=80):
    """Play a sound setting. Returns False only if nothing could play it ('none' counts as success)."""
    path, missing = resolve(spec)
    if path is None:
        return True
    vol = max(5, min(100, int(volume)))
    try:
        ok = _qt_play(path, vol) or _subprocess_play(path, vol)
    except Exception:
        ok = _subprocess_play(path, vol)
    return ok
