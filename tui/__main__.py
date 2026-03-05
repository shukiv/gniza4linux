import os
import sys
from pathlib import Path

from tui.app import GnizaApp

# Use GNIZA_DIR from env (set by bin/gniza), fall back to parent of tui/
_ROOT = os.environ.get("GNIZA_DIR", str(Path(__file__).resolve().parent.parent))


def main():
    if "--web" in sys.argv:
        from textual_serve.server import Server
        port = 8080
        host = "0.0.0.0"
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
            elif arg == "--host" and i + 1 < len(sys.argv):
                host = sys.argv[i + 1]
        os.environ["PYTHONPATH"] = f"{_ROOT}:{os.environ.get('PYTHONPATH', '')}"
        os.environ["GNIZA_DIR"] = _ROOT
        server = Server(
            "python3 -m tui",
            host=host,
            port=port,
            title="gniza",
            public_url="",
        )
        server.serve()
    else:
        app = GnizaApp()
        app.run()


if __name__ == "__main__":
    main()
