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
   a question has named alternatives, and `refs` to cite source files:

   ```yaml
   refs:
     - file: src/Auth/Guard.php
       lines: 12-40
   ```

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

The page's "One question at a time" button opens nothing of its own: it writes
the mode into the conversation as a message from Edmond, pointed at the first
open question. Reaching it means the loop above is what he wants — take the
questions one by one with `ask_on_map`, and settle each with `resolve_on_map`
before asking the next.

Without the server, the same loop runs through the chat, and Apply puts the
threads on the clipboard for Edmond to paste.
