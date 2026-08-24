"""The local map server: renders pages on request and holds what the page reports.

One instance serves every map of one project, and every map keeps its own
state: the selected node, the answers saved so far, the last Apply. The same
state is written to `<root>/.clauded/<map>.state.json`, so a session that starts
later can still read it, and two maps never share a conversation.

Two directions cross here. The page asks `GET /api/updates` on a timer and
learns which question Claude is waiting on and what Claude has replied; the page
posts each message the reader writes, and `wait_for` lets a caller block until
one arrives. Binds to 127.0.0.1 only:
this is one person's tool, not a service.
"""

import atexit
import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import mapkit

STATE_DIR = ".clauded"

# Where a running server leaves its address, one file per process. The Stop hook
# reads this directory and picks the server of its own session: a single file
# would be overwritten by whichever session started last, and the hook of the
# first would then drain the map of the second.
SERVERS = Path.home() / STATE_DIR / "servers"
MAX_BODY = 1 << 20

# How much of a cited file the code window may ask for. A generated file runs to
# megabytes on one line, and the page holds the answer in memory.
SOURCE_LINES = 4000

# Counts the writes this server has made to each map by name, so a page can tell
# it must refetch even when two writes land in the same second — and so a write
# to one map leaves the pages of the others alone.
GENERATION = {}


def map_changed(name):
    GENERATION[name] = GENERATION.get(name, 0) + 1


