"""Text on the frame: step captions (pill, chapter, callout), key pills, labelled boxes and the corner, with the
steps and key events they come from."""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from common import KEYS, Canvas, fade, hms

ACCENT = (255, 196, 64)  # amber: steps, boxes
FADE_S = 0.35  # step caption and box fade
CAP_EDGE = 20  # px at 1280 wide from the frame's edge to a pill or chapter caption
CAPTION_DESIGN = 28  # px: the title size the step capsule and the key pill were laid out around; style.caption_size
# scales both from it (the key pill's text is 22/28 of the title's)
CAPTIONS = ("pill", "callout", "chapter")  # the capsule bottom centre, beside the step's press, top left
KEY_HOLD_S = 1.0  # a key pill stays this long after its last key
TYPE_MS = 45  # a `type` event reveals one character this often unless it gives "ms"
TYPE_JOIN_S = 1.2  # typing that starts this soon after the last character joins the same pill


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
    return steps


def step_at(steps, t):
    """(index, step, alpha) of the step covering t (alpha fades in and out over FADE_S), or None."""
    for i, s in enumerate(steps):
        if s["from"] <= t < s["to"]:
            return i, s, max(0.0, min(1, (t - s["from"]) / FADE_S, (s["to"] - t) / FADE_S))
    return None


def cap_in(u):
    """A step caption u of the way through its fade (0 hidden, 1 shown): (alpha, px it sits low)."""
    return 1 - (1 - u) ** 3, (1 - u) ** 3 * 10  # ease-out cubic in, so ease-in on the way out


def read_s(text):
    """Seconds a caption takes to read: 1.5 plus one per 6 characters, from 2.5 to 9."""
    return min(9.0, max(2.5, 1.5 + len(text) / 6))


class TextLayer(Canvas):
    """Draws the text (annotate.Painter mixes this layer and the pointer layer onto one Canvas)."""

    def init_text(self, font):
        """Fonts; style.caption_size sizes the step capsule and the key pill."""
        s = self.s
        self.f_small, self.f_label = font(round(13 * s), 500), font(round(15 * s), 600)
        self.ck = self.style["caption_size"] / CAPTION_DESIGN  # the step capsule and key pill scale with the title
        c = s * self.ck
        self.f_key = font(round(22 * c), 600)
        self.f_cap, self.f_cap_n = font(round(28 * c), 600), font(round(22 * c), 600)

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

    # --- caption panel (cached per text, faded by alpha)
    def capsule(self, n, total, title):
        """The pill / chapter caption: a translucent dark capsule, an amber dot (style.dot), "n/total", a hairline,
        the title."""
        key = ("capsule", n, total, title)
        if key not in self.cache:
            s = self.s * self.ck
            probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            num = f"{n}/{total}"
            nw, tw = probe.textlength(num, font=self.f_cap_n), probe.textlength(title, font=self.f_cap)
            pad, gap = 32 * s, 16 * s
            dot = 16 * s if self.style["dot"] else 0  # its diameter
            w, h = round(pad * 2 + (dot and dot + gap * 0.75) + nw + gap * 2 + tw), round(64 * s)
            im = Image.new("RGBA", (w, h))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([0, 0, w - 1, h - 1], radius=round(min(h / 2, 32 * s)), fill=(15, 17, 24, 170))
            cy = 32 * s
            if dot:
                d.ellipse([pad, cy - dot / 2, pad + dot, cy + dot / 2], fill=(255, 196, 64, 255))
            x = pad + (dot and dot + gap * 0.75)
            lx = x + nw + gap
            dim = Image.new("RGBA", im.size)  # drawn apart and composited: a translucent fill drawn straight onto
            dd = ImageDraw.Draw(dim)          # the capsule would replace its dark pixels instead of blending
            dd.text((x, cy), num, font=self.f_cap_n, fill=(255, 255, 255, 140), anchor="lm")
            dd.line([(lx, cy - 14 * s), (lx, cy + 14 * s)], fill=(255, 255, 255, 64), width=max(1, round(2 * s)))
            im.alpha_composite(dim)
            d.text((lx + gap, cy), title, font=self.f_cap, fill=(255, 255, 255, 255), anchor="lm")
            self.cache[key] = im
        return self.cache[key]

    def caption(self, ov, step, n, total, alpha, anchor):
        """Draw the step caption, the same capsule wherever style.caption puts it; returns how much of the bottom
        edge it covers (for the key pill)."""
        s, kind = self.s * self.ck, self.style["caption"]
        cap = self.capsule(n, total, step["title"])
        alpha, rise = cap_in(alpha)
        rise *= s
        if alpha < 1:
            cap = fade(cap, alpha)
        if kind == "callout" and anchor:
            X, Y = self.xy(*anchor)
            w, h = cap.size
            gap, edge = 72 * s, 16 * s  # clear of the click ring
            # the pointer and its name tag hang below and right of the tip: try left, above, right, below
            sides = [(X - gap - w, Y - h / 2), (X - w / 2, Y - gap - h), (X + gap + 150 * s, Y - h / 2), (X - w / 2, Y + gap + 60 * s)]
            fits = lambda xy: edge <= xy[0] <= self.w - edge - w and edge <= xy[1] <= self.h - edge - h
            over = lambda xy: max(0, edge - xy[0], xy[0] - (self.w - edge - w)) + max(0, edge - xy[1], xy[1] - (self.h - edge - h))
            x, y = next((xy for xy in sides if fits(xy)), min(sides, key=over))
            self.paste(ov, cap, min(max(x, edge), self.w - edge - w), min(max(y, edge), self.h - edge - h) + rise)
            return 0
        if kind == "chapter":
            self.paste(ov, cap, CAP_EDGE * s, CAP_EDGE * s + rise)
            return 0
        self.paste(ov, cap, (self.w - cap.width) / 2, self.h - CAP_EDGE * s - cap.height + rise)
        return cap.height + CAP_EDGE * s

    def keys(self, ov, item, t, alpha, bottom):
        """The key pill, centred with its bottom edge at y = bottom: keycaps joined by +, or the text typed so far."""
        s = self.s * self.ck
        d = ImageDraw.Draw(ov)
        pad, h, cap_h, gap = 12 * s, 54 * s, 38 * s, 22 * s
        if "caps" in item:
            widths = [d.textlength(c, font=self.f_key) + 28 * s for c in item["caps"]]
            w = sum(widths) + gap * (len(widths) - 1) + 2 * pad
        else:
            text = "".join(ch for ct, ch in item["chars"] if ct <= t)[-32:]  # the tail of a long text
            w = d.textlength(text, font=self.f_key) + 4 * pad
        x, y = (self.w - w) / 2, bottom - h
        d.rounded_rectangle([x, y, x + w, y + h], radius=16 * s, fill=(18, 20, 28, int(220 * alpha)))
        if "caps" in item:
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
        else:
            d.text((x + w / 2, y + h / 2), text, font=self.f_key, fill=(255, 255, 255, int(255 * alpha)), anchor="mm")

    def corner(self, ov, text):
        s = self.s
        d = ImageDraw.Draw(ov)
        tw = d.textlength(text, font=self.f_small)
        x, y = 10 * s, self.h - 30 * s
        d.rounded_rectangle([x, y, x + tw + 16 * s, y + 20 * s], radius=10 * s, fill=(0, 0, 0, 140))
        d.text((x + 8 * s, y + 10 * s), text, font=self.f_small, fill=(230, 230, 230, 230), anchor="lm")
