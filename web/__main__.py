import logging
import os
import ssl
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from tui.config import CONFIG_DIR, LOG_DIR, parse_conf
from web.app import create_app


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


def _generate_self_signed_cert(cert_dir):
    """Generate a self-signed SSL certificate if none exists."""
    cert_file = cert_dir / "gniza-web.crt"
    key_file = cert_dir / "gniza-web.key"
    if cert_file.is_file() and key_file.is_file():
        return str(cert_file), str(key_file)

    cert_dir.mkdir(parents=True, exist_ok=True)
    import subprocess
    hostname = "gniza-backup"
    try:
        hostname = subprocess.run(
            ["hostname", "-f"], capture_output=True, text=True, timeout=5
        ).stdout.strip() or "gniza-backup"
    except Exception:
        pass

    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(key_file), "-out", str(cert_file),
        "-days", "3650", "-nodes",
        "-subj", f"/CN={hostname}/O=GNIZA Backup",
    ], check=True, capture_output=True)
    os.chmod(str(key_file), 0o600)
    print(f"Generated self-signed SSL certificate: {cert_file}")
    return str(cert_file), str(key_file)


def main():
    conf = parse_conf(CONFIG_DIR / "gniza.conf")
    host = conf.get("WEB_HOST", "0.0.0.0")
    port = int(conf.get("WEB_PORT", "2323"))
    use_ssl = conf.get("WEB_SSL", "") == "yes"
    cert_file = conf.get("WEB_SSL_CERT", "")
    key_file = conf.get("WEB_SSL_KEY", "")

    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]
        elif arg == "--ssl":
            use_ssl = True
        elif arg.startswith("--cert="):
            cert_file = arg.split("=", 1)[1]
            use_ssl = True
        elif arg.startswith("--key="):
            key_file = arg.split("=", 1)[1]
            use_ssl = True

    _setup_audit_log()
    app = create_app()
    logger = logging.getLogger("gniza-web")

    # Set up SSL context if requested
    ssl_context = None
    if use_ssl:
        if not cert_file or not key_file:
            cert_dir = CONFIG_DIR / "ssl"
            cert_file, key_file = _generate_self_signed_cert(cert_dir)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(cert_file, key_file)
        # Enable SESSION_COOKIE_SECURE when using SSL
        app.config["SESSION_COOKIE_SECURE"] = True

    proto = "https" if use_ssl else "http"

    try:
        from waitress import serve
        logger.info(f"Serving on {proto}://{host}:{port}")
        print(f"GNIZA web dashboard: {proto}://{host}:{port}")
        if ssl_context:
            # Waitress doesn't support SSL directly — use a socket wrapper
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.listen(128)
            ssl_sock = ssl_context.wrap_socket(sock, server_side=True)
            serve(app, sockets=[ssl_sock], _quiet=True)
        else:
            serve(app, host=host, port=port, _quiet=True)
    except ImportError:
        if ssl_context:
            app.run(host=host, port=port, debug=False, ssl_context=(cert_file, key_file))
        else:
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
