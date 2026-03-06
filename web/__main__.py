import os
import sys
from pathlib import Path

from web.app import create_app, parse_conf

CONFIG_DIR = Path(os.environ.get("GNIZA_CONFIG_DIR", "/usr/local/gniza/etc"))


def main():
    # Read defaults from config
    conf = parse_conf(CONFIG_DIR / "gniza.conf")
    host = conf.get("WEB_HOST", "0.0.0.0")
    port = int(conf.get("WEB_PORT", "8080"))

    # CLI overrides
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]

    app = create_app()
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
