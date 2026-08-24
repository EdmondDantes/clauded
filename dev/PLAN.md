# PLAN

Destination: Claude and Edmond design against one shared picture — Claude
collects questions onto a map and does nothing until Edmond presses Apply.

## Fog

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

## S2 — The local server  [done]

- [x] S2.1 Render on request instead of keeping a built page
      done: GET /map/<name> renders from the YAML; no .map.html is committed
      handoff: colouring is Pygments on the server; a static snapshot stays plain
- [x] S2.2 Take the page's state back
      done: POST /api/selection and /api/apply write .clauded/selection.json and pending.json

## S3 — The MCP side  [in progress]

- [x] S3.1 Decide blocking call, channel, or both
      done: the blocking call carries the work; a channel stays open as a later addition
      note: settled twice over. The blocking call carries a round, the Stop hook
        carries what was written when no call is waiting, and both work; a push
        into an idle session waits for the CLI to offer one (S3.8). This is the
        whole answer, and the question left the Fog on 2026-08-24.
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
      blocked: the CLI exposes no channel. Checked on 2026-08-24 against Claude
        Code 2.1.241: `claude --help` and `claude mcp --help` name no channel
        flag, and neither settings file mentions one. Until it appears, the Stop
        hook and a background subagent are what reach an idle session.

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
- [x] S6.2 The conversation grows without bound
      done: /api/updates serves from a given id, applied lines are trimmed on save
      tier: T1
      handoff: State.conversation takes `since` and answers what follows that
        message; an id it does not hold means the two are out of step and the
        whole log travels. The page sends the newest id it has and stores every
        line not yet handed over plus the last 200. Measured in the browser: 302
        lines saved down to 200 with both unsent ones kept. What is still
        unbounded is the server's own log, in memory and in the state file.
- [x] S6.3 A restart loses what was applied and re-delivers the inbox
      done: applied flags and delivered count survive a restart
      tier: T1
      handoff: nothing to fix — _restore already reads `delivered` and `applied`,
        and `ended` is deliberately not restored. Proved rather than assumed:
        three lines drained, a round finished, the server restarted; the three do
        not travel again, the draft is still in `applied`, and the inbox holds
        only the finish written after the drain.
- [x] S6.4 The first poll accepts the stamp without comparing
      done: the map stamp is baked into the page at render, like the build stamp
      tier: T1
      handoff: mapkit.render takes `stamp` and writes it into MAP_STAMP; the
        server passes the same string it answers with, so the first poll compares
        instead of accepting. build-map.py passes none, and a page opened as a
        file keeps the old behaviour. Checked against the server: the baked value
        equals the one /api/updates reports.
- [x] S6.5 A reload on a new build throws away a draft
      done: the page does not reload while a field holds text
      tier: T1
      handoff: the poll holds the reload back while the compose box holds text and
        says so once. Measured in the browser with a stubbed poll: the draft
        survived, one toast was shown, and the page did not reload.

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

## S10 — The end of the round  [done]

Goal: Finish reaches the agent as one unmistakable signal, whatever the agent
was doing at the time.
Done when: a waiting call, an idle turn's Stop hook and `read_state` all report
the same end, and no line is handed over twice.

- [x] S10.1 Finish is a signal, not one more line in the chat
      done: every waiting call answers the end in the same words, the Stop hook
        names it and prints the draft, and the signal is spent once
      tier: T2 · role: —
      handoff: State.finish keeps the draft, raises the flag and writes the
        summary under one lock, so a call woken by the summary cannot answer a
        finished round as a running one; the message carries kind "finish".
        take_end hands the flag to the first caller and clears it, the inbox
        clears it when it delivers the finish, and wait_for_apply spends both when
        it returns the draft. A call takes its lines through the inbox, so the
        hook never repeats what it already handed over. POST /api/end is
        gone — nothing called it — and the .end-talk style with it.
        The page marks the handover with a rule across the log and leaves the
        summary out — it repeats the lines above it — and the finish no longer
        counts as a line waiting to be handed over.

## S11 — What the reviews of 2026-08-24 found  [in progress]

A critic and a code reviewer read the per-map split and the round's end. Both
named the same two defects, and both were reproduced before anything was
changed. Fixed: a blocking call counted every line the reader had written as
handed over, so a line written while Claude worked reached nobody — the inbox is
now the one ledger, and a call takes only what it returns; `wait_for_apply` left
the end unspent, so the next wait answered a round that closed minutes ago; the
JSON-RPC loop served one request at a time, so a blocking call froze every other
tool in the session — each request now runs on its own thread, and a call the
client drops (`notifications/cancelled`, or closed input) stops waiting instead
of taking the next line with it; a page served at `/map/<name>/` read its name
off the address and talked about a map that does not exist — the name is baked
in like the stamp; a reload past 200 lines brought handed-over lines back as an
unsent draft; the state file was written without a rename, and a torn file reads
as an empty conversation; `Finish` could be pressed twice and replay the round;
`add_node` and its neighbours each answered "which map" differently.

`tests/run.py` holds the checks behind every closed step above, against the real
server and the real MCP handlers.

- [x] S11.1 One address file for every session
      done: two sessions at once, and each one's Stop hook reaches its own server
      tier: T2 · role: —
      handoff: a server writes ~/.clauded/servers/<pid>-<port>.json holding its
        url, root and the session that started it — CLAUDE_CODE_SESSION_ID, which
        Claude Code puts in the environment of an MCP server it starts and in the
        Stop event of the same session. The hook pairs itself by that id; a
        server started by hand carries no id and is taken only when it is the
        only one alive. A record is removed when its process ends, and a dead
        one is swept on the next start. Checked in tests/run.py: two servers,
        two sessions, each hook takes its own line and neither takes the other's.

