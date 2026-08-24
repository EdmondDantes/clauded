#!/usr/bin/env python3
"""MCP server for clauded: Claude asks on the map and waits for the answer there.

Speaks JSON-RPC over stdin and stdout, one message per line, and runs the local
map server in the same process. Four tools:

    open_map          render a map and hand back its address
    open_questions    what is still open on the map, so the round has an end
    add_node          write a new node into the map while the talk goes on
    edit_node         change what a node says
    remove_node       take a node off the map when it turned out wrong
    select_on_map     point at a node without waiting for anything
    read_state        what is selected, and every thread as it stands
    ask_on_map        point at one question and wait for the next thing said there
    wait_for_message  wait for anything said anywhere on the map — the chat loop
    reply_on_map      answer in a node's thread, the way a chat reply lands
    resolve_on_map    mark a question settled and move on
    wait_for_apply    wait until Apply hands the whole draft over

The waiting tools block, which is the point: work does not start while a
question is open. A blocking call is bounded by the `timeout` in .mcp.json, so
keep that above the longest wait you expect.
"""

import json
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import mapkit
import maps

PROTOCOL = "2024-11-05"
DEFAULT_PORT = 8791

TOOLS = [
    {
        "name": "open_map",
        "description": "Render a map and return its address. Opens it in a browser unless told otherwise.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Map name (the part before .map.yaml), or a path to the file"},
                "project": {"type": "string", "description": "Project root holding dev/design; defaults to where Claude Code started, and stays in force for later calls"},
                "browser": {"type": "boolean", "description": "Open a browser window; default true"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "read_state",
        "description": "What the open map shows now: the selected node, the whole conversation, what is settled, and the last Apply. Does not wait.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_questions",
        "description": "The questions still open on a map, in order, with the ones already settled left out. Empty means the round is over.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
        },
    },
    {
        "name": "add_node",
        "description": "Add a node to the map while talking — a question that came up, a decision just taken, an option rejected. Writes the map's YAML, so the page picks it up.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Short id, latin, dashes: q-cache-size"},
                "kind": {"type": "string", "description": "aspect | question | decision | rejected | module | knowledge | dependency"},
                "title": {"type": "string", "description": "One line, the node's name"},
                "body": {"type": "string", "description": "What it is, in a sentence or three"},
                "why": {"type": "string", "description": "Why it stands, if the source says"},
                "cost": {"type": "string", "description": "What it costs, if anything"},
                "status": {"type": "string", "description": "open | decided | rejected, for design maps"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "Named alternatives, for a question"},
                "origin": {"type": "string", "description": "Where it came from; defaults to this conversation"},
                "edges": {
                    "type": "array",
                    "description": "Edges to add, each [from, to, relation] with relation holds | rejects | needs",
                    "items": {"type": "array", "items": {"type": "string"}}
                },
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
            "required": ["id", "kind", "title", "body"],
        },
    },
    {
        "name": "edit_node",
        "description": "Change a node already on the map — its title, text, reason, price, status or options. Only the fields you pass are touched.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Node id to change"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "why": {"type": "string"},
                "cost": {"type": "string"},
                "status": {"type": "string", "description": "open | decided | rejected"},
                "kind": {"type": "string", "description": "aspect | question | decision | rejected | module | knowledge | dependency"},
                "options": {"type": "array", "items": {"type": "string"}},
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "remove_node",
        "description": "Take a node off the map, with every edge that touched it. Use when a node turned out to be wrong, not merely settled.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Node id to remove"},
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "select_on_map",
        "description": "Select a node on the open map, making it the subject of what the reader writes next. Does not wait.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {"type": "string", "description": "Node id to select"},
                "note": {"type": "string", "description": "One line shown with it"},
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
            "required": ["node"],
        },
    },
    {
        "name": "ask_on_map",
        "description": "Point the open map at one question and wait for the next message in its thread. Returns what was said, or nothing if the wait runs out.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {"type": "string", "description": "Node id of the question to ask"},
                "note": {"type": "string", "description": "One line shown with the question"},
                "timeout_seconds": {"type": "number", "description": "How long to wait; default 900"},
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
            "required": ["node"],
        },
    },
    {
        "name": "reply_on_map",
        "description": "Write into the map's conversation, where it appears as a chat message from Claude. Does not wait.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The reply, as the reader will see it"},
                "node": {"type": "string", "description": "Node the reply is about; shown as its subject"},
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "wait_for_message",
        "description": "Wait for the next messages the reader writes in the map's conversation; each carries the node it is about. Call it again after replying to keep talking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout_seconds": {"type": "number", "description": "How long to wait; default 1500"},
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
        },
    },
    {
        "name": "resolve_on_map",
        "description": "Mark a question settled on the map: the node shows as answered and the reader can move on. Say what the answer was.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {"type": "string", "description": "Node id of the question"},
                "answer": {"type": "string", "description": "The settled answer, one line, as it will appear on the map"},
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
            "required": ["node", "answer"],
        },
    },
    {
        "name": "wait_for_apply",
        "description": "Wait until Apply is pressed on the map, then return every answer and question it carries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout_seconds": {"type": "number", "description": "How long to wait; default 1500"},
                "name": {"type": "string", "description": "Map name; defaults to the one last opened"},
            },
        },
    },
]


