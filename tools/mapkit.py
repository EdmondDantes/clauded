"""Shared map machinery: read the YAML, check it, pull in cited code, render.

Both the command-line builder and the plugin server work through this module,
so a map means the same thing however it is opened. Colouring is optional: the
server asks for it, a static build does not, because a published artifact shows
the fragment as plain text.
"""

import html
import json
import re
from pathlib import Path

import yaml

WEB = Path(__file__).resolve().parent.parent / "web"
TEMPLATE = WEB / "map-template.html"

REQUIRED_NODE_FIELDS = ("id", "kind", "title", "body", "origin")
DESIGN_KINDS = {"aspect", "question", "decision", "rejected"}
ARCHITECTURE_KINDS = {"aspect", "module", "knowledge", "dependency"}
RELATIONS = {"holds", "rejects"}
MAX_FRAGMENT_LINES = 400

SPAN = re.compile(r"<span[^>]*>|</span>")


def load(path):
    """Reads a map file. Raises the YAML error as is: it names line and column."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def validate(data):
    """Returns the list of problems found in the map; empty means it renders."""
    problems = []

    for field in ("title", "spec", "nodes", "edges"):
        if field not in data:
            problems.append(f"map: field '{field}' is missing")
    if problems:
        return problems

    kinds = DESIGN_KINDS | ARCHITECTURE_KINDS
    seen = set()

    for index, node in enumerate(data["nodes"]):
        where = node.get("id") or f"node #{index + 1}"
        for field in REQUIRED_NODE_FIELDS:
            if not node.get(field):
                problems.append(f"{where}: field '{field}' is missing")
        if node.get("kind") and node["kind"] not in kinds:
            problems.append(f"{where}: unknown kind '{node['kind']}'")
        if node.get("id") in seen:
            problems.append(f"{where}: id is used twice")
        seen.add(node.get("id"))

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


def read_fragment(root, ref, coloured):
    """Fills ref with the cited lines; returns the problem, or None."""
    path = Path(root) / ref["file"]
    if not path.is_file():
        return f"{ref['file']}: no such file under {root}"

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    span = str(ref.get("lines", "")).strip()

    if not span:
        first, last = 1, len(lines)
    else:
        bounds = span.split("-")
        try:
            first = int(bounds[0])
            last = int(bounds[-1])
        except ValueError:
            return f"{ref['file']}: lines '{span}' is not a range like 12-40"

    if first < 1 or last > len(lines) or first > last:
        return f"{ref['file']}: lines {span} fall outside the file ({len(lines)} lines)"
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


def collect_fragments(data, root, coloured=False):
    """Fills in the code of every citation; returns the problems found."""
    problems = []

    for node in data["nodes"]:
        for ref in node.get("refs") or []:
            if not isinstance(ref, dict) or "file" not in ref:
                problems.append(f"{node.get('id')}: a ref needs a 'file' field")
                continue
            problem = read_fragment(root, ref, coloured)
            if problem:
                problems.append(f"{node.get('id')}: {problem}")

    return problems


def render(data, template=None):
    """Substitutes the MAP literal and the page title into the template."""
    text = Path(template or TEMPLATE).read_text(encoding="utf-8")
    literal = "const MAP = " + json.dumps(data, ensure_ascii=False, indent=2) + ";"
    page, count = re.subn(r"const MAP = \{.*?\n\};", lambda _: literal, text, count=1, flags=re.S)
    if count != 1:
        raise ValueError("no MAP literal to replace — the template changed shape")

    # The tag, not document.title, names the page in a browser tab and in the
    # artifact gallery, so the title travels into the markup as well.
    return re.sub(r"<title>.*?</title>", f"<title>{html.escape(data['title'])}</title>", page, count=1, flags=re.S)


def build(path, root=".", coloured=False, template=None):
    """Loads, checks and renders one map. Raises ValueError listing every problem."""
    data = load(path)
    problems = validate(data)
    if not problems:
        problems = collect_fragments(data, root, coloured)
    if problems:
        raise ValueError("\n".join(problems))

    return data, render(data, template)
