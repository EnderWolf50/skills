"""Text on the frame: step captions (pill, chapter, callout), key pills, labelled boxes, and blocks: the panels a
project lays out itself (blocks.json, BLOCKS.md), the corner among them, with the steps and key events they come from."""
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from common import KEYS, Canvas, fade, hms, rgba

ACCENT = (255, 196, 64)  # amber: steps, boxes
FADE_S = 0.35  # step caption, box and block fade
CAP_EDGE = 20  # px at 1280 wide from the frame's edge to a pill or chapter caption, at CAPTION_DESIGN
CAPTION_DESIGN = 28  # px: the title size the step capsule and the key pill were laid out around; style.caption_size
# scales both from it (the key pill's text is 22/28 of the title's)
CAPTIONS = ("pill", "callout", "chapter", "none")  # the capsule bottom centre, beside the step's press, top left; none
KEY_HOLD_S = 1.0  # a key pill stays this long after its last key
TYPE_MS = 45  # a `type` event reveals one character this often unless it gives "ms"
TYPE_JOIN_S = 1.2  # typing that starts this soon after the last character joins the same pill
ANCHORS = ("top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right")
BLOCK = {"from": None, "to": None, "at": "bottom-left", "beside": False, "size": 13, "weight": 500, "lines": [],
         "sep": "", "gap": 0, "bullets": False, "color": "#e6e6e6", "bg": "#0000008c", "radius": None,
         "pad": None, "margin": 6, "min_w": None, "max_w": None, "max_lines": 1, "rect": None, "read": True,
         "area": "frame"}  # a block's keys and defaults; area: anchored to the whole output frame or the recording in it
CORNER = {"at": "bottom-left", "lines": [["{clock}", "{step}", "{speed}"]], "sep": "  ·  ", "color": "#e6e6e6e6",
          "read": False}  # style.corner: the default block in the corner
PART_KEYS = {"text", "color", "bold", "size", "dot", "rule", "hang"}  # hang: a wrapped line's later rows start after it
TOKENS = re.compile(r"\{(clock|step|speed)\}")
LINE_H = 1.45  # line pitch, times the block's size
ROW_GAP = 4  # px at 1280 wide between blocks stacked at one anchor
SIDE_GAP = 6  # px at 1280 wide between blocks side by side (beside)
BULLET = (174, 180, 188, 255)
CLOSING = set("，。、；：！？）」』》〉】,.;:!?)]}…%")  # never the first character of a wrapped row


def key_items(events, offset=0.0):
    """Key pills from `key` ({"keys": "Ctrl+S"}) and `type` ({"text": "...", "ms"?: total}) events, sorted:
    {"t0", "t1", "caps": [..]} or {"t0", "t1", "chars": [(t, ch), ...]}. Typing close behind typing joins it."""
    out = []
    for e in sorted((e for e in events if e["kind"] in KEYS), key=lambda e: hms(e["t"])):
        t = hms(e["t"]) + offset
        if e["kind"] == "key":
            if not e.get("keys"):
                raise ValueError(f"key event at {e['t']} lacks keys: {e}")
            out.append({"t0": t, "t1": t + KEY_HOLD_S, "caps": [k.strip() for k in str(e["keys"]).split("+") if k.strip()]})
            continue
        text = str(e.get("text", ""))
        if not text:
            raise ValueError(f"type event at {e['t']} lacks text: {e}")
        step = e.get("ms", TYPE_MS * len(text)) / 1000 / len(text)
        chars = [(t + i * step, ch) for i, ch in enumerate(text)]
        prev = next((it for it in reversed(out) if "chars" in it), None)
        if prev and out[-1] is prev and t <= prev["chars"][-1][0] + TYPE_JOIN_S:
            prev["chars"] += chars
            prev["t1"] = chars[-1][0] + KEY_HOLD_S
        else:
            out.append({"t0": t, "t1": chars[-1][0] + KEY_HOLD_S, "chars": chars})
    return out


