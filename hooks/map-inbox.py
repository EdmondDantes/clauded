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
import sys
import urllib.error
import urllib.request
from pathlib import Path

ADDRESS = Path.home() / ".clauded" / "server.json"
TIMEOUT = 2


def inbox():
    """Returns the messages waiting on the map, or an empty list."""
    if not ADDRESS.is_file():
        return []

    try:
        url = json.loads(ADDRESS.read_text(encoding="utf-8"))["url"]
        with urllib.request.urlopen(f"{url}/api/inbox", timeout=TIMEOUT) as response:
            return json.loads(response.read()).get("messages") or []
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return []


def main():
    # The hook's own input is not needed, but it must be consumed: the caller
    # writes the event JSON to stdin and waits for the pipe to be read.
    sys.stdin.read()

    messages = inbox()
    if not messages:
        return

    lines = ["Edmond wrote on the map. Answer with reply_on_map, then keep working:"]
    for message in messages:
        about = f" (about {message['about']})" if message.get("about") else ""
        lines.append(f"- {message['text']}{about}")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "permissionDecision": "block",
            "permissionDecisionReason": "\n".join(lines),
        }
    }))


if __name__ == "__main__":
    main()
