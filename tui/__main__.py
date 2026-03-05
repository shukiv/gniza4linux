import sys

from tui.app import GnizaApp


def main():
    if "--web" in sys.argv:
        from textual_serve.server import Server
        port = 8080
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        server = Server("python3 -m tui", host="0.0.0.0", port=port)
        server.serve()
    else:
        app = GnizaApp()
        app.run()


if __name__ == "__main__":
    main()
