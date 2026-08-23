# PLAN

Destination: Claude and Edmond design against one shared picture — Claude
collects questions onto a map and does nothing until Edmond presses Apply.

## Fog

- Whether the reverse channel should be a blocking tool call, a `claude/channel`
  push, or both side by side.
- What the architecture map cites when a module has no single file.
- Whether a map should ever be regenerated automatically, or only on request.

## S1 — The page  [done]

- [x] S1.1 Render a graph of records with a panel, aspect colours and hiding
      done: a map of 13 nodes renders, hiding an aspect drops its subtree
      handoff: aspects carry three hues in rotation; a fourth reuses the first
- [x] S1.2 Build the page from YAML with validation
      done: a valid map renders, a map with a missing field or a dangling edge exits 1
- [x] S1.3 Answers, questions and Apply
      done: answers and asks survive a reload and leave the page only on Apply
- [x] S1.4 One question at a time, and a code window with syntax colouring
      done: `q` opens the walkthrough; a cited fragment opens with line numbers

## S2 — The reverse channel

- [ ] S2.1 Decide the shape of the channel
      done: choice and reason recorded in dev/DECISIONS.md
      tier: T2
- [ ] S2.2 MCP server over stdio, no npm dependencies
      done: `tools/list` and `tools/call` answer over stdio; the server starts from .mcp.json
      tier: T2
- [ ] S2.3 Serve the page and read the selection
      done: a tool returns the node selected with the mouse in the open page
      tier: T2
- [ ] S2.4 Ask one question on the map and wait for the answer
      done: a tool highlights one question and returns the answer Edmond gives
      tier: T2
- [ ] S2.5 Apply hands the draft to the session
      done: pressing Apply reaches the session without the clipboard
      tier: T2

## S3 — The mode in the skill

- [ ] S3.1 Write how the map carries rule 18
      done: working-with-edmond says when the map replaces the chat question loop
      tier: T1
- [ ] S3.2 Architecture map vocabulary against a real project
      done: a map of one existing project renders module, knowledge and dependency nodes
      tier: T2
