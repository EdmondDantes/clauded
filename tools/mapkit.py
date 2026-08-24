"""Shared map machinery: read the YAML, check it, pull in cited code, render.

Both the command-line builder and the plugin server work through this module,
so a map means the same thing however it is opened. Colouring is optional: the
server asks for it, a static build does not, because a published artifact shows
the fragment as plain text.
"""

import html
import json
import os
import re
from pathlib import Path

import yaml

WEB = Path(__file__).resolve().parent.parent / "web"
TEMPLATE = WEB / "map-template.html"

REQUIRED_NODE_FIELDS = ("id", "kind", "title", "body", "origin")
DESIGN_KINDS = {"aspect", "question", "decision", "rejected"}
ARCHITECTURE_KINDS = {"aspect", "module", "knowledge", "dependency"}
# holds draws a solid line; rejects and needs draw dashed ones.
RELATIONS = {"holds", "rejects", "needs"}
STATUSES = {"open", "decided", "rejected"}
MAX_FRAGMENT_LINES = 400

SPAN = re.compile(r"<span[^>]*>|</span>")


def load(path):
    """Reads a map file. Raises the YAML error as is: it names line and column."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def save(path, data, seen=None):
    """
    Writes a map back, keeping the field order the file already uses.

    The write goes to a neighbouring file and is renamed into place, so a reader
    never sees half a document. `seen` is the stamp the caller read the file at:
    if the file moved on since then, someone else wrote it and this write is
    refused rather than silently winning.
    """
    path = Path(path)
    if seen is not None and path.exists() and map_stamp(path) != seen:
        raise ValueError(f"{path} changed since it was read — reload and try again")

    text = yaml.dump(data, allow_unicode=True, sort_keys=False, width=88, default_flow_style=False)
    temporary = path.with_suffix(path.suffix + ".writing")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def map_stamp(path):
    """Identifies the map's data precisely enough to catch two writes a second apart."""
    state = Path(path).stat()
    return f"{state.st_mtime_ns}-{state.st_size}"


def vocabulary(spec):
    """
    The kinds this map declares, taken from its own `spec.nodes`.

    The spec is written for a reader — "aspect · question · decision · rejected
    alternative" — so the words are matched against the kinds the renderer
    knows and the rest is ignored. An empty answer means the spec named none,
    and the map is then checked against every kind instead of its own.
    """
    known = DESIGN_KINDS | ARCHITECTURE_KINDS
    words = re.split(r"[^a-z]+", str((spec or {}).get("nodes") or "").lower())
    return {word for word in words if word in known}


def citation_problems(where, refs):
    """
    What is wrong with a node's citations, before any file is opened.

    A hand-written line number is refused outright: it names a place, and the
    place moves under the first edit above it, quietly. A name and a line of
    text are the two forms that move with the code.
    """
    problems = []

    for ref in refs:
        if not isinstance(ref, dict) or not ref.get("file"):
            problems.append(f"{where}: a ref needs a 'file' field")
            continue

        if ref.get("lines"):
            problems.append(f"{where}: {ref['file']} is cited by line number — "
                            "cite a 'symbol' or an 'anchor' instead, and let the render find it")
        if ref.get("symbol") and ref.get("anchor"):
            problems.append(f"{where}: {ref['file']} carries both a symbol and an anchor")
        if (ref.get("until") or ref.get("span")) and not ref.get("anchor"):
            problems.append(f"{where}: {ref['file']} has an ending without an anchor to start from")
        if ref.get("until") and ref.get("span"):
            problems.append(f"{where}: {ref['file']} says both how far to read and where to stop")

        span = ref.get("span")
        if span is not None and (not isinstance(span, int) or span < 1 or span > MAX_FRAGMENT_LINES):
            problems.append(f"{where}: {ref['file']} spans '{span}' — expected 1 to {MAX_FRAGMENT_LINES} lines")

    return problems


