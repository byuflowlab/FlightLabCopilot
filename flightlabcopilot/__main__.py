"""``flightlabcopilot`` / ``python -m flightlabcopilot``: start the app and open it in a browser."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import webbrowser

from . import __version__

DEFAULT_PORT = 5160  # FlightLabFoam uses 5150; avoid 5000 (macOS AirPlay Receiver)


def _free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("could not find a free port")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="flightlabcopilot", description="GPS waypoint guidance for the copilot")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to serve on (default {DEFAULT_PORT})")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser window")
    parser.add_argument("--data-dir", help="folder for the course, progress, map and logs")
    parser.add_argument("--version", action="version", version=f"flightlabcopilot {__version__}")
    args = parser.parse_args(argv)

    from .app import create_app

    app = create_app(args.data_dir)
    engine = app.config["ENGINE"]

    # reconnect to the radio used last time, if it is still plugged in
    src = engine.settings["source"]
    if src.get("kind") == "serial" and src.get("port") and os.path.exists(src["port"]):
        engine.set_source("serial", port=src["port"], baudrate=src.get("baudrate", 57600))

    def shutdown():
        print("FlightLabCopilot stopped from the browser.")
        threading.Timer(0.5, os._exit, args=(0,)).start()

    app.config["SHUTDOWN"] = shutdown
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # no line per request at 5 Hz
    port = _free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    print(f"FlightLabCopilot {__version__} is running at {url}")
    print(f"Data folder: {engine.store.root}")
    print("Keep this window open while you use the app. Stop it with Exit in the app, or Ctrl-C here.")
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    # 127.0.0.1 only: no authentication, must not be reachable from the network
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