- [x] S11.3 Two sessions on one project overwrite each other's state
      done: two servers on one project keep a conversation each, or one refuses to start
      tier: T2 · role: —
      handoff: they keep one conversation between them instead. A write takes the
        file's lock, reads what is there, merges and writes back; a read notices
        another server's write by the file's stamp and takes it in. What was
        handed to Claude became a set of message ids rather than a count, because
        the first three lines of a joined chat are not the three that travelled.
        Edmond chose this over one shared server per project: a daemon would move
        the whole Claude side onto HTTP for two fixes worth forty lines here.
- [x] S11.2 An upgrade keeps what the old page and the old server held
      done: a conversation written before the per-map split is still there after it
      tier: T1 · role: —
      handoff: the first map to ask for its state takes `.clauded/state.json` and
        renames it `state.json.taken`, so the next map is not handed the same
        conversation; the page does the same with the `map-chat` key. Both are
        one-time and leave nothing to read twice.

- [x] S11.4 A reloaded server keeps serving the project it served
      done: a page open on a map stays alive across /reload-plugins
      tier: T1 · role: —
      handoff: Claude Code starts an MCP server in the directory the session was
        started in, which is often a home directory with no maps, and the open
        page was then told its map does not exist. `~/.clauded/last-root` holds
        the last project actually served, and start() takes it when the directory
        it was given holds no maps at all. The session then follows the server's
        root rather than its own.

## S12 — What Edmond found on the map  [in progress]

He worked a round on the map with a subagent on 2026-08-24 and named what was
wrong with it. Fixed: the graph had three columns hardcoded by kind, so a
vocabulary of ten kinds had nowhere to stand — a column is now the distance from
a node nobody points at, counted along the edges, and there are as many columns
as the map is deep (measured: a chain of eight lays out in eight); a node
rewritten in place played the arrival animation and the view re-framed under the
reader, so a change now says so on its stripe alone and the framing is left
where it was; a write could only be checked by reading the YAML, which the map's
own contract forbids — `add_node` and `edit_node` answer with the node as the
file holds it, and `read_map` reads the map back; a design map silently accepted
`knowledge` nodes, and a map is now held to the vocabulary its own spec
declares.

- [x] S12.0 The Stop hook says nothing and eats the line
      done: a line written on the map reaches the next turn's end and is answered
      tier: T1 · role: —
      handoff: two faults, both silent. The manifest named hooks/hooks.json,
        which is loaded by its path alone, so the loader saw one file twice and
        the plugin brought no hook at all. With that fixed the hook ran and
        drained the inbox, but printed `permissionDecision` — a PreToolUse field
        the Stop branch ignores — so the line was taken and handed to nobody. The
        decision now travels as `hookSpecificOutput.decision` and as the flat
        pair, and a stop already blocked once (`stop_hook_active`) leaves the mail
        where it is instead of draining it.

- [x] S12.1 Finish hands over answers, not the last thing said
      done: `applied.answers` holds what settles a question, and nothing else
      tier: T1 · role: —
      handoff: only a line about a node whose kind is `question` counts, and only
        from the round being handed over. A remark about a decision or an aspect
        stays in the chat, where it is a remark.
- [ ] S12.2 A question settled in code but not in a document
      done: q-panel is closed on the map, and a document records why
      tier: T1 · role: —
      note: the page has the panel and no popover, so the question is settled in
        fact. `d-derived` requires a source document, and the project has no
        dev/DECISIONS.md to put it in — that file needs agreeing before the
        question can close.

## S13 — A citation names a thing  [done]

Goal: a record points at code that can still be found after the code moves.
Done when: an edit above a citation changes nothing, and a citation that no
longer resolves says so instead of showing whatever now stands there.

- [x] S13.1 Citations by symbol, by anchor, or by whole file
      done: both maps cite by name, a stale citation fails loudly, and a module
        node without a citation is refused
      tier: T2 · role: — (designed with Fable, whose anchor-first shape won over
        a symbol-first one: an anchor needs no language, and the file that would
        need symbol finding most — a 3000-line HTML holding JS and CSS — is
        exactly where a regex finder would lie)
      handoff: three forms in the YAML — `symbol` (a Python def or class, dotted
        for a method; a Markdown heading), `anchor` (a line of the file written
        out, with `until` or `span`), or `file` alone. A hand-written `lines:` is
        refused by validate, which forced the audit: three of the four citations
        on the design map pointed at unrelated code. Resolution is
        mapkit.cited_range; a build refuses a citation that will not resolve,
        while the server marks it dead on the page, because the map is the
        surface a round is worked on. Bought nothing: ctags or tree-sitter would
        make a citation mean different things on different machines, and the two
        finders worth having are eighty lines.
      note: this closed two lines of the Fog — what an architecture map cites
        when a module is not one file (several citations, and a module node must
        carry at least one), and whether line numbers or names win.

## S4 — The mode in the skill

- [x] S4.1 Architecture map vocabulary against a real project
      done: dev/design/architecture.map.yaml renders 15 nodes and 13 edges, every kind placed
      handoff: the page had no columns or markers for module, knowledge and dependency until now
- [x] S4.2 Install the plugin once and use it from a session
      done: installed from the marketplace, its tools answered, a question was asked and answered on the map
      handoff: a github source clones a second time without credentials — a relative source of "./" avoids it
