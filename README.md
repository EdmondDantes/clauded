# clauded

Interactive design and architecture maps for Claude Code: a graph of the
records a project already keeps, rendered as one self-contained page you can
walk through, answer on, and hand back to Claude.

A map is derived. Knowledge stays in `dev/DECISIONS.md`, `dev/ARCHITECTURE.md`
and `dev/PLAN.md`; the map shows it as a graph and is rebuilt from those files
whenever they change. The rules that govern when a map is worth building live in
the `working-with-edmond` skill, rule 27.

## Install

```
/plugin marketplace add EdmondDantes/clauded
/plugin install clauded@clauded
```

The plugin brings the `/map` command and an MCP server named `clauded`. Python 3
with PyYAML is required; Pygments is optional and only colours cited code.

## Open a map

```
python3 server/serve.py --root . --open <name>
```

The server renders the page on each request, so an edit to the YAML shows up on
reload. It listens on 127.0.0.1 only, colours the cited code, and takes back
what you do on the page: the selected node and, on Apply, the answers.

The YAML is the source and belongs in git. Generated pages do not: nothing in
`dev/design/` is committed but the `.map.yaml` files.

For a page to publish or to read without the server:

```
python3 tools/build-map.py dev/design/<name>.map.yaml --root . -o /tmp/<name>.html
```

That snapshot shows cited code as plain text — a published artifact cannot load
a highlighter, so it does without one.

Rendering refuses a map whose node lacks a required field, whose id repeats,
whose edge names a node that is not there, or which cites a file that is
missing — all four look on the page like a record that exists.

## What the page does

- **Walk it.** Click a node to read the full record; its neighbours stay lit and
  everything else dims. Aspects carry their own colour and can be dropped from
  the view and brought back from the strip at the top.
- **Talk on it.** One conversation for the whole map, in its own column. What
  you select becomes the subject of the next line, and each line shows the
  subject it had; Claude selects a node too, when the answer is due there.
- **One question at a time.** The button on the strip hands Claude the mode and
  points it at the first open question; the questions then come one by one in
  the conversation, and each is settled on the map before the next is asked.
- **Read the code.** A node can cite files; the fragment is copied into the page
  as it is rendered and opens in a window, coloured when the server rendered it.
- **Apply.** Nothing leaves the page until Apply is pressed. Without the plugin
  running, Apply copies the threads as text for you to paste into the
  conversation; with it, they go straight to the session. Finish ends the round:
  the log marks the handover, and Claude is told the round is over wherever it
  is — in a call blocked on the map, or at the end of its turn.
- **Several maps.** A project can hold more than one, and the title in the
  header lists them. Each keeps its own conversation, its own settled marks and
  its own window arrangement.

Answers survive a reload through the browser's own storage and never travel
anywhere on their own.

## With Claude

The plugin carries an MCP server, so a session can work on the map instead of
in the chat:

| tool | what it does |
|---|---|
| `open_map` | render a map and hand back its address |
| `open_questions` | what is still open on it, so the round has an end |
| `add_node` | write a new node into the map while the talk goes on |
| `edit_node` | change what a node says |
| `remove_node` | take a node off the map when it turned out wrong |
| `read_state` | the selected node and the conversation as it stands |
| `select_on_map` | point at a node, making it the subject, without waiting |
| `ask_on_map` | point at one question and block until something is said |
| `wait_for_message` | block until anything is written anywhere on the map |
| `reply_on_map` | write a reply into a node's thread |
| `resolve_on_map` | mark a question settled, so the map shows it closed |
| `wait_for_apply` | block until Apply hands the whole draft over |

`ask_on_map` and `wait_for_message` block on purpose: while a question is open,
no work starts. The page picks the pointer up within a second and a half, opens
that question and says who is waiting.

Every tool takes `name` and falls back to the map opened last, so two maps in
one project never mix.

A blocking call is not how the conversation stays alive: typing in the terminal
interrupts the turn and the call with it. The plugin's Stop hook does that job —
before a turn ends it drains the inbox of every open map and blocks the stop, so
Claude answers whatever was written, whether or not it was waiting. Finish
travels the same way and is said once: whoever hears it first — a blocked call
or the hook — is the one told the round is over.

## Layout

```
web/map-template.html    the page: renderer, panel, walkthrough, code window
tools/mapkit.py          read, validate, inline cited code, colour, render
tools/build-map.py       one map to one HTML file, for publishing
server/maps.py           the server itself: renders, holds the threads, waits
server/serve.py          run the server on its own, without Claude
server/mcp.py            the MCP side: ask, reply, wait
skills/map/              the slash command that opens a map
dev/design/clauded.map.yaml   this project's own design map
```
