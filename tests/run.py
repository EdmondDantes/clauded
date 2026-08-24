#!/usr/bin/env python3
"""Checks the plugin against the conditions dev/PLAN.md closes its steps on.

Run it from anywhere: `python3 tests/run.py`. It builds a throwaway project of
two maps in a temporary directory, starts the real server on a spare port and
drives the real MCP handlers, so what it proves is what ships. It writes nothing
outside the temporary directory and prints one line per check.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "server"))

import maps
import mcp

PORT = 8899
FAILED = []

# The session these servers claim to belong to. The Stop hook pairs itself with
# a server by this id, and a run that borrowed the real one would leave records
# that a live session's hook would then follow into a temporary directory.
SESSION = "clauded-tests"


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{label}: {got!r}" + ("" if ok else f" != {want!r}"))
    if not ok:
        FAILED.append(label)


def project(root):
    """Writes two small but valid maps, so the tests need no fixtures on disk."""
    (root / "dev" / "design").mkdir(parents=True)
    for name, title in (("alpha", "Alpha"), ("beta", "Beta")):
        (root / "dev" / "design" / f"{name}.map.yaml").write_text(f"""title: {title}
source: tests
spec:
  nodes: aspect | question | decision | rejected
  sources: [tests]
  edge: holds
nodes:
  - id: a
    kind: aspect
    title: An aspect
    body: nothing
    origin: tests
  - id: q
    kind: question
    status: open
    title: A question
    body: nothing
    origin: tests
edges:
  - [a, q, holds]
