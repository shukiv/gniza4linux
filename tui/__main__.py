import os
import sys
from pathlib import Path

from tui.app import GnizaApp

# Resolve project root (parent of tui/)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def main():
    if "--web" in sys.argv:
        from textual_serve.server import Server
        port = 8080
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        env_path = f"{_PROJECT_ROOT}:{os.environ.get('PYTHONPATH', '')}"
        cmd = f"PYTHONPATH={env_path} GNIZA_DIR={_PROJECT_ROOT} python3 -m tui"
        server = Server(cmd, host="0.0.0.0", port=port)
        server.serve()
    else:
        app = GnizaApp()
        app.run()


if __name__ == "__main__":
    main()