def validate(data):
    """Returns the list of problems found in the map; empty means it renders."""
    problems = []

    for field in ("title", "spec", "nodes", "edges"):
        if field not in data:
            problems.append(f"map: field '{field}' is missing")
    if problems:
        return problems

    # A map that declares its own vocabulary is held to it. A design map holding
    # a `knowledge` node is a map of two minds, and the reader has no way to tell
    # which meaning a colour carries.
    declared = vocabulary(data.get("spec"))
    kinds = declared or (DESIGN_KINDS | ARCHITECTURE_KINDS)
    seen = set()

    for index, node in enumerate(data["nodes"]):
        if not isinstance(node, dict):
            problems.append(f"node #{index + 1}: expected a mapping, not {type(node).__name__}")
            continue

        where = node.get("id") or f"node #{index + 1}"
        if node.get("status") and node["status"] not in STATUSES:
            problems.append(f"{where}: unknown status '{node['status']}'")
        if node.get("kind") == "question" and not node.get("status"):
            problems.append(f"{where}: a question needs a status, usually open")
        for field in REQUIRED_NODE_FIELDS:
            if not node.get(field):
                problems.append(f"{where}: field '{field}' is missing")
        if node.get("kind") and node["kind"] not in kinds:
            named = " this map declares" if declared else ""
            problems.append(f"{where}: '{node['kind']}' is not a kind{named} ({', '.join(sorted(kinds))})")
        if node.get("id") in seen:
            problems.append(f"{where}: id is used twice")
        seen.add(node.get("id"))

        problems.extend(citation_problems(where, node.get("refs") or []))
        # A module is a piece of the code, and a node that names one without
        # pointing at it is the one place the map is allowed to hold knowledge
        # of its own. It is not allowed.
        if node.get("kind") == "module" and not (node.get("refs") or []):
            problems.append(f"{where}: a module cites the code it is — give it a ref")

    if not any(node.get("kind") == "aspect" for node in data["nodes"]):
        problems.append("map: no aspect — every node hangs under one, and the filter needs it")

    for edge in data["edges"]:
        if len(edge) != 3:
            problems.append(f"edge {edge}: expected [from, to, relation]")
            continue
        source, target, relation = edge
        for end in (source, target):
            if end not in seen:
                problems.append(f"edge {edge}: '{end}' is not a node of this map")
        if relation not in RELATIONS:
            problems.append(f"edge {edge}: unknown relation '{relation}'")

    return problems


def colour(code, filename):
    """
    Returns one HTML string per line of code, or None when no highlighter is
    installed. Pygments marks a multi-line string or comment with a span that
    crosses line ends, so open spans are closed at each line break and reopened
    on the next line — otherwise splitting the markup would break the tags.
    """
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_for_filename, guess_lexer
        from pygments.util import ClassNotFound
    except ImportError:
        return None

    try:
        lexer = get_lexer_for_filename(filename, code)
    except ClassNotFound:
        try:
            lexer = guess_lexer(code)
        except ClassNotFound:
            return None

    marked = highlight(code, lexer, HtmlFormatter(nowrap=True))
    lines = []
    open_tags = []

    for line in marked.split("\n"):
        prefix = "".join(open_tags)
        for tag in SPAN.findall(line):
            if tag == "</span>":
                if open_tags:
                    open_tags.pop()
            else:
                open_tags.append(tag)
        lines.append(prefix + line + "</span>" * len(open_tags))

    # Pygments ends its output with a newline, and a fragment may itself end in
    # blank lines: the count is trimmed or padded to the code it came from, so
    # line numbers on the page stay aligned with the file.
    wanted = len(code.split("\n"))
    del lines[wanted:]
    lines.extend([""] * (wanted - len(lines)))
    return lines


# The extensions whose structure is plain enough to find a name in without
# parsing. Everything else — JavaScript, CSS, whatever sits inside an HTML file —
# is cited by an anchor instead, which needs no language at all.
SYMBOL_LANGUAGES = {".py", ".md"}