""", encoding="utf-8")


class Server:
    """The real server on a spare port, with the calls the page and hook make."""

    def __init__(self, root):
        self.root = root
        self.server, self.board, self.url = maps.start(str(root), PORT)

    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=5) as answer:
            return json.loads(answer.read())

    def page(self, path):
        with urllib.request.urlopen(self.url + path, timeout=5) as answer:
            return answer.read().decode()

    def post(self, path, payload):
        request = urllib.request.Request(
            self.url + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as answer:
            return json.loads(answer.read())

    def stop(self):
        self.server.shutdown()


def state_is_per_map(root):
    """S6.1: two maps of one project share nothing."""
    live = Server(root)
    live.post("/api/message", {"map": "alpha", "text": "for alpha", "about": "q"})
    live.post("/api/message", {"map": "beta", "text": "for beta"})

    alpha = live.get("/api/updates?map=alpha")
    beta = live.get("/api/updates?map=beta")
    check("chats stay apart", ([m["text"] for m in alpha["chat"]], [m["text"] for m in beta["chat"]]),
          (["for alpha"], ["for beta"]))

    maps.map_changed("alpha")
    check("a write moves one stamp", (live.get("/api/updates?map=alpha")["map"] != alpha["map"],
                                      live.get("/api/updates?map=beta")["map"] == beta["map"]), (True, True))

    live.board.state(str(root), "alpha").resolve("q", "yes")
    check("settled marks stay apart", (list(live.get("/api/updates?map=alpha")["resolved"]),
                                       list(live.get("/api/updates?map=beta")["resolved"])), (["q"], []))
    check("one state file per map", sorted(p.name for p in (root / ".clauded").glob("*.state.json")),
          ["alpha.state.json", "beta.state.json"])

    swept = live.get("/api/inbox")["messages"]
    check("the sweep drains both", sorted((m["map"], m["text"]) for m in swept),
          [("alpha", "for alpha"), ("beta", "for beta")])
    check("and only once", live.get("/api/inbox")["messages"], [])

    for path, want in (("/api/updates", 400), ("/api/updates?map=nope", 404)):
        try:
            live.get(path)
            code = 200
        except urllib.error.HTTPError as refused:
            code = refused.code
        check(f"GET {path}", code, want)

    live.stop()


def the_wire_is_bounded(root):
    """S6.2 and S6.4: the page is told what it lacks, and knows its own stamp."""
    live = Server(root)
    for text in ("one", "two", "three"):
        live.post("/api/message", {"map": "alpha", "text": text})

    whole = live.get("/api/updates?map=alpha")["chat"]
    check("the whole log", [m["text"] for m in whole], ["one", "two", "three"])
    check("from the first", [m["text"] for m in live.get(f"/api/updates?map=alpha&since={whole[0]['id']}")["chat"]],
          ["two", "three"])
    check("from the last", live.get(f"/api/updates?map=alpha&since={whole[-1]['id']}")["chat"], [])
    check("from a stranger", len(live.get("/api/updates?map=alpha&since=nobody")["chat"]), 3)

    rendered = live.page("/map/alpha")
    baked = rendered.split('const MAP_STAMP = "')[1].split('"')[0]
    check("the page is rendered with its stamp", baked, live.get("/api/updates?map=alpha")["map"])
    check("and with its name", 'const SERVED_AS = "alpha";' in rendered, True)
    live.stop()


def a_restart_remembers(root):
    """S6.3: what was handed over stays handed over."""
    live = Server(root)
    for text in ("one", "two", "three"):
        live.post("/api/message", {"map": "alpha", "text": text})

    check("three lines are handed over", [m["text"] for m in live.get("/api/inbox?map=alpha")["messages"]],
          ["one", "two", "three"])
    live.post("/api/apply", {"map": "alpha", "summary": "# done\n- you: three", "answers": {}, "chat": []})
    live.stop()

    again = Server(root)
    back = again.board.state(str(root), "alpha").snapshot()
    check("the draft survives", back["applied"]["summary"], "# done\n- you: three")
    check("the count survives", back["delivered"], 3)
    check("the end is not restored", back["ended"], False)
    waiting = again.board.state(str(root), "alpha").inbox()
    check("only the finish waits", [(m["text"], m["kind"]) for m in waiting], [("# done\n- you: three", "finish")])
    again.stop()


def finish_is_one_signal(root):
    """S10: whoever hears the end first is the one told, and told once."""
    session = mcp.Session(str(root), PORT)
    session.ensure()
    session.last_map = "alpha"
    live = Server.__new__(Server)
    live.url = session.url

    def apply_soon(summary):
        time.sleep(0.4)
        live.post("/api/apply", {"map": "alpha", "summary": summary, "answers": {}, "chat": []})

    threading.Thread(target=apply_soon, args=("# one\n- you: keep the panel",), daemon=True).start()
    check("a question hears the end", mcp.tool_ask_on_map(session, {"node": "q", "timeout_seconds": 5}), mcp.FINISHED)
    check("and takes it with it", live.get("/api/inbox?map=alpha")["messages"], [])

    threading.Thread(target=apply_soon, args=("# two\n- you: ship it",), daemon=True).start()
    check("the conversation hears the same", mcp.tool_wait_for_message(session, {"timeout_seconds": 5}), mcp.FINISHED)

    threading.Thread(target=apply_soon, args=("# three\n- you: last word",), daemon=True).start()
    draft = mcp.tool_wait_for_apply(session, {"timeout_seconds": 5})
    check("the draft still comes back whole", json.loads(draft)["summary"], "# three\n- you: last word")
    check("and spends the signal", mcp.tool_wait_for_message(session, {"timeout_seconds": 2}).startswith("Nothing said"),
          True)

    live.post("/api/apply", {"map": "alpha", "summary": "# four\n- you: done", "answers": {}, "chat": []})
    hook = subprocess.run([sys.executable, str(HERE / "hooks" / "map-inbox.py")],
                          input=json.dumps({"session_id": SESSION}), capture_output=True, text=True, timeout=10)
    reason = json.loads(hook.stdout)["hookSpecificOutput"]["reason"]
    check("with nobody waiting, the hook says it", reason.splitlines()[0].startswith("Edmond pressed Finish"), True)
    check("and prints the draft", "    - you: done" in reason, True)
    session.server.shutdown()


def a_line_written_while_claude_works(root):
    """The one ledger: a line nobody was waiting for still reaches Claude."""
    session = mcp.Session(str(root), PORT)
    session.ensure()
    session.last_map = "alpha"
    live = Server.__new__(Server)
    live.url = session.url

    live.post("/api/message", {"map": "alpha", "text": "use Postgres, not SQLite"})
    threading.Thread(target=lambda: (time.sleep(0.4),
                                     live.post("/api/message", {"map": "alpha", "text": "and cap the pool at 8"})),
                     daemon=True).start()
    said = [m["text"] for m in json.loads(mcp.tool_wait_for_message(session, {"timeout_seconds": 5}))]
    check("the earlier line is not stepped over", said[0], "use Postgres, not SQLite")
    session.server.shutdown()


def the_pipe_serves_more_than_one(root):
    """A blocking call holds up neither the session nor the reader's next line."""
    answers, lock, start = {}, threading.Lock(), time.monotonic()
    proc = subprocess.Popen([sys.executable, str(HERE / "server" / "mcp.py")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, cwd=str(root))

    def read():
        for line in proc.stdout:
            message = json.loads(line)
            with lock:
                answers[message["id"]] = ((message.get("result") or {}).get("content") or [{}])[0].get("text", "")

    threading.Thread(target=read, daemon=True).start()

    def send(payload):
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def answered(rid, seconds=6):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            with lock:
                if rid in answers:
                    return answers[rid]
            time.sleep(0.05)
        return None

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    answered(1)
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": "open_map", "arguments": {"name": "alpha", "browser": False}}})
    answered(2)
    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "wait_for_message", "arguments": {"timeout_seconds": 30}}})
    time.sleep(0.5)
    send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
          "params": {"name": "read_state", "arguments": {}}})
    check("another tool answers while a call blocks", bool(answered(4)) and 3 not in answers, True)

    send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 3}})
    check("a dropped call lets go", (answered(3) or "").startswith("The call was dropped"), True)

    proc.stdin.close()
    proc.wait(timeout=10)


