#!/usr/bin/env python3
"""Serve the project's maps on localhost, rendered on each request.

Usage:
    serve.py [--root .] [--port 8791] [--open <name>]

The page is built when it is asked for, so an edit to the YAML shows up on
reload and no generated HTML is kept anywhere. This is also the side that
colours cited code, which a published snapshot does without.

Two endpoints carry what the reader does back to the session:

    POST /api/apply      the answers and questions behind the Apply button
    POST /api/selection  the node currently selected with the mouse

Both are written under <root>/.clauded/, where the MCP server reads them.
Binds to 127.0.0.1 only: this is one person's tool, not a service.
"""

import argparse
import json
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import mapkit

STATE_DIR = ".clauded"
MAX_BODY = 1 << 20


def maps_in(root):
    """Returns {name: path} for every map of the project, by file name."""
    design = Path(root) / "dev" / "design"
    return {path.name[:-len(".map.yaml")]: path for path in sorted(design.glob("*.map.yaml"))}


def index_page(root, names):
    """The page listing the maps, for when the request carries no name."""
    items = "".join(f'<li><a href="/map/{name}">{name}</a></li>' for name in names)
    empty = "<p>No maps yet. Write one into dev/design/&lt;name&gt;.map.yaml.</p>"
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Maps of {Path(root).resolve().name}</title>
<style>
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 3rem auto; max-width: 34rem; padding: 0 1.5rem; }}
  h1 {{ font-size: 1.1rem; }}
  li {{ margin: .3rem 0; }}
</style>
<h1>Maps of {Path(root).resolve().name}</h1>
{f"<ul>{items}</ul>" if names else empty}
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "clauded"

    # The default handler logs every request to stderr; the terminal running
    # this server is the one Claude Code shares, so it stays quiet.
    def log_message(self, *args):
        pass

    def reply(self, status, body, content_type="text/html; charset=utf-8"):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        root = self.server.root
        path = unquote(self.path.split("?")[0])

        if path in ("/", "/index.html"):
            self.reply(200, index_page(root, maps_in(root)))
            return

        if not path.startswith("/map/"):
            self.reply(404, "<p>Not here.</p>")
            return

        name = path[len("/map/"):].strip("/")
        source = maps_in(root).get(name)
        if source is None:
            self.reply(404, f"<p>No map named {name}.</p>")
            return

        try:
            _, page = mapkit.build(source, root, coloured=True)
        except ValueError as error:
            problems = "".join(f"<li>{line}</li>" for line in str(error).splitlines())
            self.reply(422, f"<h1>{name} does not validate</h1><ul>{problems}</ul>")
            return
        except Exception as error:
            self.reply(500, f"<h1>{name} failed to render</h1><pre>{error}</pre>")
            return

        self.reply(200, page)

    def do_POST(self):
        path = unquote(self.path.split("?")[0])
        if path not in ("/api/apply", "/api/selection"):
            self.reply(404, json.dumps({"error": "unknown endpoint"}), "application/json")
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self.reply(413, json.dumps({"error": "body too large"}), "application/json")
            return

        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.reply(400, json.dumps({"error": "body is not JSON"}), "application/json")
            return

        payload["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state = Path(self.server.root) / STATE_DIR
        state.mkdir(exist_ok=True)
        target = state / ("pending.json" if path == "/api/apply" else "selection.json")
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if path == "/api/apply":
            print(f"apply: {len(payload.get('answers') or {})} answers, "
                  f"{len(payload.get('asks') or [])} questions -> {target}", flush=True)

        self.reply(200, json.dumps({"ok": True}), "application/json")


def main():
    parser = argparse.ArgumentParser(description="Serve this project's maps on localhost.")
    parser.add_argument("--root", type=Path, default=Path("."), help="project root; defaults to .")
    parser.add_argument("--port", type=int, default=8791, help="port on 127.0.0.1; defaults to 8791")
    parser.add_argument("--open", metavar="NAME", help="open this map in the browser once the server is up")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.root = args.root

    where = f"http://127.0.0.1:{args.port}"
    names = ", ".join(maps_in(args.root)) or "none yet"
    print(f"{where} — maps: {names}", flush=True)

    if args.open:
        webbrowser.open(f"{where}/map/{args.open}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
