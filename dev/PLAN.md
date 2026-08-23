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

## S3 — The MCP side  [in progress]

- [x] S3.1 Decide blocking call, channel, or both
      done: the blocking call carries the work; a channel stays open as a later addition
      handoff: a channel needs --channels and an Anthropic allowlist, the blocking call needs neither
- [x] S3.2 MCP server over stdio, standard library only
      done: initialize, tools/list and tools/call answered over stdio in one run
- [x] S3.3 Read the selection and the threads from the session
      done: read_state returns the selection and every thread
- [x] S3.4 Ask one question on the map and wait
      done: ask_on_map blocked until a message arrived and returned it; the page saw the pointer
- [x] S3.5 Apply reaches the session without the clipboard
      done: wait_for_apply returned the applied draft
- [x] S3.6 Reach the session without a waiting call
      done: a Stop hook drains the map's inbox and blocks the stop; checked — silent when empty, delivers once, silent again
      handoff: a blocking call dies on any terminal input, which is why waiting alone never worked
- [x] S3.7 Hold the conversation without the main session
      done: a background subagent runs wait → reply → wait and survives terminal input; seen running while Edmond typed
      handoff: the Stop hook only fires at the end of a turn, so an idle session never reacts on its own
- [ ] S3.8 The channel, so no agent has to be held open at all
      done: a message on the map wakes a session that is not in a turn
      tier: T2

## S5 — One conversation  [done]

- [x] S5.1 Replace the per-node threads with one log
      done: a line carries the node it is about; the reply and the settled mark came back through the page's endpoint
      handoff: Claude hears the page only while ask_on_map or wait_for_message is running
- [x] S5.2 Claude sets the subject as well
      done: select_on_map points at a node without waiting

## S6 — What the review found  [in progress]

Fable reviewed the live-map design on 2026-08-23. Fixed: the stamp is accepted
only after a successful refetch; writes are atomic and quote the stamp they read;
the stamp is nanosecond-precise and per map, with a generation counter behind it;
an undelivered line is marked and resent; the poll no longer overlaps itself; the
selection does not move while the reader types; the walkthrough keeps the draft
and follows the question rather than a position; a settled question keeps the
view where the reader put it; validate rejects an unknown status, a question
without one, and a node that is not a mapping; a closing script tag in the data
is escaped.

- [ ] S7.1 The rest of the design critique
      done: kickers, type registers, the control strip, gutters, the tooltip anchors and the chip counter are settled
      tier: T2
      note: a designer reviewed the page on 2026-08-23. Fixed already — the record
        no longer sits at a fixed height while the chat holds empty space; the dock
        width is clamped so the graph survives 1100px and a phone shows the map at
        all (the old phone rules lost on specificity and never applied); node state
        moved to a stripe of its own, so hover, selection, unread and settled stop
        speaking the same colour; selection dims the graph to .62 instead of .3;
        the close button lost its browser defaults; the Finish label stopped
        flickering. Left: two accent hues that duplicate aspect hues, kickers on
        every plate, six type sizes and three faces, the control strip reading as
        one undifferentiated row, 20px vs 16px gutters, the split looking like a
        scrollbar, Fit/Clear and the toast overlapping on a narrow stage, and the
        "3?/3" chip counter.

- [ ] S6.1 State is one per project, not per map
      done: two maps in one project keep separate chats, resolved marks and storage keys
      tier: T2
- [ ] S6.2 The conversation grows without bound
      done: /api/updates serves from a given id, applied lines are trimmed on save
      tier: T1
- [ ] S6.3 A restart loses what was applied and re-delivers the inbox
      done: applied flags and delivered count survive a restart
      tier: T1
- [ ] S6.4 The first poll accepts the stamp without comparing
      done: the map stamp is baked into the page at render, like the build stamp
      tier: T1
- [ ] S6.5 A reload on a new build throws away a draft
      done: the page does not reload while a field holds text
      tier: T1

## S4 — The mode in the skill

- [x] S4.1 Architecture map vocabulary against a real project
      done: dev/design/architecture.map.yaml renders 15 nodes and 13 edges, every kind placed
      handoff: the page had no columns or markers for module, knowledge and dependency until now
- [x] S4.2 Install the plugin once and use it from a session
      done: installed from the marketplace, its tools answered, a question was asked and answered on the map
      handoff: a github source clones a second time without credentials — a relative source of "./" avoids it
