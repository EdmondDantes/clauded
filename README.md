# clauded

clauded turns a project's own records into a graph you can walk, answer on, and
hand back to Claude. It is a Claude Code plugin: a local server that renders the
graph, an MCP server that lets a session ask questions on it and wait for the
answers, and a Stop hook that carries what you wrote back into the session even
when nothing was waiting.

A map is derived. The knowledge stays in `dev/DECISIONS.md`, `dev/ARCHITECTURE.md`
and `dev/PLAN.md`; the map is generated from them and can be thrown away. When
those files change, the map is rebuilt rather than edited.

## Install

```
/plugin marketplace add EdmondDantes/clauded
/plugin install clauded@clauded
```

Python 3 and PyYAML are required. Pygments is optional and only colours the code
a node cites. The plugin brings the `map` skill, the MCP server named `clauded`
and the Stop hook; nothing listens outside 127.0.0.1.

## Open a map

```
python3 server/serve.py --root . --open <name>
```

The server reads `dev/design/<name>.map.yaml` and renders the page on every
request, so an edit to the YAML shows on reload. With no `--open` it prints its
address and lists the maps it found.

Rendering refuses a map whose node lacks a required field, whose id repeats,
whose edge names a node that is not there, or which cites a file that is
missing. All four would look on the page like a record that exists.

For a page to publish, or to read without the server:

```
python3 tools/build-map.py dev/design/<name>.map.yaml --root . -o /tmp/<name>.html
```

That snapshot shows cited code as plain text: a published artifact cannot load a
highlighter.

## The map file

One YAML file per map, in `dev/design/`. The `spec` block says what this map's
words mean — two maps in a project may use different vocabularies.

```yaml
title: Payments — design map
source: dev/DECISIONS.md · 2026-08-24
spec:
  nodes: aspect · question · decision · rejected
  sources: [dev/DECISIONS.md]
  edge: belongs to aspect · answers question
nodes:
  - id: a-refunds
    kind: aspect
    title: Refunds
    body: What a refund does to a settled invoice.
    origin: dev/DECISIONS.md, 2026-08-24
  - id: q-partial
    kind: question
    status: open
    title: Are partial refunds allowed?
    body: A refund smaller than the invoice leaves a balance nobody owns.
    origin: open, 2026-08-24
    options: [yes, no, only before settlement]
    refs:
      - file: src/Payments/Refund.php
        lines: 12-40
edges:
  - [a-refunds, q-partial, holds]
```

| field | what it holds |
|---|---|
| `id` | unique within the map; edges and tools name it |
| `kind` | `aspect`, `question`, `decision`, `rejected` — or `module`, `knowledge`, `dependency` for an architecture map |
| `title`, `body` | one line, then the record itself |
| `origin` | which file and place the record came from |
| `why`, `cost`, `status` | written when the source has them |
| `options` | the alternatives a question names |
| `refs` | files to cite; the fragment is copied into the page as it renders |

An aspect groups the nodes under it, gives them their colour, and can be dropped
from the view with its whole subtree.

## What the page does

- **Walk it.** Click a node to read its record; its neighbours stay lit and the
  rest dims. The strip at the top drops an aspect from the view and brings it
  back.
- **Talk on it.** One conversation for the whole map. Whatever is selected
  becomes the subject of the next line, and each line carries the subject it had.
  Claude selects a node too, when the answer is due there.
- **One question at a time.** The button on the strip hands Claude the mode and
  points it at the first open question. The questions then arrive one by one, and
  each is settled on the map before the next is asked.
- **Read the code.** A node that cites a file opens it in a window, on the cited
  lines, coloured when the server rendered it.
- **Arrange it.** The card on the dock offers six arrangements; a handle between
  the panes resizes them, and either pane folds from its own head. The
  arrangement is per map and stays in the browser.
- **Finish.** Nothing leaves the page until Finish is pressed. With the plugin
  running the draft goes straight to the session; without it, the summary goes to
  the clipboard. The log marks the handover, and the button will not hand the
  same round over twice.

Lines you have written survive a reload through the browser's own storage, and
travel nowhere on their own.

## With Claude

The plugin carries an MCP server, so a session works on the map instead of in
the chat:

| tool | what it does |
|---|---|
| `open_map` | render a map and hand back its address |
| `open_questions` | what is still open on it, so the round has an end |
| `add_node` | write a new node while the talk goes on |
| `edit_node` | change what a node says |
| `remove_node` | take a node off the map when it turned out wrong |
| `select_on_map` | point at a node, making it the subject, without waiting |
| `read_state` | the selection, the conversation and what was handed over |
| `ask_on_map` | point at one question and block until something is said |
| `wait_for_message` | block until anything is written on the map |
| `reply_on_map` | write a reply into the conversation |
| `resolve_on_map` | settle a question, on the map and in the file behind it |
| `wait_for_apply` | block until Finish hands the whole draft over |

The round runs: `open_map`, then `ask_on_map` for one question, then
`reply_on_map` and `resolve_on_map` when it is settled, then the next question,
and `wait_for_apply` at the end. Work starts on what Finish returns and not
before.

`ask_on_map` and `wait_for_message` block on purpose: while a question is open,
no work starts. A blocking call is not what keeps the conversation alive, though
— typing in the terminal interrupts the turn and the call with it. The Stop hook
does that job: before a turn ends it drains the inbox of every open map and
blocks the stop, so Claude answers whatever was written, whether or not it was
waiting.

Finish reaches Claude as one signal wherever it is — a blocked call, or the Stop
hook at the end of a turn — and is said once: whoever hears it first is the one
told the round is over. The draft is in `applied`, which `read_state` shows and
`wait_for_apply` returns.

## Several maps in one project

Every `.map.yaml` in `dev/design/` is a map of its own, and the title in the
page's header lists them all. Each keeps its own conversation, its own settled
marks and its own window arrangement, in `.clauded/<map>.state.json`. Every tool
takes `name` and falls back to the map opened last.

## Tests

```
python3 tests/run.py
```

It builds a throwaway project of two maps in a temporary directory, starts the
real server on port 8899 and drives the real MCP handlers, then checks the
conditions `dev/PLAN.md` closes its steps on: state that stays per map, a
conversation that travels bounded, a restart that remembers what was handed
over, and Finish arriving as one signal. It writes nothing outside the temporary
directory.

## What it does not do

- **One server per session.** Each session starts its own on the first free port
  from 8791 and records the last one in `~/.clauded/server.json`, which the Stop
  hook reads. Two sessions at once, and the hook follows whichever started last.
- **Nothing wakes an idle session.** A session that is not in a turn hears
  nothing until its next turn ends; the Stop hook is the reverse channel, and a
  channel that pushes into an idle session does not exist here yet.
- **Citations are line numbers.** An edit above a cited range moves it, and the
  map keeps pointing where the code used to be.

## Layout

```
web/map-template.html        the page: graph, record, conversation, code window
tools/mapkit.py              read, validate, inline cited code, colour, render
tools/build-map.py           one map to one HTML file, for publishing
server/maps.py               the server: renders, holds the conversations, waits
server/serve.py              run the server on its own, without Claude
server/mcp.py                the MCP side: ask, reply, wait
hooks/map-inbox.py           the Stop hook that carries the map back to Claude
skills/map/SKILL.md          how Claude builds a map and runs a round on it
tests/run.py                 the checks behind the plan's closed steps
dev/design/*.map.yaml        this project's own maps
```
