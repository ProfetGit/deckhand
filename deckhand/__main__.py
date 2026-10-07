import sys

if len(sys.argv) > 1 and sys.argv[1] == "mcp":
    from .mcp_cli import run
    sys.exit(run(sys.argv[2:]))

from .app import main

sys.exit(main())