def key_at(items, t):
    """(item, alpha) of the latest key pill showing at t, fading in over 0.15 s and out over 0.3 s, or None."""
    for it in reversed(items):
        if it["t0"] <= t < it["t1"]:
            return it, max(0.0, min(1, (t - it["t0"]) / 0.15, (it["t1"] - t) / 0.3))
    return None


def load_steps(path):
    steps = json.loads(Path(path).read_text(encoding="utf-8"))
    for s in steps:
        s["from"], s["to"] = hms(s["from"]), hms(s["to"])
        z = s.get("zoom")
        if z and (len(z) != 4 or z[2] <= 0 or z[3] <= 0):
            sys.exit(f"step {s.get('title')!r}: zoom must be [x,y,w,h] with w and h above 0, got {z}")
        if "tag" in s and not isinstance(s["tag"], str):
            sys.exit(f"step {s.get('title')!r}: tag must be text, got {s['tag']!r}")
    return steps


def step_at(steps, t):
    """(index, step, alpha) of the step covering t (alpha fades in and out over FADE_S), or None."""
    for i, s in enumerate(steps):
        if s["from"] <= t < s["to"]:
            return i, s, max(0.0, min(1, (t - s["from"]) / FADE_S, (s["to"] - t) / FADE_S))
    return None


def step_label(steps, cur):
    """What a caption and {step} call the current step: its tag, else 步驟 n/N; empty outside the steps."""
    if not cur:
        return ""
    i, step, _ = cur
    return step.get("tag", f"步驟 {i + 1}/{len(steps)}")


def cap_in(u):
    """A step caption u of the way through its fade (0 hidden, 1 shown): (alpha, px it sits low)."""
    return 1 - (1 - u) ** 3, (1 - u) ** 3 * 10  # ease-out cubic in, so ease-in on the way out


def read_s(text):
    """Seconds a caption takes to read: 1.5 plus one per 6 characters, from 2.5 to 9."""
    return min(9.0, max(2.5, 1.5 + len(text) / 6))


# ---------------------------------------------------------------- blocks

