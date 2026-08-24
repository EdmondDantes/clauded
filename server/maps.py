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
import fcntl
import itertools
import json
import os
import subprocess
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

# Everything this tool keeps outside a project. CLAUDED_HOME moves it, which is
# how the tests keep their servers and their last root out of the real one.
HOME = Path(os.environ.get("CLAUDED_HOME") or Path.home() / STATE_DIR)

# Where a running server leaves its address, one file per process. The Stop hook
# reads this directory and picks the server of its own session: a single file
# would be overwritten by whichever session started last, and the hook of the
# first would then drain the map of the second.
SERVERS = HOME / "servers"

# The project the last server served. A reloaded plugin starts the server again
# in the directory Claude Code was launched in, which is often not the project
# holding the maps, and a page open on the old server would then be told its map
# does not exist.
LAST_ROOT = HOME / "last-root"
MAX_BODY = 1 << 20

# How much of a cited file the code window may ask for. A generated file runs to
# megabytes on one line, and the page holds the answer in memory.
SOURCE_LINES = 4000

# Counts the writes this server has made to each map by name, so a page can tell
# it must refetch even when two writes land in the same second — and so a write
# to one map leaves the pages of the others alone.
GENERATION = {}

# Tells apart two states built in one process. The clock and the pid are the same
# for both, and two lines minted with one id are read by the merge as one line.
ORIGINS = itertools.count(1)


def map_changed(name):
    GENERATION[name] = GENERATION.get(name, 0) + 1