def python_symbol(lines, name, start=0, end=None):
    """
    The line range of a `def` or `class`, or None.

    The extent is where the indentation returns to the definition's own level,
    which is what makes Python findable without a parser. A dotted name is a
    name inside the range of the one before it.
    """
    end = len(lines) if end is None else end
    if "." in name:
        outer, inner = name.split(".", 1)
        holder = python_symbol(lines, outer, start, end)
        return python_symbol(lines, inner, holder[0], holder[1] + 1) if holder else None

    head = re.compile(rf"^(\s*)(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b")
    for index in range(start, end):
        found = head.match(lines[index])
        if not found:
            continue

        indent = len(found.group(1))
        last = index
        for after in range(index + 1, end):
            line = lines[after]
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            if line.strip():
                last = after

        return index, last

    return None


def markdown_symbol(lines, name):
    """The line range of a heading, from it to the next heading as high or higher."""
    head = re.compile(r"^(#+)\s*(.+?)\s*$")
    for index, line in enumerate(lines):
        found = head.match(line)
        if not found or not found.group(2).startswith(name):
            continue

        depth = len(found.group(1))
        for after in range(index + 1, len(lines)):
            next_head = head.match(lines[after])
            if next_head and len(next_head.group(1)) <= depth:
                return index, after - 1

        return index, len(lines) - 1

    return None


def find_symbol(path, lines, name):
    """Returns (first, last) zero-based for a named thing, or a problem string."""
    suffix = Path(path).suffix
    if suffix not in SYMBOL_LANGUAGES:
        return f"{path}: no symbol finder for {suffix or 'this file'} — cite it with an anchor"

    span = python_symbol(lines, name) if suffix == ".py" else markdown_symbol(lines, name)
    if span is None:
        return f"{path}: no symbol named '{name}'"

    return span


def find_anchor(path, lines, ref):
    """
    Returns (first, last) zero-based for an anchored citation, or a problem.

    The anchor is a line of the file, written out and compared with its own
    whitespace stripped. It must appear once: a citation that has to say which
    of three it means is a line number again, and rots the same way.

    `until` ends the citation at the first later line that reads the same and
    stands no deeper — which is what makes a bare `}` usable as an ending. To
    stop somewhere inside the block, count the lines with `span`.
    """
    wanted = str(ref["anchor"]).strip()
    hits = [index for index, line in enumerate(lines) if line.strip() == wanted]
    if not hits:
        return f"{path}: no line reads '{wanted}'"
    if len(hits) > 1:
        found = ", ".join(str(index + 1) for index in hits[:4])
        return f"{path}: '{wanted}' appears on lines {found} — make the anchor longer"

    first = hits[0]
    if ref.get("span"):
        return first, min(first + int(ref["span"]) - 1, len(lines) - 1)

    if ref.get("until"):
        # The closing line at the anchor's own level, so a `}` inside the block
        # does not end it. Indentation is not written out in the citation.
        closing = str(ref["until"]).strip()
        level = len(lines[first]) - len(lines[first].lstrip())
        for after in range(first + 1, len(lines)):
            line = lines[after]
            if line.strip() == closing and len(line) - len(line.lstrip()) <= level:
                return first, after
        return (f"{path}: nothing after the anchor reads '{closing}' at its own level — "
                "a line inside the block is reached with 'span' instead")

    return first, first


def cited_range(path, lines, ref):
    """
    Returns (first, last) zero-based for a citation, or a problem string.

    Three forms, and none of them is a line number: a whole file, a named thing,
    or an anchor. A number written by hand points at a place, and the place moves
    with the first edit above it; a name and a line of text move with the code.
    """
    if ref.get("symbol"):
        return find_symbol(path, lines, str(ref["symbol"]))
    if ref.get("anchor"):
        return find_anchor(path, lines, ref)

    return 0, len(lines) - 1