class Session:
    """
    Holds the one running map server, started when a tool first needs it.

    The project root starts as the directory Claude Code was launched in, which
    is often not the project that owns the maps: a tool may name another, and
    the running server follows it without a restart.
    """

    def __init__(self, root, port):
        self.root = Path(root)
        self.port = port
        self.lock = threading.Lock()
        self.server = None
        self.board = None
        self.url = None
        self.last_map = None

    def ensure(self):
        with self.lock:
            if self.server is None:
                self.server, self.board, self.url = maps.start(self.root, self.port)
            return self.board, self.url

    def use(self, root):
        """Points the session at another project; returns the root in force."""
        with self.lock:
            if root:
                self.root = Path(root).expanduser().resolve()
                if self.server is not None:
                    self.server.root = self.root
            return self.root


class NoMap(Exception):
    """No map was named and none is open, so a tool has nothing to work on."""


def state_of(session, args):
    """
    Returns (state, url, name) for the map a tool works on.

    The map is the one the tool names, the one opened last, or — in a project
    that holds a single map — that one. Raises NoMap when none of the three
    answers, because a conversation without a map has nowhere to go.
    """
    board, url = session.ensure()
    known = maps.maps_in(session.root)
    name = args.get("name") or session.last_map
    if name is None and len(known) == 1:
        name = next(iter(known))

    if name not in known:
        listing = ", ".join(known) or "none"
        raise NoMap(f"Open a map first with open_map. Maps under {session.root}: {listing}.")

    return board.state(session.root, name), url, name


def tool_open_map(session, args):
    name = args["name"]

    # A path to the map file names its project too: dev/design/<name>.map.yaml
    # sits three levels under the root.
    path = Path(name).expanduser()
    if path.suffix in (".yaml", ".yml") and path.is_file():
        session.use(path.resolve().parent.parent.parent)
        name = path.name[:-len(".map.yaml")]
    else:
        session.use(args.get("project"))

    board, url = session.ensure()
    known = maps.maps_in(session.root)

    if name not in known:
        listing = ", ".join(known) or "none"
        return (f"No map named {name}. Maps under {session.root}: {listing}. "
                "Name the project root with `project`, or pass the path to the .map.yaml file.")

    session.last_map = name
    board.state(session.root, name)
    address = f"{url}/map/{name}"
    if args.get("browser", True):
        webbrowser.open(address)

    return f"{address} — {known[name]}"


def tool_read_state(session, args):
    state, _, _ = state_of(session, args)
    return json.dumps(state.snapshot(), ensure_ascii=False, indent=2)


# What every waiting call says when the reader presses Finish. One wording, so
# the end of a round reads the same whichever call was blocked on it.
FINISHED = (
    "Edmond pressed Finish: the round is over. Stop waiting and stop asking. "
    "What he handed over is in `applied` — read_state, or the answer of wait_for_apply."
)


def end_of_round(state):
    """True when the round has just ended; takes the signal so it is told once."""
    return state.take_end()


def said_by_reader(snapshot, seen):
    """The reader's messages beyond the ones already counted."""
    mine = [m for m in snapshot["chat"] if m["role"] == "you"]
    return mine[seen:] or None


def tool_open_questions(session, args):
    state, _, name = state_of(session, args)
    source = maps.maps_in(session.root)[name]

    data = mapkit.load(source)
    settled = set(state.snapshot()["resolved"])
    questions = [
        {"node": node["id"], "title": node["title"], "options": node.get("options") or []}
        for node in data["nodes"]
        if node.get("kind") == "question" and node.get("status") == "open" and node["id"] not in settled
    ]

    return json.dumps({"map": name, "open": questions}, ensure_ascii=False, indent=2)