def sweep():
    """Removes the record of every server that is no longer running."""
    if not SERVERS.is_dir():
        return

    for path in sorted(SERVERS.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            os.kill(int(record["pid"]), 0)
        except (OSError, ValueError, KeyError):
            path.unlink(missing_ok=True)


def announce(url, root):
    """
    Writes this process's address where the Stop hook will find it, and returns
    the record.

    The session id comes from the environment Claude Code gives an MCP server it
    starts; the hook has the same id in its own input, and that is what pairs the
    two. The record is removed when the process ends.

    A project holding maps is also written to LAST_ROOT, where the next server
    started somewhere mapless will read it.
    """
    SERVERS.mkdir(parents=True, exist_ok=True)
    sweep()
    # Written by every version up to 0.13.0 and read by nobody since.
    (HOME / "server.json").unlink(missing_ok=True)

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

    if maps_in(record["root"]):
        LAST_ROOT.write_text(record["root"], encoding="utf-8")

    return record


def project_root(asked):
    """
    The project to serve: the one asked for, or the last one served when the one
    asked for holds no maps at all.

    Claude Code starts an MCP server in the directory the session was started in.
    That is a fine default and a poor guess: a session started in a home
    directory serves nothing, and the page that was open goes deaf. A directory
    with maps in it is never overruled.
    """
    if maps_in(asked) or not LAST_ROOT.is_file():
        return Path(asked)

    try:
        remembered = Path(LAST_ROOT.read_text(encoding="utf-8").strip())
    except OSError:
        return Path(asked)

    return remembered if maps_in(remembered) else Path(asked)


def written_at(message):
    """
    The order two servers put the same conversation in.

    The time a line carries is written to the second, so lines of one second sort
    by who minted them and in what order — an id is "<origin>-<number>", and the
    number compared as text puts 10 before 9.
    """
    origin, _, number = str(message.get("id") or "").rpartition("-")
    try:
        return (str(message.get("at")), origin, int(number))
    except ValueError:
        return (str(message.get("at")), str(message.get("id")), 0)


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
        # The reader's lines already handed to Claude, by id. A count would do
        # for one server, but two servers on one project each write their own
        # lines into the same file, and the first three of a joined chat are not
        # the three that were handed over.
        self.handed = set()
        # What the state file said when this server last read or wrote it. A
        # different stamp means another server has written since.
        self.stamp = None
        # Every message gets an id unique across restarts, so a page that
        # remembers more than the server does can still tell what is new.
        # The pid keeps two servers started in the same second from minting the
        # same message ids.
        self.origin = f"{int(time.time())}-{os.getpid()}-{next(ORIGINS)}"
        self.counter = 0
        self._restore()

    def file(self):
        """Where this map's state is kept, one file per map."""
        return self.root / STATE_DIR / f"{self.name}.state.json"

    def _inherit(self):
        """
        The conversation held before state was split per map, or None.

        Until 2026-08-24 one file, `.clauded/state.json`, held the state of the
        whole project. It names no map, so the first map to ask takes it, and it
        is set aside afterwards rather than handed to the next one as well.
        """
        legacy = self.root / STATE_DIR / "state.json"
        if not legacy.is_file():
            return None

        taken = legacy.with_suffix(".json.taken")
        try:
            os.replace(legacy, taken)
        except OSError:
            return None

        return taken

    def _stamp(self):
        """What the state file looks like on disk, or None when there is none."""
        try:
            state = self.file().stat()
        except OSError:
            return None

        return (state.st_mtime_ns, state.st_size)

    def _sync(self):
        """
        Takes in what another server wrote to the same file since we last looked.

        Two sessions in one project each hold this map in memory and write the
        same file. Without this each would overwrite the other's lines with its
        own idea of the conversation; with it, both keep everything and the file
        is the meeting point. The caller holds the lock.
        """
        stamp = self._stamp()
        if stamp is None or stamp == self.stamp:
            return

        self.stamp = stamp
        try:
            theirs = json.loads(self.file().read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        known = {message.get("id") for message in self.chat}
        for message in theirs.get("chat") or []:
            if isinstance(message, dict) and message.get("id") not in known:
                self.chat.append(message)

        self.chat.sort(key=written_at)
        self.counter = max(self.counter, len(self.chat))
        self.handed |= set(theirs.get("handed") or [])

        for node, mark in (theirs.get("resolved") or {}).items():
            self.resolved.setdefault(node, mark)

        # The later draft wins: both carry the moment Apply was pressed.
        mine = (self.applied or {}).get("at") or ""
        yours = (theirs.get("applied") or {}).get("at") or ""
        if yours > mine:
            self.applied = theirs["applied"]

    def _restore(self):
        """Brings back the conversation a previous run of the server held."""
        saved = self.file()
        if not saved.is_file():
            saved = self._inherit()
        if saved is None or not saved.is_file():
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
        self.handed = set(data.get("handed") or [])
        # Written before the ids: the count named the first N lines of the
        # reader's, and those are the ones it stood for.
        if "handed" not in data and data.get("delivered"):
            mine = [m["id"] for m in self.chat if m.get("role") == "you"]
            self.handed = set(mine[:int(data["delivered"])])

        self.stamp = self._stamp()

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
            self._sync()
            return {
                "map": self.name,
                "version": self.version,
                "selection": self.selection,
                "chat": list(self.chat),
                "listeners": self.listeners,
                "handed": sorted(self.handed),
                "delivered": len(self.handed),
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
            self._sync()
            fresh = [m for m in self.chat if m["role"] == "you" and m["id"] not in self.handed]
            self.handed |= {message["id"] for message in fresh}
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

        Two threads of this server persist at once — a post and a drained inbox —
        and a half written file reads back as an empty conversation, which hands
        the whole log to Claude a second time. A second server on the same
        project is kept out by a lock file for the length of the read, the merge
        and the write, so neither loses what the other wrote in between.
        """
        with self.writing:
            self.file().parent.mkdir(exist_ok=True)
            guard = self.file().with_suffix(".lock")

            with open(guard, "a+", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    # snapshot() takes in whatever another server wrote before
                    # it answers, so what is written here is the union.
                    payload = json.dumps(self.snapshot(), ensure_ascii=False, indent=2)

                    temporary = self.file().with_suffix(".writing")
                    temporary.write_text(payload, encoding="utf-8")
                    os.replace(temporary, self.file())
                    self.stamp = self._stamp()
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)


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
                    problems = mapkit.collect_fragments(data, self.server.root, coloured=True, strict=False)
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
            # Lenient on purpose: a citation that no longer resolves marks
            # itself dead in the record, and the map stays workable. The static
            # build refuses instead — nobody is present to notice there.
            _, page = mapkit.build(source, root, coloured=True, stamp=self.map_stamp(name),
                                   name=name, strict=False)
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


# How long a line waits for a session that is in a turn before a session is
# started to answer it. Long enough for the Stop hook of a running turn to take
# it first: that answer comes from the session Edmond is actually talking to.
ANSWER_AFTER = 25.0

# The command that answers, and the switch that allows it. Off unless asked for:
# a session started to answer spends tokens with nobody watching, and that is
# Edmond's call rather than the server's. `CLAUDED_ANSWER=claude` turns it on.
ANSWER_WITH = os.environ.get("CLAUDED_ANSWER")

ANSWER_PROMPT = """A line was written on the design map "{name}" of this project and nobody read it: \
the session that opened the map is idle, so you were started to answer that line.

The line{about}: {text}

Answer on the map, not here. Read it with read_map, answer with reply_on_map — passing `node` when \
the line is about one — and use resolve_on_map only when the line settles a question. Keep the answer \
short and in Russian, and say plainly when you do not know. Then stop: do not wait for more, and do \
not change any file of the project."""


def unanswered(snapshot):
    """The oldest line of the reader's that Claude has not been given, or None."""
    handed = set(snapshot.get("handed") or [])
    mine = [m for m in snapshot["chat"] if m["role"] == "you" and m["id"] not in handed]
    return mine[0] if mine else None


def written_when(message):
    """When a line was written, in seconds since the epoch; 0 when it does not say."""
    try:
        return datetime.fromisoformat(str(message.get("at"))).timestamp()
    except ValueError:
        return 0.0


def answer_with_claude(root, name, message):
    """
    Starts a session whose whole job is to answer one line on the map.

    A hook fires at the end of a turn, and a session sitting idle has no turn to
    end — so a line written while nobody works reaches nobody. Rather than hold
    an agent open in case something is written, one is started because something
    was. Returns the process, or None when answering is switched off.
    """
    if not ANSWER_WITH:
        return None

    about = f" is about the node {message['about']}" if message.get("about") else ""
    prompt = ANSWER_PROMPT.format(name=name, about=about, text=message.get("text", ""))
    tools = ",".join(f"mcp__plugin_clauded_clauded__{tool}" for tool in
                     ("read_map", "read_state", "open_questions", "reply_on_map",
                      "select_on_map", "resolve_on_map"))

    try:
        return subprocess.Popen(
            [ANSWER_WITH, "-p", prompt, "--allowedTools", tools],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return None


class Answerer(threading.Thread):
    """
    Watches the maps of a project and answers what no session took.

    One at a time, and only when nothing is waiting on the map: a second session
    started while the first still writes would answer the same conversation
    twice, and neither would know of the other.
    """

    def __init__(self, board, root):
        super().__init__(name="clauded-answerer", daemon=True)
        self.board = board
        self.root = root
        self.working = None

    def run(self):
        while ANSWER_WITH:
            time.sleep(5.0)
            try:
                self.round()
            except Exception:
                # The map works with or without this; a watcher that dies here
                # must not take the server with it.
                continue

    def round(self):
        if self.working is not None and self.working.poll() is None:
            return

        for state in self.board.opened(self.root):
            snapshot = state.snapshot()
            if snapshot["listeners"] or snapshot["ended"]:
                continue

            waiting = unanswered(snapshot)
            if waiting is None or time.time() - written_when(waiting) < ANSWER_AFTER:
                continue

            # Taking the line through the inbox is what marks it answered: the
            # session started below reads it from its prompt, not from the map.
            state.inbox()
            self.working = answer_with_claude(self.root, state.name, waiting)
            state.touch()
            return


PORT_TRIES = 12


def start(root=".", port=8791):
    """
    Starts the server on a background thread and returns (server, board, url).

    A second Claude Code session, or a hand-started server, already holds the
    default port; rather than failing, the next free port up is taken.
    """
    root = project_root(root)
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

    Answerer(board, Path(root)).start()

    url = f"http://127.0.0.1:{port}"
    announce(url, root)

    return server, board, url
