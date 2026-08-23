# PLAN

Destination: Claude and Edmond design against one shared picture — Claude
collects questions onto a map and does nothing until Edmond presses Apply.

## Fog

- Whether the reverse channel should be a blocking tool call, a `claude/channel`
  push, or both side by side.
- What the architecture map cites when a module has no single file.
- Whether a map should ever be regenerated automatically, or only on request.
- Citing code by line number goes stale with the first edit above it; an anchor
  by symbol name would survive, and nothing decides which one wins yet.

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

## S2 — The local server  [done]

- [x] S2.1 Render on request instead of keeping a built page
      done: GET /map/<name> renders from the YAML; no .map.html is committed
      handoff: colouring is Pygments on the server; a static snapshot stays plain
- [x] S2.2 Take the page's state back
      done: POST /api/selection and /api/apply write .clauded/selection.json and pending.json

## S3 — The MCP side

- [ ] S3.1 Decide blocking call, channel, or both
      done: choice and reason recorded in dev/DECISIONS.md
      tier: T2
- [ ] S3.2 MCP server over stdio, standard library only
      done: tools/list and tools/call answer over stdio; the server starts from .mcp.json
      tier: T2
- [ ] S3.3 Read the selection from the session
      done: a tool returns the node Edmond has selected in the open page
      tier: T2
- [ ] S3.4 Ask one question on the map and wait
      done: a tool highlights one question and returns the answer given on the page
      tier: T2
- [ ] S3.5 Apply reaches the session without the clipboard
      done: pressing Apply lands in the conversation with no copy and paste
      tier: T2

## S4 — The mode in the skill

- [ ] S4.1 Architecture map vocabulary against a real project
      done: a map of one existing project renders module, knowledge and dependency nodes
      tier: T2
