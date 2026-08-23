# clauded

Interactive design and architecture maps for Claude Code: a graph of the
records a project already keeps, rendered as one self-contained page you can
walk through, answer on, and hand back to Claude.

A map is derived. Knowledge stays in `dev/DECISIONS.md`, `dev/ARCHITECTURE.md`
and `dev/PLAN.md`; the map shows it as a graph and is rebuilt from those files
whenever they change. The rules that govern when a map is worth building live in
the `working-with-edmond` skill, rule 27.

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
- **Answer on it.** A question offers its options and a free field. Any node
  takes a question addressed to Claude — "why is this here?".
- **One question at a time.** Press `q` for the walkthrough: one card, one
  question, progress across the top.
- **Read the code.** A node can cite files; the fragment is copied into the page
  as it is rendered and opens in a window, coloured when the server rendered it.
- **Apply.** Nothing leaves the page until Apply is pressed. Without the plugin
  running, Apply copies the answers as text for you to paste into the
  conversation; with it, they go straight to the session.

Answers survive a reload through the browser's own storage and never travel
anywhere on their own.

## Layout

```
web/map-template.html    the page: renderer, panel, walkthrough, code window
tools/mapkit.py          read, validate, inline cited code, colour, render
tools/build-map.py       one map to one HTML file, for publishing
server/serve.py          localhost server: renders on request, takes answers back
skills/map/              the slash command that opens a map
dev/design/clauded.map.yaml   this project's own design map
```
