#!/usr/bin/env python3
"""Stop hook: hand Claude whatever was written on the map before the turn ends.

Waiting in a blocking tool call did not survive: any message typed in the
terminal interrupts the turn and the wait with it, and the map then talked to
nobody. This runs instead when Claude is about to stop, drains the map's inbox,
and blocks the stop so Claude answers what is there.

Silent by design: no map server, no messages, or anything unexpected means the
turn ends as it would have.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SERVERS = Path(os.environ.get("CLAUDED_HOME") or Path.home() / ".clauded") / "servers"
TIMEOUT = 2


def alive(record):
    """True while the process that wrote the record is still running."""
    try:
        os.kill(int(record["pid"]), 0)
    except (OSError, ValueError, KeyError):
        return False

    return True


def server_of(session):
    """
    The map server this session started, or None.

    Every server leaves a record naming its session, so a second session running
    at the same time does not take the first one's map. A server started by hand
    carries no session, and is taken only when it is the only one alive: with two
    unnamed servers there is nothing to tell them apart by.
    """
    if not SERVERS.is_dir():
        return None

    live = []
    for path in sorted(SERVERS.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        if alive(record):
            live.append(record)

    mine = [record for record in live if session and record.get("session") == session]
    if mine:
        return mine[-1]

    loose = [record for record in live if not record.get("session")]
    return loose[0] if len(loose) == 1 else None


def inbox(session):
    """Returns the messages waiting on this session's map, or an empty list."""
    record = server_of(session)
    if record is None:
        return []

    try:
        with urllib.request.urlopen(f"{record['url']}/api/inbox", timeout=TIMEOUT) as response:
            return json.loads(response.read()).get("messages") or []
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return []


def event():
    """The Stop event as the caller wrote it, or an empty one.

    The pipe must be read whatever happens: the caller writes the JSON and waits
    for it to be taken.
    """
    raw = sys.stdin.read()
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return {}


def main():
    # A stop that a hook already blocked carries this flag. Blocking again would
    # loop, and draining without blocking would drop the line, so the mail is
    # left where it is and waits for the next turn to end.
    stopping = event()
    if stopping.get("stop_hook_active"):
        return

    messages = inbox(stopping.get("session_id"))
    if not messages:
        return

    # Finish is not one more remark: it ends the round, and the turn that hears
    # about it has to stop asking rather than answer.
    ending = any(message.get("kind") == "finish" for message in messages)
    lines = [
        "Edmond pressed Finish on the map: the round is over. Take what is below as "
        "handed over, stop asking, and report."
        if ending else
        "Edmond wrote on the map. Answer with reply_on_map, then keep working:"
    ]

    for message in messages:
        # A project holds several maps and the sweep drains them all, so a line
        # says which map it was written on and reply_on_map can name it back.
        where = f"[{message['map']}] " if message.get("map") else ""

        if message.get("kind") == "finish":
            lines.append(f"- {where}FINISH — what he handed over:")
            lines.extend(f"    {row}" for row in message["text"].splitlines())
            continue

        about = f" (about {message['about']})" if message.get("about") else ""
        lines.append(f"- {where}{message['text']}{about}")

    # The decision travels twice. Claude Code 2.1.241 blocks on the flat
    # `decision`/`reason` pair alone; the Stop branch of `hookSpecificOutput` is
    # declared with `additionalContext` and nothing else, so the copy nested
    # there is stripped and costs only its own bytes. The wrong field name costs
    # the message itself — the inbox is drained either way, and a line nobody
    # was handed is a line Edmond wrote to nobody.
    reason = "\n".join(lines)
    print(json.dumps({
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "decision": "block",
            "reason": reason,
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