def load_blocks(path):
    """blocks.json -> (canvas, blocks, space): canvas {top, bottom, left, right (px at 1280 wide), color (RGB)},
    the blocks checked (check_block), and the file's own space for `rect`, or None."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        sys.exit(f"blocks: the file must be an object with canvas and blocks, got {type(doc).__name__}")
    if unknown := set(doc) - {"canvas", "blocks", "space"}:
        sys.exit(f"blocks: unknown keys {sorted(unknown)}; known: canvas, blocks, space")
    return check_canvas(doc.get("canvas") or {}), [check_block(b, f"blocks[{i}]") for i, b in enumerate(doc.get("blocks", []))], doc.get("space")


def check_canvas(c):
    if not isinstance(c, dict) or set(c) - {"top", "bottom", "left", "right", "color"}:
        sys.exit(f"blocks: canvas takes top, bottom, left, right and color, got {c!r}")
    out = {k: c.get(k, 0) for k in ("top", "bottom", "left", "right")}
    if any(not isinstance(v, (int, float)) or not 0 <= v <= 2000 for v in out.values()):
        sys.exit(f"blocks: canvas sides must be px from 0 to 2000, got {out}")
    color = rgba(c.get("color", "#111318"))
    if color is None:
        sys.exit(f"blocks: canvas color must be #rrggbb, got {c.get('color')!r}")
    return {**out, "color": color[:3]}


def check_block(b, where):
    """A block's keys over BLOCK, checked: times in seconds, colours as RGBA, each line a list of part dicts."""
    if not isinstance(b, dict):
        sys.exit(f"{where}: a block must be an object, got {b!r}")
    if unknown := set(b) - set(BLOCK) - {"_rise"}:
        sys.exit(f"{where}: unknown keys {sorted(unknown)}; known: {', '.join(BLOCK)}")
    blk = {**BLOCK, **b}
    if blk["at"] not in ANCHORS:
        sys.exit(f"{where}: at must be one of {', '.join(ANCHORS)}, got {blk['at']!r}")
    for k in ("from", "to"):
        try:
            blk[k] = None if blk[k] is None else blk[k] if isinstance(blk[k], float) else hms(str(blk[k]))
        except ValueError:
            sys.exit(f"{where}: {k} must be HH:MM:SS.fff, got {blk[k]!r}")
    for k in ("color", "bg"):
        if blk[k] is not None and not isinstance(blk[k], tuple):
            blk[k] = rgba(blk[k])
            if blk[k] is None:
                sys.exit(f"{where}: {k} must be #rrggbb or #rrggbbaa, got {b[k]!r}")
    for k, lo, hi in (("size", 6, 96), ("weight", 100, 900), ("gap", 0, 200), ("margin", 0, 2000)):
        if not isinstance(blk[k], (int, float)) or not lo <= blk[k] <= hi:
            sys.exit(f"{where}: {k} must be a number from {lo} to {hi}, got {blk[k]!r}")
    for k in ("min_w", "max_w", "radius"):
        if blk[k] is not None and (not isinstance(blk[k], (int, float)) or blk[k] < 0):
            sys.exit(f"{where}: {k} must be a number of px, got {blk[k]!r}")
    if not isinstance(blk["max_lines"], int) or isinstance(blk["max_lines"], bool) or not 1 <= blk["max_lines"] <= 20:
        sys.exit(f"{where}: max_lines must be a whole number from 1 to 20, got {blk['max_lines']!r}")
    for k, n in (("pad", 2), ("rect", 4)):
        v = blk[k]
        if v is not None and (not isinstance(v, list) or len(v) != n or not all(isinstance(x, (int, float)) for x in v)):
            sys.exit(f"{where}: {k} must be {n} numbers, got {v!r}")
    if blk["rect"] and (blk["rect"][2] <= 0 or blk["rect"][3] <= 0):
        sys.exit(f"{where}: rect must be [x,y,w,h] with w and h above 0, got {blk['rect']}")
    if blk["area"] not in ("frame", "video"):
        sys.exit(f"{where}: area must be frame or video, got {blk['area']!r}")
    for k in ("beside", "bullets", "read"):
        if not isinstance(blk[k], bool):
            sys.exit(f"{where}: {k} must be true or false, got {blk[k]!r}")
    if not isinstance(blk["sep"], str) or not isinstance(blk["lines"], list):
        sys.exit(f"{where}: sep must be text and lines a list, got {blk['sep']!r}, {blk['lines']!r}")
    blk["lines"] = [[part(p, where) for p in ([line] if isinstance(line, (str, dict)) else line)] for line in blk["lines"]]
    return blk


def part(p, where):
    """A line's part as a dict: {"text"} or {"dot": RGBA} or {"rule": True}, with color (RGBA), bold, size."""
    if isinstance(p, str):
        return {"text": p}
    if not isinstance(p, dict) or set(p) - PART_KEYS:
        sys.exit(f"{where}: a part is text or an object with {', '.join(sorted(PART_KEYS))}, got {p!r}")
    p = dict(p)
    for k in ("color", "dot"):
        if k in p and not isinstance(p[k], tuple):
            p[k] = rgba(p[k])
            if p[k] is None:
                sys.exit(f"{where}: a part's {k} must be #rrggbb or #rrggbbaa")
    if "text" in p:
        p["text"] = str(p["text"])
    return p


def expand(parts, tokens):
    """The parts with {clock}, {step} and {speed} filled in; a text part left empty by its tokens is dropped."""
    out = []
    for p in parts:
        if "text" in p:
            text = TOKENS.sub(lambda m: tokens.get(m.group(1), ""), p["text"])
            if not text and TOKENS.search(p["text"]):
                continue
            p = {**p, "text": text}
        out.append(p)
    return out


