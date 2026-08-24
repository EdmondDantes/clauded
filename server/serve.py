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
import os
import signal
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import maps


def stop_running():
    """
    Stops every server started by hand and says which; returns how many.

    A server a session started is left alone: it belongs to that session, and
    taking it down would cut the map off from the one place it talks to.
    """
    stopped = 0
    for record in maps.running_records():
        # A server a session started belongs to that session; only what was
        # started at a terminal is a person's to stop.
        if record.get("kind") != "hand":
            continue

        try:
            os.kill(int(record["pid"]), signal.SIGTERM)
        except OSError as refused:
            print(f"{record['url']} (pid {record['pid']}): {refused}", flush=True)
            continue

        print(f"stopped {record['url']} (pid {record['pid']})", flush=True)
        stopped += 1

    return stopped


def main():
    parser = argparse.ArgumentParser(description="Serve this project's maps on localhost.")
    parser.add_argument("--root", type=Path, default=Path("."), help="project root; defaults to .")
    parser.add_argument("--port", type=int, default=8791, help="port on 127.0.0.1; defaults to 8791")
    parser.add_argument("--open", metavar="NAME", help="open this map in the browser once the server is up")
    parser.add_argument("--stop", action="store_true",
                        help="stop the servers started by hand and exit")
    args = parser.parse_args()

    if args.stop:
        print("nothing was running" if stop_running() == 0 else "done", flush=True)
        return

    server, _, url = maps.start(args.root, args.port, kind="hand")
    names = ", ".join(maps.maps_in(args.root)) or "none yet"
    print(f"{url} — maps: {names}", flush=True)
    print(f"Ctrl+C stops it, and so does `serve.py --stop` from anywhere. pid {os.getpid()}", flush=True)

    if args.open:
        webbrowser.open(f"{url}/map/{args.open}")

    try:
        # A short sleep in a loop rather than one long wait: a wait with no
        # timeout can sit through Ctrl+C, and a server nobody can stop is worse
        # than no server.
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("stopped", flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