def read_fragment(root, ref, coloured):
    """Fills ref with the cited lines; returns the problem, or None."""
    path = Path(root) / ref["file"]
    if not path.is_file():
        return f"{ref['file']}: no such file under {root}"

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return f"{ref['file']}: the file is empty"

    found = cited_range(ref["file"], lines, ref)
    if isinstance(found, str):
        return found

    first, last = found[0] + 1, found[1] + 1
    # A whole file is cited, not excerpted: the page opens it through the server
    # rather than carrying it, and the cap is about what fits on a card.
    if not ref.get("symbol") and not ref.get("anchor"):
        ref["lines"] = ""
        ref.pop("code", None)
        ref.pop("html", None)
        return None

    if last - first + 1 > MAX_FRAGMENT_LINES:
        return f"{ref['file']}: {last - first + 1} lines is too much to read on a card"

    ref["code"] = "\n".join(lines[first - 1:last])
    ref["lines"] = f"{first}-{last}" if first != last else str(first)
    ref.pop("html", None)

    if coloured:
        marked = colour(ref["code"], ref["file"])
        if marked:
            ref["html"] = marked

    return None


def collect_fragments(data, root, coloured=False, strict=True):
    """
    Fills in the code of every citation; returns the problems found.

    `strict` decides what a citation that no longer resolves costs. A build
    refuses the map: a published page has nobody present to notice. A served page
    marks the citation dead and carries on — the map is the surface a round is
    worked on, and a stale ref must not stand between Edmond and an open
    question.
    """
    problems = []

    for node in data["nodes"]:
        for ref in node.get("refs") or []:
            if not isinstance(ref, dict) or "file" not in ref:
                problems.append(f"{node.get('id')}: a ref needs a 'file' field")
                continue

            problem = read_fragment(root, ref, coloured)
            if not problem:
                ref.pop("error", None)
                continue

            if strict:
                problems.append(f"{node.get('id')}: {problem}")
            else:
                ref["error"] = problem
                ref.pop("code", None)
                ref.pop("html", None)

    return problems


def build_stamp(template=None):
    """Identifies the page code being served: its file's modification time."""
    path = Path(template or TEMPLATE)
    return str(int(path.stat().st_mtime))


def render(data, template=None, stamp=None, name=None):
    """
    Substitutes the MAP literal, the title, the build stamp and the map's own
    stamp into the template.

    `stamp` identifies the data this page was rendered from. The page compares
    it with what the server reports and refetches when the two differ, so it has
    to be the same string the server would answer with; left out, the page waits
    for the first poll to tell it where it stands.

    `name` is the map's name on the server. Without it the page reads its name
    off the address, and an address that ends in a slash leaves it talking about
    a map that does not exist.
    """
    path = Path(template or TEMPLATE)
    text = path.read_text(encoding="utf-8")
    text = text.replace('const BUILD = "dev";', f'const BUILD = "{build_stamp(path)}";', 1)
    if stamp:
        text = text.replace('const MAP_STAMP = "dev";', f'const MAP_STAMP = "{stamp}";', 1)
    if name:
        text = text.replace('const SERVED_AS = "";', f'const SERVED_AS = "{name}";', 1)
    # A "</script>" anywhere in the data would close the tag the literal sits in.
    literal = "const MAP = " + json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/") + ";"
    page, count = re.subn(r"const MAP = \{.*?\n\};", lambda _: literal, text, count=1, flags=re.S)
    if count != 1:
        raise ValueError("no MAP literal to replace — the template changed shape")

    # The tag, not document.title, names the page in a browser tab and in the
    # artifact gallery, so the title travels into the markup as well.
    return re.sub(r"<title>.*?</title>", f"<title>{html.escape(data['title'])}</title>", page, count=1, flags=re.S)


def build(path, root=".", coloured=False, template=None, stamp=None, name=None, strict=True):
    """
    Loads, checks and renders one map. Raises ValueError listing every problem.

    `strict` is what a citation that no longer resolves costs, and it differs by
    who is looking: see collect_fragments.
    """
    data = load(path)
    problems = validate(data)
    if not problems:
        problems = collect_fragments(data, root, coloured, strict)
    if problems:
        raise ValueError("\n".join(problems))

    return data, render(data, template, stamp, name)