def running():
    """
    Every map server alive on this machine: the records, dead ones removed.

    A record names the session that started the server, when there was one —
    a server started by hand from serve.py has none.
    """
    if not SERVERS.is_dir():
        return []

    alive = []
    for path in sorted(SERVERS.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            os.kill(int(record["pid"]), 0)
        except (OSError, ValueError, KeyError):
            path.unlink(missing_ok=True)
            continue

        alive.append(record)

    return alive


def announce(url, root):
    """
    Writes this process's address where the Stop hook will find it, and returns
    the record.

    The session id comes from the environment Claude Code gives an MCP server it
    starts; the hook has the same id in its own input, and that is what pairs the
    two. The record is removed when the process ends.
    """
    SERVERS.mkdir(parents=True, exist_ok=True)
    running()

    record = {
        "url": url,
        "root": str(Path(root).resolve()),
        "pid": os.getpid(),
        "session": os.environ.get("CLAUDE_CODE_SESSION_ID"),
    }

    # By pid and port: one process may hold more than one server, and each
    # server's record has to come and go with the server itself.
    mine = SERVERS / f"{os.getpid()}-{urlsplit(url).port}.json"
    mine.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    atexit.register(lambda: mine.unlink(missing_ok=True))
    return record


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

    One instance stands for one map of one project. Every change bumps a version
    and wakes whoever waits on it, so a blocking tool call returns the moment the
    reader acts instead of polling. `focus` is the one field that travels the
    other way: Claude sets it, the page reads it.
    """

    def __init__(self, root, name):
        self.root = Path(root)
        self.name = name
        self.lock = threading.Condition()
        # Held over a write to the state file. Two threads renaming the same
        # temporary file leaves the second with nothing to rename.
        self.writing = threading.Lock()
        self.version = 0
        self.selection = None
        self.chat = []
        self.resolved = {}
        self.applied = None
        self.focus = None
        self.listeners = 0
        # When Claude was last seen doing anything for this map. A blocked wait
        # is only one of the states: between them Claude is working, not gone.
        self.last_seen = 0.0
        # Set when the reader ends the round: whoever is waiting learns the talk
        # is over instead of hanging until a timeout.
        self.ended = False
        # How many of the reader's messages have already been handed to Claude,
        # so the same line is not delivered twice.
        self.delivered = 0
        # Every message gets an id unique across restarts, so a page that
        # remembers more than the server does can still tell what is new.
        # The pid keeps two servers started in the same second from minting the
        # same message ids.
        self.origin = f"{int(time.time())}-{os.getpid()}"
        self.counter = 0
        self._restore()

    def file(self):
        """Where this map's state is kept, one file per map."""
        return self.root / STATE_DIR / f"{self.name}.state.json"

    def _restore(self):
        """Brings back the conversation a previous run of the server held."""
        saved = self.file()
        if not saved.is_file():
            return

        try:
            data = json.loads(saved.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        self.chat = [m for m in data.get("chat", []) if isinstance(m, dict)]
        self.delivered = int(data.get("delivered") or 0)
        # A message saved before ids existed still needs one: without it the
        # page treats the same reply as new on every poll.
        for index, message in enumerate(self.chat, start=1):
            message.setdefault("id", f"restored-{index}")
        self.counter = len(self.chat)
        self.resolved = data.get("resolved") or {}
        self.applied = data.get("applied")

    def touch(self):
        """Records that Claude is on this map right now."""
        with self.lock:
            self.last_seen = time.monotonic()

    def presence(self, idle_after=45.0):
        """
        Returns waiting, working or offline.

        waiting — a call is blocked on the reader's next message;
        working — no call is blocked, but Claude acted within `idle_after`;
        offline — nothing for longer than that, so a message will wait.
        """
        with self.lock:
            if self.listeners > 0:
                return "waiting"
            if self.last_seen and time.monotonic() - self.last_seen < idle_after:
                return "working"
            return "offline"

    def snapshot(self):
        with self.lock:
            return {
                "map": self.name,
                "version": self.version,
                "selection": self.selection,
                "chat": list(self.chat),
                "listeners": self.listeners,
                "delivered": self.delivered,
                "ended": self.ended,
                "resolved": dict(self.resolved),
                "applied": self.applied,
                "focus": self.focus,
            }

    def wait_for(self, test, timeout=None, stop=None):
        """
        Blocks until `test(snapshot)` returns something other than None, or the
        timeout runs out; returns that value, or None. The caller decides what
        counts as an answer, so one wait serves both Apply and a single question.

        `stop` is asked once a second whether the caller is still there: a client
        that walked away leaves the wait sitting on the map, and the next line
        the reader writes would be handed to nobody.
        """
        end = None if timeout is None else time.monotonic() + timeout

        with self.lock:
            self.listeners += 1
            self.last_seen = time.monotonic()

        try:
            return self._wait_loop(test, end, stop)
        finally:
            with self.lock:
                self.listeners -= 1

    def _wait_loop(self, test, end, stop):
        with self.lock:
            while True:
                if stop is not None and stop():
                    return None

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

    def add_message(self, role, text, about=None, kind="line"):
        """
        Appends one line to the single conversation and wakes whoever waits.

        `about` is the node selected when the line was written — the subject, not
        a separate thread: one chat is easier to follow than a dozen. `kind` is
        "line" for anything said and "finish" for the one the round ends with, so
        a reader of the chat tells the end from a remark about it.
        """
        with self.lock:
            message = self._append(role, text, about, kind)
            # An answer settles the question Claude pointed at, so the pointer
            # goes away and the page stops showing it as waited on.
            if role == "you" and self.focus and (about is None or self.focus.get("node") == about):
                self.focus = None
            if role == "claude":
                self.last_seen = time.monotonic()
            self.version += 1
            self.lock.notify_all()

        self._persist()
        return message

    def _append(self, role, text, about, kind):
        """Puts one line in the conversation. The caller holds the lock."""
        self.counter += 1
        message = {
            "id": f"{self.origin}-{self.counter}",
            "role": role,
            "text": text,
            "about": about,
            "kind": kind,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.chat.append(message)
        return message

    def finish(self, payload, summary):
        """
        Ends the round: keeps the draft, raises the flag and writes the summary
        into the conversation.

        The three happen under one lock and wake the waiters once, so a call
        blocked on the conversation cannot see the summary before the flag and
        answer a finished round as though it were still running.
        """
        with self.lock:
            self.applied = payload
            self.focus = None
            self.ended = True
            message = self._append("you", summary, None, "finish")
            self.version += 1
            self.lock.notify_all()

        self._persist()
        return message

    def take_end(self):
        """
        Reports the end of the round once and forgets it.

        The end is a signal, not a state: the first caller to ask is told, and a
        call that starts afterwards waits for the next Finish instead of hearing
        this one again.
        """
        with self.lock:
            if not self.ended:
                return False
            self.ended = False
            self.version += 1
            self.lock.notify_all()

        self._persist()
        return True

    def resolve(self, node, note):
        """Marks a question settled, so the page stops asking for it."""
        with self.lock:
            self.resolved[node] = {"note": note, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if self.focus and self.focus.get("node") == node:
                self.focus = None
            self.version += 1
            self.lock.notify_all()

        self._persist()

    def inbox(self):
        """The reader's messages Claude has not been given yet, and marks them given."""
        with self.lock:
            mine = [m for m in self.chat if m["role"] == "you"]
            fresh = mine[self.delivered:]
            self.delivered = len(mine)
            # Handing the finish over spends the signal, the same way a waiting
            # call spends it: the end is told once, and a wait that starts after
            # belongs to the next round.
            if any(message.get("kind") == "finish" for message in fresh):
                self.ended = False

        if fresh:
            self._persist()

        return fresh

    def conversation(self, since=None):
        """
        The conversation after the message `since`, or all of it when `since` is
        None or names a message this server does not hold.

        The page keeps its own copy of what it sent, but a second window — or a
        phone — sent lines this one never saw, so everything travels until the
        page says how far it has got. An unknown id means the two are out of
        step — a restarted server, a page open since yesterday — and the whole
        log is the only safe answer.
        """
        chat = self.snapshot()["chat"]
        if since is None:
            return chat

        for index, message in enumerate(chat):
            if message.get("id") == since:
                return chat[index + 1:]

        return chat

    def update(self, **fields):
        with self.lock:
            for name, value in fields.items():
                setattr(self, name, value)
            self.version += 1
            self.lock.notify_all()
        self._persist()

    def _persist(self):
        """
        Writes the state beside the file and renames it into place.

        Two threads persist at once — a post and a drained inbox — and a half
        written file reads back as an empty conversation, which hands the whole
        log to Claude a second time.
        """
        with self.writing:
            self.file().parent.mkdir(exist_ok=True)
            temporary = self.file().with_suffix(".writing")
            temporary.write_text(
                json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, self.file())


class Board:
    """
    The state of each map, made when a map is first asked for and kept by
    project and name.

    A map nobody has opened has no state here, which is what lets the Stop hook
    drain every conversation at once without inventing empty ones.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.states = {}

    def state(self, root, name):
        key = (str(Path(root).resolve()), name)
        with self.lock:
            if key not in self.states:
                self.states[key] = State(root, name)
            return self.states[key]

    def opened(self, root):
        """Every state made for this project so far, in the order they were made."""
        wanted = str(Path(root).resolve())
        with self.lock:
            return [state for (where, _), state in self.states.items() if where == wanted]


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

    def asked_map(self):
        """The map named in the query string; empty when the request names none."""
        return (parse_qs(urlsplit(self.path).query).get("map") or [""])[0].strip("/")

    def asked_since(self):
        """The last message id the page holds, or None when it holds none."""
        return (parse_qs(urlsplit(self.path).query).get("since") or [""])[0] or None

    def state_for(self, name):
        """
        The state of one map, or None with the answer already sent.

        Every endpoint that carries a conversation needs the name: the states of
        two maps differ in everything but the project they sit in.
        """
        if not isinstance(name, str) or not name:
            self.json_reply(400, {"error": "name the map: ?map=<name>"})
            return None

        if name not in maps_in(self.server.root):
            self.json_reply(404, {"error": f"no map named {name}"})
            return None

        return self.server.board.state(self.server.root, name)

    def do_GET(self):
        root = self.server.root
        path = unquote(self.path.split("?")[0])

        if path in ("/", "/index.html"):
            self.reply(200, index_page(root, maps_in(root)))
            return

        if path.startswith("/api/map/"):
            name = path[len("/api/map/"):].strip("/")
            source = maps_in(self.server.root).get(name)
            if source is None:
                self.json_reply(404, {"error": f"no map named {name}"})
                return

            try:
                data = mapkit.load(source)
                problems = mapkit.validate(data)
                if not problems:
                    problems = mapkit.collect_fragments(data, self.server.root, coloured=True)
                if problems:
                    self.json_reply(422, {"error": problems})
                    return
            except Exception as error:
                self.json_reply(500, {"error": str(error)})
                return

            self.json_reply(200, data)
            return

        if path == "/api/maps":
            self.json_reply(200, {"maps": self.map_listing()})
            return

        if path == "/api/source":
            self.serve_source(root)
            return

        if path == "/api/inbox":
            # Named: one map. Unnamed: every map the session has opened, which is
            # what the Stop hook wants — it knows a turn is ending, not which map
            # was written on.
            wanted = self.asked_map()
            if wanted:
                state = self.state_for(wanted)
                if state is None:
                    return
                states = [state]
            else:
                states = self.server.board.opened(self.server.root)

            messages = []
            for state in states:
                fresh = state.inbox()
                if not fresh:
                    continue

                # Draining the inbox is Claude reaching for this map, which is as
                # good a sign of presence as answering. A map with nothing on it
                # is not reached for, and saying otherwise puts Claude on a map
                # nobody wrote to.
                state.touch()
                for message in fresh:
                    messages.append(dict(message, map=state.name))

            self.json_reply(200, {"messages": messages})
            return

        if path == "/api/updates":
            state = self.state_for(self.asked_map())
            if state is None:
                return

            snapshot = state.snapshot()
            self.json_reply(200, {
                "build": mapkit.build_stamp(),
                "map": self.map_stamp(state.name),
                "presence": state.presence(),
                "ended": snapshot["ended"],
                "focus": snapshot["focus"],
                "resolved": snapshot["resolved"],
                "chat": state.conversation(self.asked_since()),
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
            _, page = mapkit.build(source, root, coloured=True, stamp=self.map_stamp(name), name=name)
        except ValueError as error:
            problems = "".join(f"<li>{line}</li>" for line in str(error).splitlines())
            self.reply(422, f"<h1>{name} does not validate</h1><ul>{problems}</ul>")
            return
        except Exception as error:
            self.reply(500, f"<h1>{name} failed to render</h1><pre>{error}</pre>")
            return

        self.reply(200, page)

    def map_listing(self):
        """
        Every map of the project: the name it is served under and the title it
        carries. A map whose YAML no longer parses keeps its name in the list,
        because a menu that hides a broken map hides the way to fix it.
        """
        listing = []
        for name, source in maps_in(self.server.root).items():
            try:
                title = mapkit.load(source).get("title") or name
            except Exception:
                title = name
            listing.append({"name": name, "title": title})
        return listing

    def map_stamp(self, name):
        """
        A stamp that changes whenever this map's data does.

        Two parts: what the file says now, and how many writes this server has
        made to it — a file written twice within one clock tick still moves the
        stamp. Other maps do not enter it, so a write to one leaves the pages of
        the rest where they are.
        """
        source = maps_in(self.server.root).get(name)
        if source is None:
            return "gone"
        return f"{GENERATION.get(name, 0)}|{mapkit.map_stamp(source)}"

    def serve_source(self, root):
        """
        Serves one file of the project whole, coloured the same way a cited
        fragment is. The code window opens on the cited lines and scrolls
        through the rest: a fragment cut to fifteen lines answers what the line
        says and nothing about what it sits in.
        """
        base = Path(root).resolve()
        wanted = (parse_qs(urlsplit(self.path).query).get("file") or [""])[0]
        target = (base / wanted).resolve()

        # A path is a request from the page, and the page is one reload away
        # from carrying anything: nothing outside the project is served.
        if not wanted or base not in target.parents:
            self.json_reply(403, {"error": "not a file of this project"})
            return

        if not target.is_file():
            self.json_reply(404, {"error": f"no file at {wanted}"})
            return

        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")
        clipped = len(lines) > SOURCE_LINES
        if clipped:
            text = "\n".join(lines[:SOURCE_LINES])

        self.json_reply(200, {
            "file": wanted,
            "code": text,
            "html": mapkit.colour(text, target.name),
            "clipped": clipped,
        })

    def do_POST(self):
        path = unquote(self.path.split("?")[0])
        known = {"/api/apply", "/api/selection", "/api/message"}
        if path not in known:
            self.json_reply(404, {"error": "unknown endpoint"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            # The body is never read, so the connection cannot carry another
            # request after this one.
            self.close_connection = True
            self.json_reply(413, {"error": "body too large"})
            return

        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.json_reply(400, {"error": "body is not JSON"})
            return

        state = self.state_for(payload.get("map") or self.asked_map())
        if state is None:
            return

        payload["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if path == "/api/selection":
            state.update(selection=payload)
        elif path == "/api/message":
            state.add_message("you", payload.get("text", ""), payload.get("about"))
        else:
            # Apply is the end of the round: whoever waits stops waiting.
            state.finish(payload, payload.get("summary") or "Работа принята.")

        self.json_reply(200, {"ok": True})


PORT_TRIES = 12


def start(root=".", port=8791):
    """
    Starts the server on a background thread and returns (server, board, url).

    A second Claude Code session, or a hand-started server, already holds the
    default port; rather than failing, the next free port up is taken.
    """
    board = Board()
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
    server.board = board
    server.daemon_threads = True

    thread = threading.Thread(target=server.serve_forever, name="clauded-http", daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    announce(url, root)

    return server, board, url