def a_map_holds_its_own_vocabulary(root):
    """A design map refuses a kind it never declared."""
    import mapkit

    source = root / "dev" / "design" / "alpha.map.yaml"
    data = mapkit.load(source)
    check("the fixture validates", mapkit.validate(data), [])
    check("it declares four kinds", sorted(mapkit.vocabulary(data["spec"])),
          ["aspect", "decision", "question", "rejected"])

    data["nodes"].append({"id": "k", "kind": "knowledge", "title": "t", "body": "b", "origin": "tests"})
    problems = mapkit.validate(data)
    check("a knowledge node is refused", len(problems) == 1 and "not a kind this map declares" in problems[0], True)


def a_write_can_be_checked(root):
    """A node written through the tools can be read back through them."""
    session = mcp.Session(str(root), PORT)
    session.ensure()
    session.last_map = "alpha"

    written = json.loads(mcp.tool_add_node(session, {
        "id": "q-new", "kind": "question", "status": "open", "title": "A new question",
        "body": "written by the tests", "edges": [["a", "q-new", "holds"]]}))
    check("add_node answers with the node", written["node"]["title"], "A new question")

    back = json.loads(mcp.tool_read_map(session, {"node": "q-new"}))
    check("read_map finds it", back["node"]["body"], "written by the tests")
    check("with the edge that holds it", back["edges"], [["a", "q-new", "holds"]])

    changed = json.loads(mcp.tool_edit_node(session, {"id": "q-new", "body": "rewritten"}))
    check("edit_node answers with the change", changed["node"]["body"], "rewritten")

    mcp.tool_remove_node(session, {"id": "q-new"})
    check("remove_node takes it off", mcp.tool_read_map(session, {"node": "q-new"}), "q-new is not on alpha.")
    session.server.shutdown()


