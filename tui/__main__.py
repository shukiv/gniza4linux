import base64
import os
import re
import secrets
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


def _load_web_credentials() -> tuple[str, str]:
    """Load WEB_USER and WEB_API_KEY from gniza.conf."""
    config_dir = os.environ.get("GNIZA_CONFIG_DIR", "")
    if not config_dir:
        # Detect from mode
        if os.geteuid() == 0:
            config_dir = "/etc/gniza"
        else:
            config_dir = os.path.join(
                os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                "gniza",
            )
    conf_path = Path(config_dir) / "gniza.conf"
    user = "admin"
    api_key = ""
    if conf_path.is_file():
        kv_re = re.compile(r'^([A-Z_][A-Z0-9_]*)="(.*)"$')
        for line in conf_path.read_text().splitlines():
            m = kv_re.match(line.strip())
            if m:
                if m.group(1) == "WEB_USER":
                    user = m.group(2)
                elif m.group(1) == "WEB_API_KEY":
                    api_key = m.group(2)
    return user, api_key


def main():
    if "--web" in sys.argv:
        from aiohttp import web as aio_web
        from textual_serve.server import Server

        host, port = _parse_web_args()
        web_user, web_key = _load_web_credentials()

        if not web_key:
            print("WARNING: No WEB_API_KEY in gniza.conf. Web dashboard is unprotected.")

        os.environ["PYTHONPATH"] = f"{_ROOT}:{os.environ.get('PYTHONPATH', '')}"
        os.environ["GNIZA_DIR"] = _ROOT

        # Determine public URL for WebSocket connections
        if host == "0.0.0.0":
            public_host = _get_local_ip()
        else:
            public_host = host

        public_url = f"http://{public_host}:{port}"
        print(f"GNIZA web: serving TUI at {public_url}")
        if web_key:
            print(f"GNIZA web: login with user={web_user!r}")

        server = Server(
            "python3 -m tui",
            host=host,
            port=port,
            title="GNIZA Backup",
            public_url=public_url,
        )

        # Add HTTP Basic Auth middleware if API key is configured
        if web_key:
            _orig_make_app = server._make_app

            async def _authed_make_app():
                app = await _orig_make_app()

                @aio_web.middleware
                async def basic_auth(request, handler):
                    auth_header = request.headers.get("Authorization", "")
                    if auth_header.startswith("Basic "):
                        try:
                            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                            req_user, req_pass = decoded.split(":", 1)
                            if (
                                secrets.compare_digest(req_user, web_user)
                                and secrets.compare_digest(req_pass, web_key)
                            ):
                                return await handler(request)
                        except Exception:
                            pass
                    return aio_web.Response(
                        status=401,
                        headers={"WWW-Authenticate": 'Basic realm="GNIZA"'},
                        text="Authentication required",
                    )

                app.middlewares.insert(0, basic_auth)
                return app

            server._make_app = _authed_make_app

        server.serve()
    else:
        app = GnizaApp()
        app.run()


if __name__ == "__main__":
    main()