def anchor(at):
    """An anchor's (row, side): top-left -> ("top", "left"), center -> ("middle", "center")."""
    if "-" in at:
        return tuple(at.split("-"))
    return {"top": ("top", "center"), "bottom": ("bottom", "center"), "left": ("middle", "left"),
            "right": ("middle", "right"), "center": ("middle", "center")}[at]


def fit(text, room, measure):
    """How many leading characters of text fit in room px."""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if measure(text[:mid]) <= room else (lo, mid - 1)
    return lo


def wrap(items, room, max_lines, gap, measure, indent=0.0):
    """A line's items ([part, font, width]) in rows no wider than room px: [(x, row)]. A text part that does not fit
    breaks between characters, at a space when the break would split a word, never before closing punctuation; rows
    after the first start at indent; past max_lines the rest is cut and the last row ends in an ellipsis.
    measure(font, text) -> px."""
    rows, row, x0, x, cut = [], [], 0.0, 0.0, False
    queue = [list(it) for it in items]
    while queue:
        p, f, w = queue.pop(0)
        lead = gap if row else 0
        if x + lead + w <= room or "text" not in p:
            row.append([p, f, w])
            x += lead + w
            continue
        if len(rows) + 1 >= max_lines:  # the last row this line may take: the rest is cut
            row.append([p, f, w])
            cut = bool(queue)
            break
        text = p["text"]
        n = fit(text, room - x - lead, lambda t: measure(f, t))
        if 0 < n < len(text):
            if text[n - 1].isascii() and text[n - 1].isalnum() and text[n].isascii() and text[n].isalnum() and " " in text[:n]:
                n = text[:n].rindex(" ") + 1  # keep the word whole
            while 1 < n < len(text) and text[n] in CLOSING:
                n -= 1
        if n == 0 and row:  # nothing more fits on this row: the part starts the next
            rows.append((x0, row))
            row, x0, x = [], indent, indent
            queue.insert(0, [p, f, w])
            continue
        n = max(n, 1)
        head, tail = text[:n].rstrip(), text[n:].lstrip()
        row.append([{**p, "text": head}, f, measure(f, head)])
        rows.append((x0, row))
        row, x0, x = [], indent, indent
        if tail:
            queue.insert(0, [{**p, "text": tail}, f, measure(f, tail)])
    if row or not rows:
        rows.append((x0, row))
    x0, row = rows[-1]
    width = lambda r: sum(w for _, _, w in r) + gap * (len(r) - 1)
    texts = [i for i, it in enumerate(row) if "text" in it[0]]
    if texts and (cut or x0 + width(row) > room):  # the last row ends in an ellipsis, shortened until it fits
        i = texts[-1]
        p, f, _ = row[i]
        text = p["text"].rstrip("…") + "…" if cut else p["text"]
        row[i:] = [[{**p, "text": text}, f, measure(f, text)]]
        while x0 + width(row) > room and row[i][0]["text"].rstrip("…"):
            text = row[i][0]["text"].rstrip("…")[:-1].rstrip() + "…"
            row[i] = [{**p, "text": text}, f, measure(f, text)]
    return rows


def block_text(blk):
    """A block's words without its tokens, for its reading time."""
    return "".join(TOKENS.sub("", p.get("text", "")) for line in blk["lines"] for p in line)


def block_alpha(blk, t):
    """The block's opacity at t: 1 for a block without times, fading in and out over FADE_S, or None while hidden."""
    a, b = blk["from"], blk["to"]
    if (a is not None and t < a) or (b is not None and t >= b):
        return None
    return max(0.0, min(1, (t - a) / FADE_S if a is not None else 1, (b - t) / FADE_S if b is not None else 1))