def tool_add_node(session, args):
    session.ensure()
    known = maps.maps_in(session.root)
    name = args.get("name") or session.last_map
    source = known.get(name)

    if source is None:
        listing = ", ".join(known) or "none"
        return f"No map named {name}. Maps under {session.root}: {listing}."

    data = mapkit.load(source)
    seen = mapkit.map_stamp(source)
    if any(node["id"] == args["id"] for node in data["nodes"]):
        return f"{args['id']} is already on the map."

    node = {
        "id": args["id"],
        "kind": args["kind"],
        "title": args["title"],
        "body": args["body"],
        "origin": args.get("origin") or "added while talking on the map",
    }
    for field in ("why", "cost", "status", "options"):
        if args.get(field):
            node[field] = args[field]

    if node["kind"] == "question" and "status" not in node:
        node["status"] = "open"

    data["nodes"].append(node)
    for edge in args.get("edges") or []:
        data["edges"].append(list(edge))

    problems = mapkit.validate(data)
    if problems:
        return "The node would break the map:\n" + "\n".join(problems)

    failed = write_map(source, data, seen)
    if failed:
        return failed

    return f"{args['id']} is on the map, and {source} now holds it."


def open_map_file(session, args):
    """
    Returns (path, data, stamp) for the map a tool names, or (None, message, None).

    The stamp is taken with the read: writing quotes it back, so a file someone
    else changed in between is not overwritten.
    """
    session.ensure()
    known = maps.maps_in(session.root)
    name = args.get("name") or session.last_map
    source = known.get(name)

    if source is None:
        listing = ", ".join(known) or "none"
        return None, f"No map named {name}. Maps under {session.root}: {listing}.", None

    return source, mapkit.load(source), mapkit.map_stamp(source)


def write_map(source, data, seen):
    """Saves a map and tells the server its data moved; returns an error, or None."""
    try:
        mapkit.save(source, data, seen=seen)
    except ValueError as error:
        return str(error)

    maps.map_changed(source.name[:-len(".map.yaml")])
    return None


def tool_edit_node(session, args):
    source, data, seen = open_map_file(session, args)
    if source is None:
        return data

    node = next((n for n in data["nodes"] if n["id"] == args["id"]), None)
    if node is None:
        return f"{args['id']} is not on this map."

    for field in ("title", "body", "why", "cost", "status", "kind", "options"):
        if args.get(field) is not None:
            node[field] = args[field]

    problems = mapkit.validate(data)
    if problems:
        return "The change would break the map:\n" + "\n".join(problems)

    failed = write_map(source, data, seen)
    if failed:
        return failed

    return f"{args['id']} updated in {source}."


def tool_remove_node(session, args):
    source, data, seen = open_map_file(session, args)
    if source is None:
        return data

    node_id = args["id"]
    if not any(n["id"] == node_id for n in data["nodes"]):
        return f"{node_id} is not on this map."

    data["nodes"] = [n for n in data["nodes"] if n["id"] != node_id]
    dropped = [e for e in data["edges"] if node_id in (e[0], e[1])]
    data["edges"] = [e for e in data["edges"] if node_id not in (e[0], e[1])]

    problems = mapkit.validate(data)
    if problems:
        return "Removing it would break the map:\n" + "\n".join(problems)

    failed = write_map(source, data, seen)
    if failed:
        return failed

    return f"{node_id} removed from {source}, along with {len(dropped)} edge(s)."


def tool_select_on_map(session, args):
    state, url, name = state_of(session, args)
    state.update(focus={"node": args["node"], "note": args.get("note", "")})
    return f"{args['node']} is selected on the map at {url}/map/{name}."


def tool_ask_on_map(session, args):
    state, url, name = state_of(session, args)
    node = args["node"]
    timeout = float(args.get("timeout_seconds", 900))

    seen = len([m for m in state.snapshot()["chat"] if m["role"] == "you"])
    state.update(focus={"node": node, "note": args.get("note", "")})

    def answer(snapshot):
        # The end of the round outranks anything said in it: the last line Apply
        # writes is a summary of the round, not an answer to this question.
        if snapshot["ended"]:
            return "ended"
        return said_by_reader(snapshot, seen)

    fresh = state.wait_for(answer, timeout)

    if fresh == "ended":
        end_of_round(state)
        state.mark_delivered()
        state.update(focus=None)
        return FINISHED

    if fresh is None:
        state.update(focus=None)
        return f"Nothing said about {node} within {timeout:.0f}s. It is still open on the map at {url}/map/{name}."

    state.mark_delivered()
    return json.dumps({"asked": node, "said": [{"text": m["text"], "about": m["about"]} for m in fresh]}, ensure_ascii=False)


