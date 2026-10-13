#!/usr/bin/env python3
"""Read a Figma design through the REST API (token in FIGMA_API_KEY, never printed).

    figma.py frames <figma-url | file-key> [--node <id>] [--match <text>] [--depth <n>]
    figma.py render <figma-url | file-key> --ids <id,id,...> [--scale <n>] [--out <dir>]
    figma.py styles <figma-url | file-key> --node <id> [--max-depth <n>]

A URL's node-id (11538-113252) is used as --node when none is given. Node ids are printed and accepted as 11538:113252.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://api.figma.com/v1"


def parse_target(target):
    """(file_key, node_id or None) from a figma.com URL or a bare file key."""
    m = re.search(r"figma\.com/(?:design|file|proto)/([A-Za-z0-9]+)", target)
    if not m:
        return target, None
    query = urllib.parse.parse_qs(urllib.parse.urlparse(target).query)
    node = query.get("node-id", [None])[0]
    return m.group(1), node.replace("-", ":") if node else None


def hex_color(color, opacity=1.0):
    """#rrggbb, with @alpha (two decimals) when not opaque."""
    rgb = "".join(f"{round(color[c] * 255):02x}" for c in "rgb")
    alpha = color.get("a", 1) * opacity
    return f"#{rgb}" + (f"@{alpha:.2f}" if alpha < 0.995 else "")


def get(path, params=None):
    token = os.environ.get("FIGMA_API_KEY")
    if not token:
        sys.exit("FIGMA_API_KEY is not set")
    url = f"{API}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"X-Figma-Token": token})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def node_doc(key, node, depth=None):
    params = {"ids": node}
    if depth:
        params["depth"] = depth
    return get(f"files/{key}/nodes", params)["nodes"][node]["document"]


def size(n):
    b = n.get("absoluteBoundingBox") or {}
    return f"{round(b.get('width', 0))}x{round(b.get('height', 0))}" if b else ""


def fills(n):
    out = []
    for f in n.get("fills", []):
        if f.get("visible") is False:
            continue
        if f["type"] == "SOLID":
            out.append(hex_color(f["color"], f.get("opacity", 1)))
        else:
            out.append(f["type"].lower() + ":" + ">".join(hex_color(s["color"]) for s in f.get("gradientStops", [])))
    return ",".join(out)


def describe(n):
    """One line: type, name, size and the style values a front end maps to its tokens."""
    parts = [n["type"], json.dumps(n.get("name", ""), ensure_ascii=False), size(n)]
    if n["type"] == "TEXT":
        s = n.get("style", {})
        parts += [json.dumps(n.get("characters", "")[:80], ensure_ascii=False),
                  f"font={s.get('fontSize')}/{s.get('fontWeight')}/lh{round(s.get('lineHeightPx', 0))}", f"color={fills(n)}"]
        return " ".join(p for p in parts if p)
    if fills(n):
        parts.append(f"fill={fills(n)}")
    strokes = [hex_color(s["color"], s.get("opacity", 1)) for s in n.get("strokes", []) if s.get("visible") is not False]
    if strokes:
        weights = n.get("individualStrokeWeights")
        parts.append(f"stroke={','.join(strokes)}/{json.dumps(weights) if weights else n.get('strokeWeight')}")
    if n.get("cornerRadius"):
        parts.append(f"r={n['cornerRadius']}")
    for e in n.get("effects", []):
        if e.get("visible") is not False and "SHADOW" in e["type"]:
            o = e.get("offset", {})
            parts.append(f"{e['type'].lower()}={o.get('x', 0)},{o.get('y', 0)},{e.get('radius', 0)},{e.get('spread', 0)},{hex_color(e['color'])}")
    if n.get("itemSpacing"):
        parts.append(f"gap={n['itemSpacing']}")
    pad = [n.get(k, 0) for k in ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft")]
    if any(pad):
        parts.append("pad=" + "/".join(str(p) for p in pad))
    return " ".join(p for p in parts if p)


def cmd_frames(args):
    key, url_node = parse_target(args.target)
    node = args.node or url_node
    if not node:
        doc = get(f"files/{key}", {"depth": 2})["document"]
        roots = doc["children"]
    else:
        roots = node_doc(key, node.replace("-", ":"), args.depth)["children"]
    for n in roots:
        if args.match and args.match.lower() not in n.get("name", "").lower():
            continue
        b = n.get("absoluteBoundingBox") or {}
        at = f"@{round(b['x'])},{round(b['y'])}" if b else ""
        print(f"{n['id']}\t{n['type']}\t{n.get('name', '')}\t{size(n)}\t{at}")


def cmd_render(args):
    key, _ = parse_target(args.target)
    ids = [i.strip().replace("-", ":") for i in args.ids.split(",") if i.strip()]
    images = get(f"images/{key}", {"ids": ",".join(ids), "format": "png", "scale": args.scale})["images"]
    os.makedirs(args.out, exist_ok=True)
    for i in ids:
        if not images.get(i):
            print(f"{i}\tnot rendered", file=sys.stderr)
            continue
        path = os.path.join(args.out, i.replace(":", "_") + ".png")
        with urllib.request.urlopen(images[i], timeout=120) as r, open(path, "wb") as f:
            f.write(r.read())
        print(f"{i}\t{os.path.abspath(path)}")


def cmd_styles(args):
    key, url_node = parse_target(args.target)
    node = (args.node or url_node or "").replace("-", ":")
    if not node:
        sys.exit("styles needs --node (or a URL with node-id)")

    def walk(n, depth):
        if n.get("visible") is False:
            return
        print("  " * depth + describe(n))
        if depth < args.max_depth:
            for c in n.get("children", []):
                walk(c, depth + 1)

    walk(node_doc(key, node), 0)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")  # piped output on Windows would use the ANSI code page
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("frames", help="list the children of a node (or of the file's pages)")
    f.add_argument("target")
    f.add_argument("--node")
    f.add_argument("--match", help="only names containing this text")
    f.add_argument("--depth", type=int, default=1, help="levels fetched below the node (keeps a whole canvas small)")
    r = sub.add_parser("render", help="render nodes to PNG")
    r.add_argument("target")
    r.add_argument("--ids", required=True)
    r.add_argument("--scale", type=float, default=1)
    r.add_argument("--out", default="figma")
    s = sub.add_parser("styles", help="print a node's tree with text, colour, shadow and spacing values")
    s.add_argument("target")
    s.add_argument("--node")
    s.add_argument("--max-depth", type=int, default=12)
    args = p.parse_args(argv)
    {"frames": cmd_frames, "render": cmd_render, "styles": cmd_styles}[args.cmd](args)


if __name__ == "__main__":
    main()
