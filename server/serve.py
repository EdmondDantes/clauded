#!/usr/bin/env python3
"""Serve this project's maps on localhost, rendered on each request.

Usage:
    serve.py [--root .] [--port 8791] [--open <name>]

The page is built when it is asked for, so an edit to the YAML shows up on
reload and no generated HTML is kept anywhere. This is the plain way in; when
Claude needs to ask on the map and wait for the answer, it runs the same server
through server/mcp.py instead.
"""

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import maps


def main():
    parser = argparse.ArgumentParser(description="Serve this project's maps on localhost.")
    parser.add_argument("--root", type=Path, default=Path("."), help="project root; defaults to .")
    parser.add_argument("--port", type=int, default=8791, help="port on 127.0.0.1; defaults to 8791")
    parser.add_argument("--open", metavar="NAME", help="open this map in the browser once the server is up")
    args = parser.parse_args()

    server, state, url = maps.start(args.root, args.port)
    names = ", ".join(maps.maps_in(args.root)) or "none yet"
    print(f"{url} — maps: {names}", flush=True)

    if args.open:
        webbrowser.open(f"{url}/map/{args.open}")

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("stopped", flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
