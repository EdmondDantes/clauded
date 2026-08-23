#!/usr/bin/env python3
"""Render a map YAML into a standalone HTML page.

Usage:
    build-map.py dev/design/access.map.yaml [-o out.html] [--root .]

The data file is the source; the page is generated and carries the same data as
a MAP literal, so it opens from the file system with no server. Output defaults
to the input path with the .yaml suffix replaced by .html.

A node may cite source files:

    refs:
      - file: src/Auth/Guard.php
        lines: 12-40

The fragment is copied into the page at build time, so the map shows what it was
built from even after the file moves on; --root says where the paths start from
and defaults to the working directory.

The map is validated before rendering: a missing field, an edge pointing at an
unknown node, or a citation of a file that is not there stops the build, because
all three look on the page like a record that exists.
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

import yaml

TEMPLATE = Path(__file__).resolve().parent.parent / "web" / "map-template.html"

REQUIRED_NODE_FIELDS = ("id", "kind", "title", "body", "origin")
DESIGN_KINDS = {"aspect", "question", "decision", "rejected"}
ARCHITECTURE_KINDS = {"aspect", "module", "knowledge", "dependency"}
RELATIONS = {"holds", "rejects"}
MAX_FRAGMENT_LINES = 400


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


def read_fragment(root, ref):
    """Reads the cited lines into ref['code']; returns the problem, or None."""
    path = root / ref["file"]
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
    return None


def collect_fragments(data, root):
    """Fills in the code of every citation; returns the problems found."""
    problems = []

    for node in data["nodes"]:
        for ref in node.get("refs") or []:
            if not isinstance(ref, dict) or "file" not in ref:
                problems.append(f"{node.get('id')}: a ref needs a 'file' field")
                continue
            problem = read_fragment(root, ref)
            if problem:
                problems.append(f"{node.get('id')}: {problem}")

    return problems


def render(data, template):
    """Substitutes the MAP literal in the template and returns the page."""
    literal = "const MAP = " + json.dumps(data, ensure_ascii=False, indent=2) + ";"
    page, count = re.subn(r"const MAP = \{.*?\n\};", lambda _: literal, template, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{TEMPLATE}: no MAP literal to replace — template changed shape")

    # The tag, not document.title, is what names the page in a browser tab and
    # in the artifact gallery, so the title travels into the markup as well.
    title = html.escape(data["title"])
    return re.sub(r"<title>.*?</title>", f"<title>{title}</title>", page, count=1, flags=re.S)


def main():
    parser = argparse.ArgumentParser(description="Render a map YAML into an HTML page.")
    parser.add_argument("source", type=Path, help="map data, dev/design/<name>.map.yaml")
    parser.add_argument("-o", "--out", type=Path, help="output page; defaults to <name>.map.html")
    parser.add_argument("--root", type=Path, default=Path("."), help="where cited paths start; defaults to .")
    parser.add_argument("--template", type=Path, default=TEMPLATE, help="page template; defaults to web/map-template.html")
    args = parser.parse_args()

    data = yaml.safe_load(args.source.read_text(encoding="utf-8"))
    problems = validate(data)
    if not problems:
        problems = collect_fragments(data, args.root)
    if problems:
        print(f"{args.source}: map does not validate", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(1)

    out = args.out or args.source.with_suffix(".html")
    out.write_text(render(data, args.template.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"{out}: {len(data['nodes'])} nodes, {len(data['edges'])} edges")


if __name__ == "__main__":
    main()
