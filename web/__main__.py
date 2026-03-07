from tui.config import CONFIG_DIR, parse_conf
from web.app import create_app
import sys


def main():
    conf = parse_conf(CONFIG_DIR / "gniza.conf")
    host = conf.get("WEB_HOST", "0.0.0.0")
    port = int(conf.get("WEB_PORT", "2323"))

    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]

    app = create_app()
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
