#!/usr/bin/env python3
"""MCP server for clauded: Claude asks on the map and waits for the answer there.

Speaks JSON-RPC over stdin and stdout, one message per line, and runs the local
map server in the same process. Four tools:

    open_map          render a map and hand back its address
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
        "description": "What the open map shows now: the selected node, every thread with its messages, and the last Apply. Does not wait.",
        "inputSchema": {"type": "object", "properties": {}},
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
            },
            "required": ["node"],
        },
    },
    {
        "name": "reply_on_map",
        "description": "Write a reply into a node's thread, where it appears as a chat message from Claude. Does not wait.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {"type": "string", "description": "Node id whose thread the reply belongs to"},
                "text": {"type": "string", "description": "The reply, as the reader will see it"},
            },
            "required": ["node", "text"],
        },
    },
    {
        "name": "wait_for_message",
        "description": "Wait for the next message the reader writes anywhere on the map, and return it with its node. Call it again after replying to keep the conversation going.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout_seconds": {"type": "number", "description": "How long to wait; default 1500"},
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
        self.state = None
        self.url = None

    def ensure(self):
        with self.lock:
            if self.server is None:
                self.server, self.state, self.url = maps.start(self.root, self.port)
            return self.state, self.url

    def use(self, root):
        """Points the session at another project; returns the root in force."""
        with self.lock:
            if root:
                self.root = Path(root).expanduser().resolve()
                if self.server is not None:
                    self.server.root = self.root
            return self.root


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

    state, url = session.ensure()
    known = maps.maps_in(session.root)

    if name not in known:
        listing = ", ".join(known) or "none"
        return (f"No map named {name}. Maps under {session.root}: {listing}. "
                "Name the project root with `project`, or pass the path to the .map.yaml file.")

    address = f"{url}/map/{name}"
    if args.get("browser", True):
        webbrowser.open(address)

    return f"{address} — {known[name]}"


def tool_read_state(session, args):
    state, _ = session.ensure()
    return json.dumps(state.snapshot(), ensure_ascii=False, indent=2)


def said_by_reader(snapshot, node, seen):
    """The reader's messages in a thread beyond the ones already counted."""
    mine = [m for m in snapshot["threads"].get(node, []) if m["role"] == "you"]
    return mine[seen:] or None


def tool_ask_on_map(session, args):
    state, url = session.ensure()
    node = args["node"]
    timeout = float(args.get("timeout_seconds", 900))

    seen = len([m for m in state.snapshot()["threads"].get(node, []) if m["role"] == "you"])
    state.update(focus={"node": node, "note": args.get("note", "")})
    fresh = state.wait_for(lambda snap: said_by_reader(snap, node, seen), timeout)

    if fresh is None:
        state.update(focus=None)
        return f"Nothing said about {node} within {timeout:.0f}s. The question is still open on the map at {url}."

    return json.dumps({"node": node, "said": [message["text"] for message in fresh]}, ensure_ascii=False)


def tool_wait_for_message(session, args):
    state, url = session.ensure()
    timeout = float(args.get("timeout_seconds", 1500))

    def counted(snapshot):
        return sum(len([m for m in messages if m["role"] == "you"])
                   for messages in snapshot["threads"].values())

    seen = counted(state.snapshot())

    def fresh(snapshot):
        if counted(snapshot) <= seen:
            return None
        latest = None
        for node, messages in snapshot["threads"].items():
            for message in messages:
                if message["role"] != "you":
                    continue
                if latest is None or message["at"] >= latest[1]["at"]:
                    latest = (node, message)
        return latest

    found = state.wait_for(fresh, timeout)
    if found is None:
        return f"Nothing said on the map within {timeout:.0f}s. It is still open at {url}."

    node, message = found
    return json.dumps({"node": node, "text": message["text"], "at": message["at"]}, ensure_ascii=False)


def tool_resolve_on_map(session, args):
    state, _ = session.ensure()
    state.add_message(args["node"], "claude", f"Settled: {args['answer']}")
    state.resolve(args["node"], args["answer"])
    return f"{args['node']} is marked settled: {args['answer']}"


def tool_reply_on_map(session, args):
    state, _ = session.ensure()
    state.add_message(args["node"], "claude", args["text"])
    return f"Replied in the thread of {args['node']}."


def tool_wait_for_apply(session, args):
    state, url = session.ensure()
    timeout = float(args.get("timeout_seconds", 1500))
    before = state.snapshot()["applied"]

    applied = state.wait_for(
        lambda snap: snap["applied"] if snap["applied"] != before else None, timeout
    )

    if applied is None:
        return f"Apply was not pressed within {timeout:.0f}s. The map is still open at {url}."

    return json.dumps(applied, ensure_ascii=False, indent=2)


HANDLERS = {
    "open_map": tool_open_map,
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
    except Exception as error:
        return {"content": [{"type": "text", "text": f"{name} failed: {error}"}], "isError": True}

    return {"content": [{"type": "text", "text": text}]}


def handle(session, message):
    """Answers one JSON-RPC request; returns None for a notification."""
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
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
