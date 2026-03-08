from tui.config import CONFIG_DIR, parse_conf
from web.app import create_app
import sys
import logging


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

    try:
        from waitress import serve
        logger = logging.getLogger("gniza-web")
        logger.info(f"Serving on http://{host}:{port}")
        serve(app, host=host, port=port, _quiet=True)
    except ImportError:
        app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
