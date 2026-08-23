#!/usr/bin/env python3
"""Render a map YAML into a standalone HTML page.

Usage:
    build-map.py dev/design/access.map.yaml [-o out.html] [--root .]

The YAML is the source and belongs in git; the page is a snapshot, meant for
publishing or for reading without the plugin, and is not committed. Code cited
by a node is copied in as plain text — the plugin server is what colours it.

The build refuses to render a map whose node lacks a required field, whose id
repeats, whose edge names a node that is not there, or which cites a missing
file: all four look on the page like a record that exists.
"""

import argparse
import sys
from pathlib import Path

import mapkit


def main():
    parser = argparse.ArgumentParser(description="Render a map YAML into an HTML page.")
    parser.add_argument("source", type=Path, help="map data, dev/design/<name>.map.yaml")
    parser.add_argument("-o", "--out", type=Path, help="output page; defaults to <name>.map.html")
    parser.add_argument("--root", type=Path, default=Path("."), help="where cited paths start; defaults to .")
    parser.add_argument("--colour", action="store_true", help="colour the cited code, as the server does")
    args = parser.parse_args()

    try:
        data, page = mapkit.build(args.source, args.root, coloured=args.colour)
    except ValueError as error:
        print(f"{args.source}: map does not validate", file=sys.stderr)
        for problem in str(error).splitlines():
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(1)

    out = args.out or args.source.with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    print(f"{out}: {len(data['nodes'])} nodes, {len(data['edges'])} edges")


if __name__ == "__main__":
    main()
