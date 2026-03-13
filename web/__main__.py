from logging.handlers import RotatingFileHandler

from tui.config import CONFIG_DIR, LOG_DIR, parse_conf
from web.app import create_app
import sys
import logging


def _setup_audit_log():
    """Configure audit logger to write to LOG_DIR/audit.log."""
    audit = logging.getLogger("gniza.audit")
    audit.setLevel(logging.INFO)
    if not audit.handlers:
        log_file = LOG_DIR / "audit.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            str(log_file), maxBytes=5 * 1024 * 1024, backupCount=3
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        audit.addHandler(handler)


def main():
    conf = parse_conf(CONFIG_DIR / "gniza.conf")
    host = conf.get("WEB_HOST", "0.0.0.0")
    port = int(conf.get("WEB_PORT", "2323"))

    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]

    _setup_audit_log()
    app = create_app()

    try:
        from waitress import serve
        logger = logging.getLogger("gniza-web")
        logger.info(f"Serving on http://{host}:{port}")
        serve(app, host=host, port=port, _quiet=True)
    except ImportError:
        app.run(host=host, port=port, debug=False)
    except OSError as e:
        if e.errno == 98:
            print(f"Error: Port {port} is already in use. Another gniza-web instance may be running.")
            print(f"  Stop it with: systemctl --user stop gniza-web")
            print(f"  Or use a different port: gniza web --port=2324")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
