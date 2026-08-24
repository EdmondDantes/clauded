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

- [x] S7.1 The rest of the design critique
      done: kickers, type registers, the control strip, gutters, the tooltip anchors and the chip counter are settled
      tier: T2
      handoff: the aspect palette moved to violet, cyan and magenta, so no aspect
        borrows a status hue; --step-micro and --gutter leave the page five sizes,
        two faces and one gutter; the strip is .bar-filters and .bar-actions with a
        rule between them; the handle draws a seam and a grip where it drew a
        filled bar; the toast took the top of the graph and no longer meets
        Fit/Clear; a chip prints its node count with an open-coloured pip instead
        of "3?/3"; the record heads with kind, state and the close on one line, and
        drops the state when the kind already says it.
        Measured in headless Chrome at 1440, 700 and 390: the handle keeps its axis
        in all four arrangements, the toast clears the toolbar at every width, and
        .stage no longer reaches past the window. Two defects found on the way and
        fixed — Chrome dropped the subject title whole out of an ellipsised box,
        and the auto grid columns of .stage and .dock let the header overflow a
        phone.

- [x] S6.1 State is one per project, not per map
      done: two maps in one project keep separate chats, resolved marks and storage keys
      tier: T2
      handoff: State takes a map name and writes .clauded/<map>.state.json; a Board
        makes one state per (project, map) on demand, and every endpoint that
        carries a conversation names its map — /api/updates?map=, and `map` in the
        body of a post. /api/inbox without a name still drains every opened map,
        which is what the Stop hook needs, and tags each line with its map. The
        page keys localStorage by map name, and the MCP tools take `name`,
        defaulting to the map opened last. Checked with two maps in one project:
        chats, settled marks, stamps and state files stay apart, a restart brings
        each back, and the browser page shows only its own map's lines.
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

## S8 — The window Edmond works in  [done]

Goal: the arrangement of the window is changed from the window itself, and it
holds still while it is being changed.
Done when: the dock reaches the top of the window, a splitter grows the pane the
drag points at, and the arrangement is picked from a card on the dock.

- [x] S8.1 The Finish label survives a redraw of the aspect strip
      done: pressing a layout control leaves the label and its counter in place
      tier: T1 · role: —
      handoff: the button is built empty and takes its text from updateApply, so
        renderAspectBar calls it at the end. Checked in the browser: the label
        held across an arrangement change and across hiding an aspect.
- [x] S8.2 A splitter grows the pane the drag points at
      done: every arrangement, phone width included, follows the pointer
      tier: T1 · role: —
      handoff: draggable reads the axis from the handle's own box and the
        direction from where the panel lies against it, so the arrangement is
        never consulted. Measured in the browser: the dock and the record grew
        by the drag distance in eight arrangements, and by 50px and 40px at
        390px wide, where the phone rules had sent the old drag sideways.
- [x] S8.3 The dock stands the full height of the window
      done: the title and the aspect strip end at the dock's edge
      tier: T2 · role: —
      handoff: the header and the aspect strip moved inside .stage, and body is
        one row holding main. The two panes sit in .dock-body, which is what the
        flow rules size now; .dock keeps a head above it.
- [x] S8.4 The arrangement is picked from a card on the dock
      done: one button on the dock head offers six arrangements; the aspect strip
        carries no layout buttons
      tier: T2 · role: —
      handoff: the card is a 3x2 table — a column is which edge the dock stands
        against, a row is how the panes divide it — drawn as SVG pictograms in
        currentColor, so the chosen one takes the accent. Swap sits under them.
- [x] S8.5 Each pane folds from its own head
      done: folding the record leaves the conversation the whole dock
      tier: T1 · role: —
      handoff: data-fold on main gives the folded pane's track to the other and
        hides the handle. Measured: folding the record took the chat from 774 to
        824px, folding the chat gave the record the dock.
- [x] S8.6 One question at a time is a message, not a window
      done: the button hands the agent the mode and opens no dialog
      tier: T2 · role: —
      handoff: the walkthrough dialog is gone — markup, styles and some 250
        lines of it. The button writes ONE_AT_A_TIME into the conversation and
        points at the first open question; checked that it reached /api/inbox.
        The skill says what to do on receiving it.
- [x] S8.7 The code window shows the file around the fragment
      done: the window opens on the cited lines and scrolls through the file
      tier: T2 · role: —
      handoff: GET /api/source?file= serves one file of the project, capped at
        4000 lines and coloured by the same mapkit.colour; a path outside the
        root is refused. Checked: mcp.py opened 609 rows with the cited 15
        tinted and scrolled to. Without the server the stored fragment stays.

## S9 — Several maps in one project  [in progress]

Goal: a project with more than one map is worked from the page, not from the
address bar.
Done when: the reader moves between maps without typing a URL, and each map
keeps its own conversation.

- [x] S9.1 The page offers the maps of the project
      done: a menu on the page lists every map and opens the one picked
      tier: T2 · role: —
      handoff: GET /api/maps answers name and title for every map of the project,
        keeping a map whose YAML no longer parses in the list under its name. The
        title in the header becomes a button when the answer holds more than one
        map, and the card under it links to /map/<name>, marking the open one with
        aria-current. Opened as a file the title stays plain text. Checked against
        the running server: both maps listed, the open one marked, /map/architecture
        answers 200.

## S4 — The mode in the skill

- [x] S4.1 Architecture map vocabulary against a real project
      done: dev/design/architecture.map.yaml renders 15 nodes and 13 edges, every kind placed
      handoff: the page had no columns or markers for module, knowledge and dependency until now
- [x] S4.2 Install the plugin once and use it from a session
      done: installed from the marketplace, its tools answered, a question was asked and answered on the map
      handoff: a github source clones a second time without credentials — a relative source of "./" avoids it