def tool_wait_for_message(session, args):
    state, url, name = state_of(session, args)
    timeout = float(args.get("timeout_seconds", 1500))
    seen = len([m for m in state.snapshot()["chat"] if m["role"] == "you"])

    def next_line(snapshot):
        if snapshot["ended"]:
            return "ended"
        return said_by_reader(snapshot, seen)

    fresh = state.wait_for(next_line, timeout)
    if fresh == "ended":
        end_of_round(state)
        state.mark_delivered()
        return FINISHED
    if fresh is None:
        return f"Nothing said on the map within {timeout:.0f}s. It is still open at {url}/map/{name}."

    state.mark_delivered()
    return json.dumps(
        [{"text": m["text"], "about": m["about"], "at": m["at"]} for m in fresh],
        ensure_ascii=False,
    )


def tool_resolve_on_map(session, args):
    """
    Settles a question on the map and in the file behind it: the node stops
    being a question and becomes the decision that was taken, so the record
    survives the conversation.
    """
    state, _, name = state_of(session, args)
    node_id = args["node"]
    answer = args["answer"]

    state.add_message("claude", f"Settled: {answer}", node_id)
    state.resolve(node_id, answer)

    source = maps.maps_in(session.root)[name]
    data = mapkit.load(source)
    seen = mapkit.map_stamp(source)
    node = next((n for n in data["nodes"] if n["id"] == node_id), None)
    if node is None:
        return f"{node_id} is settled on the map: {answer}. The file holds no such node."

    node["kind"] = "decision"
    node["status"] = "decided"
    node["why"] = (node.get("why") + " " if node.get("why") else "") + f"Settled on the map: {answer}"
    node.pop("options", None)

    problems = mapkit.validate(data)
    if problems:
        return f"{node_id} is settled on the map, but the file was left alone:\n" + "\n".join(problems)

    failed = write_map(source, data, seen)
    if failed:
        return f"{node_id} is settled on the map, but the file was not written: {failed}"

    return f"{node_id} is settled: {answer}. {source} now records it as a decision."


def tool_reply_on_map(session, args):
    state, _, _ = state_of(session, args)
    state.add_message("claude", args["text"], args.get("node"))
    return "Replied in the conversation." + (f" Subject: {args['node']}." if args.get("node") else "")


def tool_wait_for_apply(session, args):
    state, url, name = state_of(session, args)
    timeout = float(args.get("timeout_seconds", 1500))
    before = state.snapshot()["applied"]

    applied = state.wait_for(
        lambda snap: snap["applied"] if snap["applied"] != before else None, timeout
    )

    if applied is None:
        return f"Apply was not pressed within {timeout:.0f}s. The map is still open at {url}/map/{name}."

    return json.dumps(applied, ensure_ascii=False, indent=2)


HANDLERS = {
    "open_map": tool_open_map,
    "open_questions": tool_open_questions,
    "add_node": tool_add_node,
    "edit_node": tool_edit_node,
    "remove_node": tool_remove_node,
    "select_on_map": tool_select_on_map,
    "read_state": tool_read_state,
    "ask_on_map": tool_ask_on_map,
    "wait_for_message": tool_wait_for_message,
    "reply_on_map": tool_reply_on_map,
    "resolve_on_map": tool_resolve_on_map,
    "wait_for_apply": tool_wait_for_apply,
}


def call_tool(session, params):
    name = params.get("name")
    handler = HANDLERS.get(name)
    if handler is None:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

    try:
        text = handler(session, params.get("arguments") or {})
    except NoMap as nothing:
        return {"content": [{"type": "text", "text": str(nothing)}], "isError": True}
    except Exception as error:
        return {"content": [{"type": "text", "text": f"{name} failed: {error}"}], "isError": True}

    return {"content": [{"type": "text", "text": text}]}


def handle(session, message):
    """Answers one JSON-RPC request; returns None for a notification."""
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        # Start the map server at once: the Stop hook looks up its address in a
        # file, and until something has started it, there is nothing to look up.
        try:
            session.ensure()
        except OSError:
            pass

        # Echo the client's protocol revision when it names one: the client
        # picks the dialect, and this server speaks nothing revision-specific.
        asked = (message.get("params") or {}).get("protocolVersion")
        result = {
            "protocolVersion": asked if isinstance(asked, str) else PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "clauded", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = call_tool(session, message.get("params") or {})
    elif method in ("ping",):
        result = {}
    elif request_id is None:
        return None
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main():
    root = Path.cwd()
    port = DEFAULT_PORT
    session = Session(root, port)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        answer = handle(session, message)
        if answer is not None:
            sys.stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