class TextLayer(Canvas):
    """Draws the text (annotate.Painter mixes this layer and the pointer layer onto one Canvas). Blocks, captions and
    key pills go on the output frame: ow x oh, the recording at (ox, oy) inside it when blocks.json adds a canvas."""

    def init_text(self, font):
        """Fonts; style.caption_size sizes the step capsule and the key pill."""
        s = self.s
        self.font, self.fonts = font, {}
        self.ow, self.oh, self.ox, self.oy = self.w, self.h, 0, 0
        self.f_label = font(round(15 * s), 600)
        self.ck = self.style["caption_size"] / CAPTION_DESIGN  # the step capsule and key pill scale with the title
        c = s * self.ck
        self.f_key = font(round(22 * c), 600)

    def tfont(self, size, weight):
        """The font at size px at 1280 wide and weight, cached."""
        key = (round(size * self.s), weight)
        if key not in self.fonts:
            self.fonts[key] = self.font(*key)
        return self.fonts[key]

    # --- boxes
    def box(self, d, x, y, w, h, label, alpha):
        s = self.s
        X0, Y0 = self.xy(x, y)
        X1, Y1 = self.xy(x + w, y + h)
        d.rounded_rectangle([X0, Y0, X1, Y1], radius=6 * s, outline=(*ACCENT, int(240 * alpha)), width=max(2, round(3 * s)))
        if label:
            tw = d.textlength(label, font=self.f_label)
            ly = Y0 - 26 * s if Y0 > 40 * s else Y1 + 4 * s
            d.rounded_rectangle([X0, ly, X0 + tw + 14 * s, ly + 22 * s], radius=5 * s, fill=(*ACCENT, int(235 * alpha)))
            d.text((X0 + 7 * s, ly + 11 * s), label, font=self.f_label, fill=(20, 20, 24, int(255 * alpha)), anchor="lm")

    # --- blocks
    def block_image(self, blk, tokens, bg=True, width=None):
        """The block drawn at its size, its tokens filled in (cached per text), or None when it has nothing to show:
        lines of parts left to right, `gap` apart, each row centred on its pitch; a dot, a hairline (rule) or text.
        A line wider than the block may be (max_w, or `width` px when it makes way for another) wraps to max_lines
        rows (wrap), the last ending in an ellipsis when it still does not fit."""
        lines = [expand(line, tokens) for line in blk["lines"]]
        if blk["sep"]:
            lines = [[q for i, p in enumerate(line) for q in ([{"text": blk["sep"]}] if i else []) + [p]] for line in lines]
        lines = [line for line in lines if line] if any(lines) else []
        if not lines:
            return None
        look = repr(sorted((k, v) for k, v in blk.items() if k not in ("lines", "from", "to")))
        key = ("block", look, repr(lines), bg, width)  # by content: an id() is reused once a passing dict is freed
        if key in self.cache:
            return self.cache[key]
        s, size = self.s, blk["size"]
        padx, pady = [v * s for v in (blk["pad"] or (0.62 * size, 0.27 * size))]
        gap = blk["gap"] * s
        outer = blk["max_w"] * s if blk["max_w"] else self.area(blk)[2] - 2 * blk["margin"] * s
        room = min(outer, width or outer) - 2 * padx
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        measure = lambda f, text: probe.textlength(text, font=f)
        laid = []  # visual rows: (x, [[part, font, width], ...])
        for line in lines:
            items = [[{"text": "•  ", "color": BULLET, "hang": True}, self.tfont(size, blk["weight"]), 0]] if blk["bullets"] else []
            for p in line:
                if "dot" in p:
                    items.append([p, None, 0.57 * size * s])
                elif p.get("rule"):
                    items.append([p, None, max(1, round(2 / 28 * size * s))])
                else:
                    items.append([p, self.tfont(p.get("size", size), 700 if p.get("bold") else blk["weight"]), 0])
            for it in items:
                if "text" in it[0]:
                    it[2] = measure(it[1], it[0]["text"])
            hang = next((i for i, it in enumerate(items) if it[0].get("hang")), None)  # later rows start after it
            indent = sum(w for _, _, w in items[:hang + 1]) + gap * (hang + 1) if hang is not None else 0
            laid += wrap(items, room, blk["max_lines"], gap, measure, indent)
        pitch = LINE_H * size * s
        w = round(max(2 * padx + max(x0 + sum(w for _, _, w in r) + gap * (len(r) - 1) for x0, r in laid),
                      min((blk["min_w"] or 0) * s, 2 * padx + room)))  # min_w, but never past the room it has
        h = round(2 * pady + size * s + pitch * (len(laid) - 1))
        im = Image.new("RGBA", (max(w, 1), max(h, 1)))
        r = blk["radius"] * s if blk["radius"] is not None else h / 2 if len(laid) == 1 else 6 * s
        if bg and blk["bg"]:
            ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, h - 1], radius=round(min(r, h / 2)), fill=blk["bg"])
        ink = Image.new("RGBA", im.size)  # drawn apart and composited: a translucent fill drawn straight onto the
        d = ImageDraw.Draw(ink)            # background would replace its pixels instead of blending
        for i, (x0, row) in enumerate(laid):
            x, cy = padx + x0, pady + size * s / 2 + pitch * i
            for p, f, pw in row:
                if "dot" in p:
                    d.ellipse([x, cy - pw / 2, x + pw, cy + pw / 2], fill=p["dot"])
                elif p.get("rule"):
                    d.line([(x, cy - size * s / 2), (x, cy + size * s / 2)], fill=p.get("color", (255, 255, 255, 64)), width=round(pw))
                else:
                    d.text((x, cy), p["text"], font=f, fill=p.get("color", blk["color"]), anchor="lm")
                x += pw + gap
        im.alpha_composite(ink)
        self.cache[key] = im
        return im

    def area(self, blk):
        """(x, y, w, h) a block is anchored in: the whole output frame, or the recording inside its bands."""
        return (self.ox, self.oy, self.w, self.h) if blk["area"] == "video" else (0, 0, self.ow, self.oh)

    def place(self, items):
        """{id(block): (x, y)} on the output frame: per area and anchor, rows (a block `beside` the one before joins
        its row) stacked away from the anchor's edge, ROW_GAP apart, the anchor's first block's margin off the edges."""
        s, out, by = self.s, {}, {}
        for blk, im in items:
            by.setdefault((blk["area"], blk["at"]), []).append((blk, im))
        for (_, at), group in by.items():
            v, hz = anchor(at)
            X0, Y0, AW, AH = self.area(group[0][0])
            rows = []
            for blk, im in group:
                if blk["beside"] and rows:
                    rows[-1].append((blk, im))
                else:
                    rows.append([(blk, im)])
            m = group[0][0]["margin"] * s
            heights = [max(im.height for _, im in r) for r in rows]
            total = sum(heights) + ROW_GAP * s * (len(rows) - 1)
            y = Y0 + (m if v == "top" else AH - m if v == "bottom" else (AH - total) / 2)
            for r, rh in zip(rows, heights):
                if v == "bottom":
                    y -= rh
                rw = sum(im.width for _, im in r) + SIDE_GAP * s * (len(r) - 1)
                x = X0 + (m if hz == "left" else AW - m - rw if hz == "right" else (AW - rw) / 2)
                for blk, im in r:
                    dy = 0 if v == "top" else rh - im.height if v == "bottom" else (rh - im.height) / 2
                    out[id(blk)] = (x, y + dy)
                    x += im.width + SIDE_GAP * s
                y = y - ROW_GAP * s if v == "bottom" else y + rh + ROW_GAP * s
        return out

    def blocks(self, ov, blocks, t, tokens):
        """Draw the blocks showing at t (all but covers) on the output overlay, each making way for the blocks it
        would overlap (make_way); returns {id(block): (x, y, w, h)}."""
        live = [(blk, a) for blk in blocks if not blk["rect"] and (a := block_alpha(blk, t)) is not None]
        widths = {}
        for _ in range(4):  # a narrower block may wrap taller and meet another: lay out again, a few times at most
            shown = [(blk, im) for blk, _ in live if (im := self.block_image(blk, tokens, width=widths.get(id(blk)))) is not None]
            at = self.place(shown)
            boxes = {id(blk): (*at[id(blk)], im.width, im.height) for blk, im in shown}
            if not self.make_way(shown, boxes, widths):
                break
        alpha = dict((id(blk), a) for blk, a in live)
        for blk, im in shown:
            a, rise = alpha[id(blk)], 0
            if blk.get("_rise"):  # a step caption: eases in and settles up, as it always has
                a, rise = cap_in(a)
                rise *= self.s * self.ck
            x, y, _, _ = boxes[id(blk)]
            self.paste(ov, fade(im, a) if a < 1 else im, x, y + rise)
        return boxes

    def make_way(self, shown, boxes, widths):
        """Narrow each block that overlaps one further right in the same row of anchors (top, middle, bottom): a
        left block makes way for a centre or right one, a centre block for a right one, SIDE_GAP apart. Records the
        new widths in `widths`; True when one changed."""
        rank, changed, g = {"left": 0, "center": 1, "right": 2}, False, SIDE_GAP * self.s
        for b1, _ in shown:
            v1, h1 = anchor(b1["at"])
            x1, y1, w1, hh1 = boxes[id(b1)]
            for b2, _ in shown:
                v2, h2 = anchor(b2["at"])
                x2, y2, w2, hh2 = boxes[id(b2)]
                if v1 != v2 or rank[h1] >= rank[h2] or not (x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + hh2 and y2 < y1 + hh1):
                    continue
                ax, _, aw, _ = self.area(b1)
                room = x2 - g - x1 if h1 == "left" else 2 * (x2 - g - ax - aw / 2)
                room = max(room, 3 * b1["size"] * self.s)
                if room < w1 - 0.5 and room < widths.get(id(b1), float("inf")):
                    widths[id(b1)], changed = room, True
        return changed

    def cover(self, ov, blk, t, tokens, space):
        """A block with a rect: a box over the recording there (through the zoom), its lines inside at the top left."""
        if (a := block_alpha(blk, t)) is None:
            return
        x, y, w, h = blk["rect"]
        sx, sy = self.w / space[0], self.h / space[1]
        X0, Y0 = self.vp(x * sx, y * sy)
        X1, Y1 = self.vp((x + w) * sx, (y + h) * sy)
        if blk["bg"]:  # covers go first onto a clear overlay, so drawing straight onto it is the same as compositing
            r = (blk["radius"] or 0) * self.s
            ImageDraw.Draw(ov).rounded_rectangle([X0, Y0, X1 - 1, Y1 - 1], radius=r, fill=(*blk["bg"][:3], round(blk["bg"][3] * a)))
        if im := self.block_image(blk, tokens, bg=False):
            self.paste(ov, fade(im, a) if a < 1 else im, X0, Y0)

    # --- the step caption: a block, the same capsule wherever style.caption puts it
    def caption_block(self, step, n, total):
        """The pill / chapter caption as a block (cached per step): a translucent dark capsule, an amber dot
        (style.dot), the step's tag or "n/total", a hairline, the title."""
        key = ("capblk", n, total, step["title"], step.get("tag"), step["from"], step["to"])  # by content: a step
        if key not in self.cache:                                                          # dict may be a passing one
            size = self.style["caption_size"]
            k = size / CAPTION_DESIGN
            parts = ([{"dot": (255, 196, 64, 255)}] if self.style["dot"] else []) + [
                {"text": step.get("tag", f"{n}/{total}"), "size": 22 * k, "color": (255, 255, 255, 140)},
                {"rule": True}, {"text": step["title"], "color": (255, 255, 255, 255)}]
            self.cache[key] = {**BLOCK, "from": step["from"], "to": step["to"], "_rise": True, "read": False,
                               "at": "top-left" if self.style["caption"] == "chapter" else "bottom", "area": "video",
                               "size": size, "weight": 600, "lines": [parts], "gap": 16 * k, "pad": [32 * k, 18 * k],
                               "bg": (15, 17, 24, 170), "margin": CAP_EDGE * k}
        return self.cache[key]

    def capsule(self, n, total, title, tag=None):
        """The caption's capsule image alone."""
        step = {"from": None, "to": None, "title": title, **({"tag": tag} if tag else {})}
        key = ("capsule", n, total, title, tag)
        if key not in self.cache:
            self.cache[key] = self.block_image(self.caption_block(step, n, total), {})
        return self.cache[key]

    def callout(self, ov, step, n, total, alpha, anchor):
        """The capsule beside the step's first press (else its first box), on the side away from the pointer and its
        name tag, else the side that fits best, kept inside the output frame."""
        s = self.s * self.ck
        cap = self.block_image(self.caption_block(step, n, total), {})
        alpha, rise = cap_in(alpha)
        rise *= s
        if alpha < 1:
            cap = fade(cap, alpha)
        X, Y = self.xy(*anchor)
        X, Y = X + self.ox, Y + self.oy
        w, h = cap.size
        gap, edge = 72 * s, 16 * s  # clear of the click ring
        # the pointer and its name tag hang below and right of the tip: try left, above, right, below
        sides = [(X - gap - w, Y - h / 2), (X - w / 2, Y - gap - h), (X + gap + 150 * s, Y - h / 2), (X - w / 2, Y + gap + 60 * s)]
        fits = lambda xy: edge <= xy[0] <= self.ow - edge - w and edge <= xy[1] <= self.oh - edge - h
        over = lambda xy: max(0, edge - xy[0], xy[0] - (self.ow - edge - w)) + max(0, edge - xy[1], xy[1] - (self.oh - edge - h))
        x, y = next((xy for xy in sides if fits(xy)), min(sides, key=over))
        self.paste(ov, cap, min(max(x, edge), self.ow - edge - w), min(max(y, edge), self.oh - edge - h) + rise)

    def keys(self, ov, item, t, alpha, bottom):
        """The key pill, centred on the recording with its bottom edge at y = bottom: keycaps joined by +, or the
        text typed so far (a block in the same dark pill)."""
        s = self.s * self.ck
        pad, h, cap_h, gap = 12 * s, 54 * s, 38 * s, 22 * s
        if "chars" in item:
            k = self.ck
            text = "".join(ch for ct, ch in item["chars"] if ct <= t)[-32:]  # the tail of a long text
            blk = self.cache.setdefault(("typed", text), {**BLOCK, "size": 22 * k, "weight": 600, "pad": [24 * k, 16 * k],
                                                          "bg": (18, 20, 28, 220), "radius": 16 * k, "color": (255, 255, 255, 255),
                                                          "lines": [[{"text": text}]] if text else []})
            if im := self.block_image(blk, {}):
                self.paste(ov, fade(im, alpha) if alpha < 1 else im, self.ox + (self.w - im.width) / 2, bottom - im.height)
            return
        d = ImageDraw.Draw(ov)
        widths = [d.textlength(c, font=self.f_key) + 28 * s for c in item["caps"]]
        w = sum(widths) + gap * (len(widths) - 1) + 2 * pad
        x, y = self.ox + (self.w - w) / 2, bottom - h
        d.rounded_rectangle([x, y, x + w, y + h], radius=16 * s, fill=(18, 20, 28, int(220 * alpha)))
        x += pad
        for i, (c, cw) in enumerate(zip(item["caps"], widths)):
            cy = y + (h - cap_h) / 2
            d.rounded_rectangle([x, cy + 3 * s, x + cw, cy + cap_h + 3 * s], radius=8 * s, fill=(170, 176, 190, int(255 * alpha)))
            d.rounded_rectangle([x, cy, x + cw, cy + cap_h], radius=8 * s, fill=(255, 255, 255, int(255 * alpha)))
            d.text((x + cw / 2, cy + cap_h / 2), c, font=self.f_key, fill=(20, 22, 28, int(255 * alpha)), anchor="mm")
            x += cw
            if i < len(widths) - 1:
                d.text((x + gap / 2, y + h / 2), "+", font=self.f_key, fill=(170, 176, 190, int(255 * alpha)), anchor="mm")
                x += gap
