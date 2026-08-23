# clauded

Interactive design and architecture maps for Claude Code: a graph of the
records a project already keeps, rendered as one self-contained page you can
walk through, answer on, and hand back to Claude.

A map is derived. Knowledge stays in `dev/DECISIONS.md`, `dev/ARCHITECTURE.md`
and `dev/PLAN.md`; the map shows it as a graph and is rebuilt from those files
whenever they change. The rules that govern when a map is worth building live in
the `working-with-edmond` skill, rule 27.

## Build a map

```
python3 tools/build-map.py dev/design/<name>.map.yaml --root .
```

The YAML is the source and belongs in git. The generated `.map.html` opens by
double-click, with no server and no network. `--root` says where the paths cited
by nodes start.

The build refuses to render a map whose node lacks a required field, whose id
repeats, whose edge names a node that is not there, or which cites a file that
is missing — all four look on the page like a record that exists.

## What the page does

- **Walk it.** Click a node to read the full record; its neighbours stay lit and
  everything else dims. Aspects carry their own colour and can be dropped from
  the view and brought back from the strip at the top.
- **Answer on it.** A question offers its options and a free field. Any node
  takes a question addressed to Claude — "why is this here?".
- **One question at a time.** Press `q` for the walkthrough: one card, one
  question, progress across the top.
- **Read the code.** A node can cite files; the fragment is copied into the page
  at build time and opens in a window with syntax colouring.
- **Apply.** Nothing leaves the page until Apply is pressed. Without the plugin
  running, Apply copies the answers as text for you to paste into the
  conversation; with it, they go straight to the session.

Answers survive a reload through the browser's own storage and never travel
anywhere on their own.

## Layout

```
web/map-template.html    the page: renderer, panel, walkthrough, code window
tools/build-map.py       YAML → page, with validation and fragment inlining
skills/map/              the slash command that builds and opens a map
server/                  MCP server: the reverse channel (planned, see dev/PLAN.md)
dev/design/clauded.map.yaml   this project's own design map
```
