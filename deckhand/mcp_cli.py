"""`deckhand mcp`: stdio MCP server entry point. Stdlib only so it starts instantly.

It is a thin pipe between the agent (stdin/stdout) and the running Deckhand app (a user-only
Unix socket), starting the app first if needed. All MCP logic lives in the app, next to the live
deck state. Running actions on the computer always needs the user's approval inside the app.
"""
import os
import socket
import subprocess
import sys
import threading
import time

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def socket_path():
    p = os.environ.get("DECKHAND_SOCKET")
    if p:
        return p
    d = os.environ.get("XDG_RUNTIME_DIR")
    if d and os.path.isdir(d):
        return os.path.join(d, "deckhand-mcp.sock")
    return f"/tmp/deckhand-{os.getuid()}-mcp.sock"


def _connect(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    return s


def _launch_app():
    subprocess.Popen([sys.executable, "-m", "deckhand", "--minimized"], cwd=PKG_ROOT, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def connect_with_autostart(timeout=30.0):
    path = socket_path()
    try:
        return _connect(path)
    except OSError:
        pass
    print("deckhand: starting the Deckhand app...", file=sys.stderr)
    _launch_app()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            return _connect(path)
        except OSError:
            time.sleep(0.2)
    raise SystemExit("deckhand: could not reach the Deckhand app (try starting `deckhand` once from a terminal)")


def serve():
    sock = connect_with_autostart()
    out = sys.stdout.buffer

    def pump_in():
        try:
            for line in sys.stdin.buffer:
                sock.sendall(line if line.endswith(b"\n") else line + b"\n")
        except OSError:
            pass
        finally:
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    threading.Thread(target=pump_in, daemon=True).start()
    try:
        while True:
            data = sock.recv(65536)
            if not data:
                break
            out.write(data)
            out.flush()
    except OSError:
        pass
    return 0


def run(argv):
    if not argv or argv[0] == "serve":
        return serve()
    from .mcp_install import run_cli
    return run_cli(argv)
