import os
import socket
import subprocess
import sys
from pathlib import Path

from tui.app import GnizaApp

# Use GNIZA_DIR from env (set by bin/gniza), fall back to parent of tui/
_ROOT = os.environ.get("GNIZA_DIR", str(Path(__file__).resolve().parent.parent))


def _get_local_ip() -> str:
    """Get the machine's LAN IP for public_url."""
    # Method 1: UDP socket trick
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip != "0.0.0.0":
            return ip
    except Exception:
        pass
    # Method 2: hostname -I
    try:
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            ip = result.stdout.strip().split()[0]
            if ip:
                return ip
    except Exception:
        pass
    # Method 3: hostname resolution
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def _parse_web_args():
    """Parse --port and --host from sys.argv."""
    port = 8080
    host = "0.0.0.0"
    for i, arg in enumerate(sys.argv):
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]
        elif arg == "--host" and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
    return host, port


def main():
    if "--web" in sys.argv:
        from textual_serve.server import Server

        host, port = _parse_web_args()

        os.environ["PYTHONPATH"] = f"{_ROOT}:{os.environ.get('PYTHONPATH', '')}"
        os.environ["GNIZA_DIR"] = _ROOT

        # Determine public URL for WebSocket connections
        if host == "0.0.0.0":
            public_host = _get_local_ip()
        else:
            public_host = host

        public_url = f"http://{public_host}:{port}"
        print(f"GNIZA web: serving TUI at {public_url}")

        server = Server(
            f"python3 -m tui",
            host=host,
            port=port,
            title="GNIZA Backup",
            public_url=public_url,
        )
        server.serve()
    else:
        app = GnizaApp()
        app.run()


if __name__ == "__main__":
    main()
