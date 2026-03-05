import os
import socket
import sys
from pathlib import Path

from tui.app import GnizaApp

# Use GNIZA_DIR from env (set by bin/gniza), fall back to parent of tui/
_ROOT = os.environ.get("GNIZA_DIR", str(Path(__file__).resolve().parent.parent))


def _get_local_ip() -> str:
    """Get the machine's LAN IP for public_url."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def main():
    if "--web" in sys.argv:
        from textual_serve.server import Server
        port = 8080
        host = "0.0.0.0"
        public_host = None
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
            elif arg == "--host" and i + 1 < len(sys.argv):
                host = sys.argv[i + 1]
                public_host = host
        os.environ["PYTHONPATH"] = f"{_ROOT}:{os.environ.get('PYTHONPATH', '')}"
        os.environ["GNIZA_DIR"] = _ROOT
        # textual-serve uses public_url to build WebSocket URLs.
        # If binding to 0.0.0.0, detect the real IP for the browser.
        if public_host is None:
            public_host = _get_local_ip() if host == "0.0.0.0" else host
        public_url = f"http://{public_host}:{port}"
        server = Server(
            "python3 -m tui",
            host=host,
            port=port,
            title="gniza",
            public_url=public_url,
        )
        server.serve()
    else:
        app = GnizaApp()
        app.run()


if __name__ == "__main__":
    main()