def two_sessions_do_not_cross(root):
    """Each session's Stop hook reaches its own server and no other."""
    was = os.environ.get("CLAUDE_CODE_SESSION_ID")
    servers = []
    try:
        # A project each: two sessions on one project would also share its state
        # files, which is a separate hole and not what this checks.
        for session, port in (("tests-a", PORT + 1), ("tests-b", PORT + 2)):
            mine = root / session
            mine.mkdir()
            project(mine)
            os.environ["CLAUDE_CODE_SESSION_ID"] = session
            server, board, url = maps.start(str(mine), port)
            servers.append((session, server, url))

        for session, _, url in servers:
            request = urllib.request.Request(
                url + "/api/message",
                data=json.dumps({"map": "alpha", "text": f"written for {session}"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(request, timeout=5).read()

        for session, _, _ in servers:
            hook = subprocess.run([sys.executable, str(HERE / "hooks" / "map-inbox.py")],
                                  input=json.dumps({"session_id": session}), capture_output=True,
                                  text=True, timeout=10)
            reason = json.loads(hook.stdout)["hookSpecificOutput"]["reason"]
            check(f"the hook of {session} takes its own line", f"written for {session}" in reason, True)
            other = "tests-b" if session == "tests-a" else "tests-a"
            check(f"and not {other}'s", f"written for {other}" in reason, False)
    finally:
        for _, server, _ in servers:
            server.shutdown()
        if was is None:
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        else:
            os.environ["CLAUDE_CODE_SESSION_ID"] = was


def two_servers_on_one_project(root):
    """Two servers on one project keep every line, and hand each over once."""
    first = Server(root)
    second = Server.__new__(Server)
    second.root = root
    second.server, second.board, second.url = maps.start(str(root), PORT + 4)

    first.post("/api/message", {"map": "alpha", "text": "written on the first"})
    second.post("/api/message", {"map": "alpha", "text": "written on the second"})

    check("the first sees both", sorted(m["text"] for m in first.get("/api/updates?map=alpha")["chat"]),
          ["written on the first", "written on the second"])
    check("the second sees both", sorted(m["text"] for m in second.get("/api/updates?map=alpha")["chat"]),
          ["written on the first", "written on the second"])

    taken = sorted(m["text"] for m in first.get("/api/inbox?map=alpha")["messages"])
    check("one of them hands both over", taken, ["written on the first", "written on the second"])
    check("and the other has nothing left", second.get("/api/inbox?map=alpha")["messages"], [])

    first.stop()
    second.stop()


def the_old_state_is_inherited(root):
    """A conversation held before the split is taken by the first map to ask."""
    (root / ".clauded").mkdir(exist_ok=True)
    (root / ".clauded" / "state.json").write_text(json.dumps({
        "chat": [{"id": "old-1", "role": "you", "text": "written before the split", "about": None,
                  "at": "2026-08-23T10:00:00+00:00"}],
        "delivered": 0,
        "resolved": {"q": {"note": "settled long ago", "at": "2026-08-23T10:00:00+00:00"}},
        "applied": None,
    }, ensure_ascii=False), encoding="utf-8")

    live = Server(root)
    first = live.get("/api/updates?map=alpha")
    check("the first map takes it", [m["text"] for m in first["chat"]], ["written before the split"])
    check("with what was settled", list(first["resolved"]), ["q"])
    check("and it is not offered twice", live.get("/api/updates?map=beta")["chat"], [])
    check("the old file is set aside", (root / ".clauded" / "state.json").exists(), False)
    check("and kept under its own name", (root / ".clauded" / "state.json.taken").exists(), True)
    live.stop()


def main():
    os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION

    for run in (state_is_per_map, the_wire_is_bounded, a_restart_remembers, finish_is_one_signal,
                a_line_written_while_claude_works, the_pipe_serves_more_than_one,
                a_map_holds_its_own_vocabulary, a_write_can_be_checked,
                two_sessions_do_not_cross, two_servers_on_one_project,
                the_old_state_is_inherited):
        print(f"\n--- {run.__doc__.splitlines()[0]}")
        root = Path(tempfile.mkdtemp(prefix="clauded-test-"))
        try:
            project(root)
            run(root)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            time.sleep(0.2)

    print("\n" + ("all checks passed" if not FAILED else f"FAILED: {FAILED}"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
