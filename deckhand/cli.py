"""Console entry point: `deckhand` (the app) and `deckhand mcp ...` (the agent bridge)."""
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from .mcp_cli import run
        return run(sys.argv[2:])
    from .app import main as app_main
    return app_main()
