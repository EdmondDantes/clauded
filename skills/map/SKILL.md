---
name: map
description: Build or rebuild an interactive design or architecture map from the project's own records and open it. Use when asked for a map, a decision graph, or a picture of what is decided and what is still open — and when a design discussion has collected more open questions than fit in a chat reply.
---

# Build a map

A map is derived: it holds nothing that is not written in the project. Build it
from `dev/DECISIONS.md`, `dev/PLAN.md` (`## Fog` and `Decide` steps) and
`dev/ARCHITECTURE.md`, and rebuild it rather than editing the page.

## Steps

1. **Read the sources whole.** A grep gives a map with holes, and a hole reads
   as a decision nobody made.
2. **Write `dev/design/<name>.map.yaml`.** One node per record, with `id`,
   `kind`, `title`, `body` and `origin` — the file and place the record came
   from. Add `why`, `cost` and `status` when the source has them, `options` when
   a question has named alternatives, and `refs` to cite the code. A citation
   names a thing, never a line number: the render finds it, and an edit above it
   changes nothing.

   ```yaml
   refs:
     - file: src/Auth/Guard.php
       symbol: Guard.allows            # a def or class in Python, a heading in Markdown
     - file: web/app.js
       anchor: "function refresh() {"  # any language: a line of the file, written out
       until: "}"                      # ends there, at the anchor's own level
     - file: src/Auth/Session.php      # the whole file, when the file is the thing
   ```

   `span: 12` reads that many lines from the anchor instead. An anchor must
   appear once in the file — lengthen it if it does not. A node of kind `module`
   has to cite something: a module pointing at no code is the map holding
   knowledge of its own.

   A citation that stops resolving — a symbol renamed, an anchor edited away —
   fails loudly: the build refuses the map, and a served page draws that citation
   struck through with the reason on it. That is the point of the form. A line
   number gone stale looks exactly like one that has not.

3. **Edges only where the source states them.** A connection you can see but
   nobody wrote down belongs in `## Fog`, not on the map.
4. **Open it:**

   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/server/serve.py --root . --open <name>
   ```

   The server renders the page on each request and colours the cited code, so an
   edit to the YAML shows up on reload. Rendering fails on a missing field, a
   repeated id, a dangling edge or a cited file that is not there — fix the
   YAML, never the page.

   For a page to publish or to read without the server:

   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/tools/build-map.py dev/design/<name>.map.yaml --root . -o /tmp/<name>.html
   ```

5. **Commit the YAML only.** Generated pages stay out of git. Publishing a
   snapshot as an artifact is Edmond's call, not yours.

## Vocabularies

| Map | Node kinds |
|---|---|
| design | `aspect`, `question`, `decision`, `rejected` |
| architecture | `aspect`, `module`, `knowledge`, `dependency` |

An aspect groups nodes, gives them their colour, and can be hidden with its
whole subtree.

## Working on the map

Questions collected on the map are questions you have not acted on. The page
holds every thread until Apply is pressed; until then the work has not started.
This is rule 18 — one question at a time — with the map as its board.

With the plugin's MCP server running, the loop is:

1. `open_map` — the map opens where Edmond can see it.
2. `ask_on_map` with one node id. The call blocks, the page opens that question
   and marks it as waited on. Ask one question, never a list.
3. Read what came back and answer with `reply_on_map` — one conversation, and
   the node id you pass is its subject. When
   the question is settled, `resolve_on_map` marks it on the map so Edmond can
   see it is closed, then ask the next one.
4. You do not have to wait for the map: the plugin's Stop hook drains it before
   your turn ends and hands you what was written, so answer it and carry on.
   `wait_for_message` is for holding a turn open deliberately — it dies when
   Edmond types in the terminal, because that interrupts the turn.
5. `wait_for_apply` when the questions are done. Work starts on what it returns,
   and not before.
6. Finish ends the round and reaches you as one signal wherever you are: a
   waiting `ask_on_map` or `wait_for_message` returns "Edmond pressed Finish",
   and a turn that waits on nothing hears it from the Stop hook with the draft
   printed under it. Whoever hears it first spends it, so it is said once — stop
   asking, take the draft from `applied` (`read_state`, or what `wait_for_apply`
   returns) and report.

A project can hold several maps, and each keeps its own conversation: a reply
written on one is not on the other. Every tool takes `name` and falls back to
the map opened last, so name the map whenever two are in play. The page's title
lists the project's maps and opens the one picked.

The page's "One question at a time" button opens nothing of its own: it writes
the mode into the conversation as a message from Edmond, pointed at the first
open question. Reaching it means the loop above is what he wants — take the
questions one by one with `ask_on_map`, and settle each with `resolve_on_map`
before asking the next.

Without the server, the same loop runs through the chat, and Apply puts the
threads on the clipboard for Edmond to paste.

## Holding the conversation with a subagent

A blocking call in the main session dies the moment Edmond types in the
terminal. To keep a conversation running while he works on the page, launch a
background subagent whose whole job is the loop: `wait_for_message`, then
`reply_on_map`, then wait again, until Finish ends the round.

Give it the map's name, the address of the page already open — so it does not
call `open_map` and raise a second window — and enough of the current work to
answer without asking. The plugin's tools are deferred, so it loads them itself:

```
ToolSearch("select:mcp__plugin_clauded_clauded__wait_for_message,mcp__plugin_clauded_clauded__reply_on_map,mcp__plugin_clauded_clauded__add_node")
```

**Allow the writing tools before it starts.** Edmond asks the agent he is
talking to for a node on the map, not for a note about one, and a subagent that
may only read is stopped by the permission classifier before the call reaches
the plugin — the refusal arrives as a bare "Blocked by classifier", so the agent
cannot even explain what was refused. These belong in `permissions.allow`:

```
mcp__plugin_clauded_clauded__add_node
mcp__plugin_clauded_clauded__edit_node
mcp__plugin_clauded_clauded__remove_node
mcp__plugin_clauded_clauded__resolve_on_map
mcp__plugin_clauded_clauded__reply_on_map
mcp__plugin_clauded_clauded__select_on_map
```

The subagent writes the map and nothing else: the repository is the main
session's work, and a node written from a conversation is the record of that
conversation.
