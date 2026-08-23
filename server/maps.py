"""The local map server: renders pages on request and holds what the page reports.

One instance serves every map of one project. It keeps the reader's state in
memory — the selected node, the answers saved so far, the last Apply — and
writes the same state under `<root>/.clauded/` so a session that starts later
can still read it.

Two directions cross here. The page asks `GET /api/updates` on a timer and
learns which question Claude is waiting on and what Claude has replied; the page
posts each message the reader writes, and `wait_for` lets a caller block until
one arrives. Binds to 127.0.0.1 only:
this is one person's tool, not a service.
"""

import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import mapkit

STATE_DIR = ".clauded"
MAX_BODY = 1 << 20


def maps_in(root):
    """Returns {name: path} for every map of the project, by file name."""
    design = Path(root) / "dev" / "design"
    return {path.name[:-len(".map.yaml")]: path for path in sorted(design.glob("*.map.yaml"))}


def index_page(root, names):
    """The page listing the maps, for a request that carries no name."""
    items = "".join(f'<li><a href="/map/{name}">{name}</a></li>' for name in names)
    empty = "<p>No maps yet. Write one into dev/design/&lt;name&gt;.map.yaml.</p>"
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Maps of {Path(root).resolve().name}</title>
<style>
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 3rem auto; max-width: 34rem; padding: 0 1.5rem; }}
  h1 {{ font-size: 1.1rem; }}
  li {{ margin: .3rem 0; }}
</style>
<h1>Maps of {Path(root).resolve().name}</h1>
{f"<ul>{items}</ul>" if names else empty}
"""


class State:
    """
    What the open page has reported, and what Claude is waiting for.

    Every change bumps a version and wakes whoever waits on it, so a blocking
    tool call returns the moment the reader acts instead of polling. `focus` is
    the one field that travels the other way: Claude sets it, the page reads it.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.Condition()
        self.version = 0
        self.selection = None
        self.chat = []
        self.resolved = {}
        self.applied = None
        self.focus = None
        self.listeners = 0
        # Every message gets an id unique across restarts, so a page that
        # remembers more than the server does can still tell what is new.
        self.origin = str(int(time.time()))
        self.counter = 0
        self._restore()

    def _restore(self):
        """Brings back the conversation a previous run of the server held."""
        saved = self.root / STATE_DIR / "state.json"
        if not saved.is_file():
            return

        try:
            data = json.loads(saved.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        self.chat = [m for m in data.get("chat", []) if isinstance(m, dict)]
        # A message saved before ids existed still needs one: without it the
        # page treats the same reply as new on every poll.
        for index, message in enumerate(self.chat, start=1):
            message.setdefault("id", f"restored-{index}")
        self.counter = len(self.chat)
        self.resolved = data.get("resolved") or {}
        self.applied = data.get("applied")

    def snapshot(self):
        with self.lock:
            return {
                "version": self.version,
                "selection": self.selection,
                "chat": list(self.chat),
                "listeners": self.listeners,
                "resolved": dict(self.resolved),
                "applied": self.applied,
                "focus": self.focus,
            }

    def wait_for(self, test, timeout=None):
        """
        Blocks until `test(snapshot)` returns something other than None, or the
        timeout runs out; returns that value, or None. The caller decides what
        counts as an answer, so one wait serves both Apply and a single question.
        """
        end = None if timeout is None else time.monotonic() + timeout

        with self.lock:
            self.listeners += 1

        try:
            return self._wait_loop(test, end)
        finally:
            with self.lock:
                self.listeners -= 1

    def _wait_loop(self, test, end):
        with self.lock:
            while True:
                found = test(self.snapshot())
                if found is not None:
                    return found

                if end is None:
                    self.lock.wait(1.0)
                    continue

                left = end - time.monotonic()
                if left <= 0:
                    return None
                self.lock.wait(min(1.0, left))

    def add_message(self, role, text, about=None):
        """
        Appends one line to the single conversation and wakes whoever waits.

        `about` is the node selected when the line was written — the subject, not
        a separate thread: one chat is easier to follow than a dozen.
        """
        with self.lock:
            self.counter += 1
            message = {
                "id": f"{self.origin}-{self.counter}",
                "role": role,
                "text": text,
                "about": about,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }

            self.chat.append(message)
            # An answer settles the question Claude pointed at, so the pointer
            # goes away and the page stops showing it as waited on.
            if role == "you" and self.focus and (about is None or self.focus.get("node") == about):
                self.focus = None
            self.version += 1
            self.lock.notify_all()

        self._persist()
        return message

    def resolve(self, node, note):
        """Marks a question settled, so the page stops asking for it."""
        with self.lock:
            self.resolved[node] = {"note": note, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if self.focus and self.focus.get("node") == node:
                self.focus = None
            self.version += 1
            self.lock.notify_all()

        self._persist()

    def replies_for_page(self):
        """Claude's side of the conversation, which is what the page does not have."""
        return [message for message in self.snapshot()["chat"] if message["role"] == "claude"]

    def update(self, **fields):
        with self.lock:
            for name, value in fields.items():
                setattr(self, name, value)
            self.version += 1
            self.lock.notify_all()
        self._persist()

    def _persist(self):
        directory = self.root / STATE_DIR
        directory.mkdir(exist_ok=True)
        (directory / "state.json").write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


class Handler(BaseHTTPRequestHandler):
    server_version = "clauded"

    # The default handler logs every request to stderr, which on this server is
    # the MCP transport's neighbour; it stays quiet.
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

    def json_reply(self, status, payload):
        self.reply(status, json.dumps(payload, ensure_ascii=False), "application/json")

    def do_GET(self):
        root = self.server.root
        path = unquote(self.path.split("?")[0])

        if path in ("/", "/index.html"):
            self.reply(200, index_page(root, maps_in(root)))
            return

        if path == "/api/updates":
            state = self.server.state
            snapshot = state.snapshot()
            self.json_reply(200, {
                "build": mapkit.build_stamp(),
                "listening": snapshot["listeners"] > 0,
                "focus": snapshot["focus"],
                "resolved": snapshot["resolved"],
                "replies": state.replies_for_page(),
            })
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
        known = {"/api/apply", "/api/selection", "/api/message"}
        if path not in known:
            self.json_reply(404, {"error": "unknown endpoint"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self.json_reply(413, {"error": "body too large"})
            return

        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.json_reply(400, {"error": "body is not JSON"})
            return

        state = self.server.state
        payload["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if path == "/api/selection":
            state.update(selection=payload)
        elif path == "/api/message":
            state.add_message("you", payload.get("text", ""), payload.get("about"))
        else:
            state.update(applied=payload, focus=None)

        self.json_reply(200, {"ok": True})


PORT_TRIES = 12


def start(root=".", port=8791):
    """
    Starts the server on a background thread and returns (server, state, url).

    A second Claude Code session, or a hand-started server, already holds the
    default port; rather than failing, the next free port up is taken.
    """
    state = State(root)
    server = None
    last = None

    for candidate in range(port, port + PORT_TRIES):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError as error:
            last = error

    if server is None:
        raise OSError(f"no free port between {port} and {port + PORT_TRIES - 1}: {last}")

    server.root = Path(root)
    server.state = state
    server.daemon_threads = True

    thread = threading.Thread(target=server.serve_forever, name="clauded-http", daemon=True)
    thread.start()
    return server, state, f"http://127.0.0.1:{port}"
