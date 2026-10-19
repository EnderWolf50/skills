# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "numpy", "opencv-python-headless"]
# ///
"""Burn touch events, step captions, boxes, zoom and privacy masks into a screen recording.

uv run annotate.py VIDEO -o OUT.mp4 --start HH:MM:SS[.fff] --events events.json \
    [--steps steps.json] [--masks masks.json] [--from T --to T] [--frames T,T,...] [--offset S]
    [--font FILE] [--no-video]

--start   wall time of the first video frame; every other time (events, steps, --from, --to, --frames) is wall time
--events  {"space":[w,h],"pointer"?:"touch|mouse|none","style"?:{...},"events":[{"t","kind":"tap|swipe|down|up","x","y","x2"?,"y2"?,"ms"?}]}; coordinates in
          `space`, mapped to the frame by its own size. swipe runs x,y -> x2,y2 over ms; down/up bracket a press
          (up may carry x,y = the release point)
--steps   [{"from","to","title","note"?,"boxes"?:[[x,y,w,h,"label"]],"zoom"?:[x,y,w,h]}] in the events' space
--masks   {"space":[w,h],"masks":[{"template":"a.png","threshold":0.8,"boxes":[[x,y,w,h]]}]}: a box is blacked out
          while its template matches (2 fps scan, +-1 s around each hit); template paths relative to the masks file
--from/--to  cut a clip; --frames also saves those annotated frames as PNG next to OUT; --no-video writes only them
--offset  calibration: seconds added to every event time before mapping to video time
--font    a CJK-capable font file (default: first of the usual Windows / Linux ones)
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import cursor_motion as cm

ACCENT = (255, 196, 64)  # amber: steps, boxes
POINTERS = ("touch", "mouse", "none")
FONTS = [  # CJK first: Windows, then Linux
    "C:/Windows/Fonts/NotoSansTC-VF.ttf", "C:/Windows/Fonts/msjh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
HOLD_S = 0.3  # a press without movement longer than this is a hold
FADE_S = 0.35  # step caption and box fade
ZOOM_S = 0.6  # zoom ease-in / ease-out
RING_S = 0.6  # click ring: grows and fades after a press (and a drag's or hold's release), never before
PRESS_S = 0.13  # pointer shrinks to PRESS_K this long before a press and grows back after the release
PRESS_K = 0.8
STYLE = {"cursor": "mac", "color": None, "label": "", "trail": True, "motion": "signature_arc", "arc": 0.25,
         "tilt": 1.0}  # events.json "style"; color None = the cursor's own (COLORS)
CURSORS = ("mac", "cua", "figma")
COLORS = {"mac": "#4785ff", "cua": "#5ec0e8", "figma": "#4785ff"}
FX = 2.5  # pointers are drawn this many times Cua's 42 pt cursor, so its glow and trail scale with them
PX = 1280  # glides are planned in pixels of a 1280-wide frame, about Cua's screen points

# pointer outlines in pointer units (3.2 px at 1280 wide), tip at 0,0, and where each tip points at rest
SHAPES = {"mac": [(0, 0), (0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12.5), (12.5, 12.5)],
          "figma": [(0, 0), (0, 14), (4, 10.5), (10.5, 10.5)]}
TIPS = {"mac": float(np.arctan2(-1, -0.62)), "figma": float(np.arctan2(-1, -0.75)), "cua": cm.TIP_ANGLE}
# Cua Driver's cursor body (cursor-overlay/assets/build_default_theme.py CURSOR_PATH via @trycua/cursor-motion,
# MIT) on its 128-unit canvas, tip at (55, 30), and the glow strokes under it: (width, opacity)
CUA_PATH = ("M55 30 C48 28 42 33 43 41 C43 41 64 98 64 98 C67 106 73 106 77 99 C77 99 86 79 86 79 "
            "C88 75 91 72 95 70 C95 70 108 63 108 63 C115 59 114 53 107 50 C107 50 55 30 55 30 Z")
CUA_GLOW = [(44, 0.02), (36, 0.024), (29, 0.03), (23, 0.038), (18, 0.048), (14, 0.06), (10, 0.075), (7, 0.095)]


def svg_points(path, n=12):
    """Polygon of an SVG path made of M and C commands, each curve sampled n times."""
    tok = re.findall(r"[MC]|-?[\d.]+", path)
    pts, i = [], 0
    while i < len(tok):
        if tok[i] == "M":
            pts.append((float(tok[i + 1]), float(tok[i + 2])))
            i += 3
        else:  # C x1 y1 x2 y2 x y
            p0, (c1, c2, p3) = pts[-1], [(float(tok[i + k]), float(tok[i + k + 1])) for k in (1, 3, 5)]
            for u in (j / n for j in range(1, n + 1)):
                v = 1 - u
                pts.append(tuple(v ** 3 * a + 3 * v * v * u * b + 3 * v * u * u * c + u ** 3 * d
                                 for a, b, c, d in zip(p0, c1, c2, p3)))
            i += 7
    return pts


# ---------------------------------------------------------------- time

def hms(s):
    """'14:30:41.2' -> seconds of the day."""
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def fmt(t, nd=1):
    """Seconds of the day -> 'HH:MM:SS.f' with nd decimals; rounds first so it never prints seconds = 60."""
    k = 10 ** nd
    n = round(t * k) % (86400 * k)
    s, f = divmod(n, k)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}.{f:0{nd}d}"


# ---------------------------------------------------------------- events -> gestures

def gestures(events):
    """Gestures in event space: {"kind": tap|hold|drag, "t0", "t1", "pts": [(t, x, y), ...]} sorted by t0.

    ponytail: one contact; a second `down` while one is open closes the first at that time."""
    out, held = [], None
    for e in sorted(events, key=lambda e: hms(e["t"])):
        t, k = hms(e["t"]), e["kind"]
        need = {"tap": "xy", "swipe": ("x", "y", "x2", "y2"), "down": "xy"}.get(k, ())
        if missing := [f for f in need if f not in e]:
            raise ValueError(f"{k} event at {e['t']} lacks {', '.join(missing)}: {e}")
        if k in ("tap", "swipe"):
            d = e.get("ms", 50 if k == "tap" else 200) / 1000
            pts = [(t, e["x"], e["y"])] + ([(t + d, e["x2"], e["y2"])] if k == "swipe" else [])
            out.append({"t0": t, "t1": t + d, "pts": pts})
        elif k == "down":
            if held:
                held["t1"] = t
            held = {"t0": t, "t1": t, "pts": [(t, e["x"], e["y"])]}
            out.append(held)
        elif k == "up":
            if held:  # a stray `up` (nothing held) is ignored
                if "x" in e:
                    held["pts"].append((t, e["x"], e["y"]))
                held["t1"] = t
                held = None
        else:
            raise ValueError(f"bad event {e}")
    if held:
        held["t1"] = max(held["t1"], held["t0"] + 0.05)
    for g in out:
        x0, y0 = g["pts"][0][1:]
        moved = any(abs(x - x0) > 4 or abs(y - y0) > 4 for _, x, y in g["pts"])
        g["kind"] = "drag" if moved else "hold" if g["t1"] - g["t0"] > HOLD_S else "tap"
    return sorted(out, key=lambda g: g["t0"])


def pos_at(g, t):
    """(x, y) of gesture g at time t in event space: its first point before, its last after, interpolated between."""
    pts = g["pts"]
    if t <= pts[0][0]:
        return pts[0][1:]
    if t >= pts[-1][0]:
        return pts[-1][1:]
    i = next(i for i in range(1, len(pts)) if pts[i][0] >= t)
    (ta, xa, ya), (tb, xb, yb) = pts[i - 1], pts[i]
    u = (t - ta) / (tb - ta) if tb > ta else 1
    return xa + (xb - xa) * u, ya + (yb - ya) * u


class Track:
    """Where a mouse pointer is: at rest on the gestures, gliding between them as Cua Driver moves its cursor
    (cursor_motion), arriving as each press starts. Glides are planned in 1280-wide frame pixels."""

    def __init__(self, gs, style, to_px):
        self.gs, self.to_px = gs, to_px  # to_px: event space -> 1280-wide pixels
        self.glides = []  # (start s, gesture, trajectory, glide end point)
        for prev, g in zip(gs, gs[1:]):
            a, b = to_px(*pos_at(prev, prev["t1"])), to_px(*pos_at(g, g["t0"]))
            gap = g["t0"] - prev["t1"]
            if gap < 0.02 or np.hypot(b[0] - a[0], b[1] - a[1]) < 1:
                continue
            traj = cm.plan(a, b, style["motion"], arc_size=style["arc"], tilt=style["tilt"], tip_angle=TIPS[style["cursor"]])
            if traj.arrival > gap:  # the log leaves less time than the move takes: play it faster
                traj = traj.scaled(gap / traj.arrival)
            self.glides.append((g["t0"] - traj.arrival, g, traj, b))

    def at(self, t):
        """(x, y, heading, trajectory or None, seconds into it) in 1280-wide pixels."""
        gl = next((gl for gl in reversed(self.glides) if gl[0] <= t), None)
        on = next((g for g in reversed(self.gs) if g["t0"] <= t), self.gs[0])
        if gl and t < gl[1]["t0"]:  # gliding
            _, x, y, h = gl[2].sample_at(t - gl[0])
            return x, y, h, gl[2], t - gl[0]
        x, y = self.to_px(*pos_at(on, t))
        if gl and gl[1] is on and t - gl[0] <= gl[2].duration():  # arrived: the settle plays around the gesture
            _, sx, sy, h = gl[2].sample_at(t - gl[0])
            return x + sx - gl[3][0], y + sy - gl[3][1], h, gl[2], t - gl[0]
        return x, y, cm.REST_HEADING, None, 0.0


def load_style(doc):
    """events.json "style" over STYLE, checked: cursor one of CURSORS, color #rrggbb (-> RGB tuple)."""
    st = {**STYLE, **doc.get("style", {})}
    if unknown := set(st) - set(STYLE):
        sys.exit(f"events: unknown style keys {sorted(unknown)}; known: {', '.join(STYLE)}")
    if st["cursor"] not in CURSORS:
        sys.exit(f"events: style.cursor must be one of {', '.join(CURSORS)}, got {st['cursor']!r}")
    if st["motion"] not in cm.STYLES:
        sys.exit(f"events: style.motion must be one of {', '.join(cm.STYLES)}, got {st['motion']!r}")
    for k, lo, hi in (("arc", 0, 1), ("tilt", 0, 1)):
        if not isinstance(st[k], (int, float)) or not lo <= st[k] <= hi:
            sys.exit(f"events: style.{k} must be a number from {lo} to {hi}, got {st[k]!r}")
    c = str(st["color"] or COLORS[st["cursor"]]).lstrip("#")
    try:
        st["color"] = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else None
    except ValueError:
        st["color"] = None
    if st["color"] is None:
        sys.exit(f"events: style.color must be #rrggbb, got {doc['style']['color']!r}")
    return st


def press_k(gs, t):
    """Pointer scale at t: PRESS_K while pressed, eased over PRESS_S before the press and after the release."""
    p = max((min(ease((t - g["t0"] + PRESS_S) / PRESS_S), ease((g["t1"] + PRESS_S - t) / PRESS_S)) for g in gs), default=0)
    return 1 - (1 - PRESS_K) * p


def shift(gs, offset):
    for g in gs:
        g["t0"] += offset
        g["t1"] += offset
        g["pts"] = [(t + offset, x, y) for t, x, y in g["pts"]]
    return gs


# ---------------------------------------------------------------- steps and zoom

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


def ease(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def fit_region(r, space):
    """Grow region [x,y,w,h] to the aspect of `space` (w,h), keep its centre, slide it inside the space."""
    sw, sh = space
    x, y, w, h = r
    if w / h < sw / sh:
        w = h * sw / sh
    else:
        h = w * sh / sw
    w, h = min(w, sw), min(h, sh)
    cx, cy = x + r[2] / 2, y + r[3] / 2
    return min(max(cx - w / 2, 0), sw - w), min(max(cy - h / 2, 0), sh - h), w, h


def zoom_region(step, t, space):
    """Region [x,y,w,h] of `space` shown at time t: eases from the full frame into step["zoom"] and back out."""
    z = step.get("zoom")
    if not z:
        return None
    p = ease(min((t - step["from"]) / ZOOM_S, (step["to"] - t) / ZOOM_S))
    full, tgt = (0, 0, *space), fit_region(z, space)
    return tuple(a + (b - a) * p for a, b in zip(full, tgt))


# ---------------------------------------------------------------- masks

def load_masks(path):
    """([(template_gray, threshold, boxes)], (space_w, space_h)); template paths are relative to the masks file."""
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for m in doc["masks"]:
        tpl = cv2.imread(str(p.parent / m["template"]), cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            sys.exit(f"mask template {m['template']} not readable")
        for b in m["boxes"]:
            if len(b) != 4 or not all(isinstance(v, (int, float)) for v in b) or b[2] <= 0 or b[3] <= 0:
                sys.exit(f"mask {m['template']}: box must be [x,y,w,h] with w and h above 0, got {b}")
        out.append((tpl, m.get("threshold", 0.8), m["boxes"]))
    return out, parse_space(doc, "masks")


def parse_space(doc, what):
    """doc["space"] as two positive ints (it is interpolated into an ffmpeg -vf, so it must be numbers)."""
    try:
        w, h = (int(v) for v in doc["space"])
    except (KeyError, TypeError, ValueError):
        sys.exit(f"{what}: space must be [width, height] as two numbers, got {doc.get('space')!r}")
    if w <= 0 or h <= 0:
        sys.exit(f"{what}: space must be above 0, got {[w, h]}")
    return w, h


def matches(gray, tpl, threshold):
    """True when the template is found in the gray frame (both already at space size)."""
    if tpl.shape[0] > gray.shape[0] or tpl.shape[1] > gray.shape[1]:
        return False
    return cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED).max() >= threshold


def merge_spans(hits, pad=1.0):
    """Clip times (s) where a template matched -> [[t0, t1]] with `pad` seconds each side, touching spans merged."""
    spans = []
    for t in sorted(hits):
        if spans and t - pad <= spans[-1][1]:
            spans[-1][1] = t + pad
        else:
            spans.append([max(0.0, t - pad), t + pad])
    return spans


def mask_spans(video, ss, dur, masks, space):
    """Per mask: spans in clip time where its template shows (2 fps scan)."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
           "-vf", f"fps=2,scale={space[0]}:{space[1]}", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n, hits, i = space[0] * space[1], [[] for _ in masks], 0
    while (buf := p.stdout.read(n)) and len(buf) == n:
        gray = np.frombuffer(buf, np.uint8).reshape(space[1], space[0])
        for h, (tpl, thr, _) in zip(hits, masks):
            if matches(gray, tpl, thr):
                h.append(i / 2)
        i += 1
    if p.wait():
        sys.exit(f"ffmpeg failed while scanning for masks (rc {p.returncode})")
    return [merge_spans(h) for h in hits]


def apply_masks(frame, tv, masks, spans, space):
    """Black out the boxes of every mask whose span covers clip time tv; boxes are clamped to the frame."""
    H, W = frame.shape[:2]
    for (_, _, boxes), sp in zip(masks, spans):
        if any(a <= tv <= b for a, b in sp):
            for x, y, w, h in boxes:
                y0, y1 = (min(max(round(v * H / space[1]), 0), H) for v in (y, y + h))
                x0, x1 = (min(max(round(v * W / space[0]), 0), W) for v in (x, x + w))
                frame[y0:y1, x0:x1] = 0


# ---------------------------------------------------------------- drawing

def pick_font(arg):
    for p in ([arg] if arg else FONTS):
        if Path(p).exists():
            return p
    sys.exit("no CJK font found: pass --font FILE")


class Painter:
    def __init__(self, w, h, space, font_path, style=None):
        self.w, self.h, self.space = w, h, space
        self.style = style or load_style({})
        self.color = self.style["color"]
        self.sx, self.sy, self.s = w / space[0], h / space[1], w / 1280  # s scales sizes, sx/sy scale positions
        s = self.s

        def font(size, weight):
            f = ImageFont.truetype(font_path, size)
            try:
                f.set_variation_by_axes([weight])  # variable fonts only
            except (OSError, AttributeError):
                pass
            return f

        self.f_title, self.f_note = font(round(26 * s), 700), font(round(17 * s), 400)
        self.f_badge, self.f_small, self.f_label = font(round(20 * s), 800), font(round(13 * s), 500), font(round(15 * s), 600)
        self.f_tag = font(round(22 * s), 600)
        self.cache = {}

    def xy(self, x, y):
        return x * self.sx, y * self.sy

    # --- touches
    def circle(self, ov, X, Y, r, fill, fill_a, edge, edge_a, edge_w):
        """Antialiased disc of radius r with a centred edge band edge_w wide, composited onto ov."""
        R = r + edge_w
        x0, y0, x1, y1 = max(0, int(X - R) - 1), max(0, int(Y - R) - 1), min(self.w, int(X + R) + 2), min(self.h, int(Y + R) + 2)
        if x0 >= x1 or y0 >= y1 or r <= 0:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        d = np.hypot(xx + 0.5 - X, yy + 0.5 - Y)
        ae = edge_a * np.clip(edge_w / 2 - np.abs(d - r) + 0.5, 0, 1)
        af = fill_a * np.clip(r - d + 0.5, 0, 1) * (1 - ae)
        a = ae + af
        rgb = (np.multiply.outer(ae, edge) + np.multiply.outer(af, fill)) / np.maximum(a, 1e-6)[..., None]
        ov.alpha_composite(Image.fromarray(np.dstack([rgb, a * 255]).round().astype(np.uint8), "RGBA"), (x0, y0))

    def ring(self, ov, X, Y, age):
        """Click ring: grows to 100 px (at 1280 wide) with ease-out cubic and fades over RING_S after the press."""
        p = age / RING_S
        if 0 <= p <= 1:
            R, a = 100 * self.s, 0.7 * (1 - p) ** 1.5
            self.circle(ov, X, Y, R * (1 - (1 - p) ** 3), self.color, 0.3 * a, self.color, a, (0.1 + 0.06 * p) * R * 0.6)

    def sprite(self, k):
        """Pointer sprite at press scale k, drawn 4x and scaled down, square with the tip at its centre (so it
        rotates about the tip): (image, half size). Look by style.cursor; cua and figma take style.color."""
        k = round(k * 25) / 25  # 6 sizes between PRESS_K and 1: each is a 4x draw and blur, so cache few
        if ("sprite", k) in self.cache:
            return self.cache[("sprite", k)]
        kind, rgb = self.style["cursor"], self.color
        if kind == "cua":  # 128-unit canvas shown 42 pt x FX, tip at (55, 30)
            u = 42 * FX / 128 * self.s * k * 4
            pts, tip = svg_points(CUA_PATH), (55, 30)
        else:
            u = 3.2 * self.s * k * 4
            pts, tip = SHAPES[kind], (0, 0)
        half = round(130 * u) if kind == "cua" else round(30 * u)  # room for the shape, its glow and any rotation
        size = (2 * half, 2 * half)
        mask = Image.new("L", size)
        ImageDraw.Draw(mask).polygon([(half + (x - tip[0]) * u, half + (y - tip[1]) * u) for x, y in pts], fill=255)
        m = np.asarray(mask)

        def grow(w):  # mask grown (w > 0) or shrunk by w units, round corners
            r = max(1, round(abs(w) * u))
            disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
            return Image.fromarray((cv2.dilate if w > 0 else cv2.erode)(m, disc))

        im = Image.new("RGBA", size)
        if kind == "cua":  # Cua's soft glow strokes, then the body with a white stroke centred on its edge
            for w, a in CUA_GLOW:
                layer = Image.new("RGBA", size, rgb)
                layer.putalpha(grow(w / 2).point(lambda v: int(v * a)))
                im.alpha_composite(layer)
            im.paste((255, 255, 255, 255), (0, 0), grow(2.5))
            im.paste((*rgb, 255), (0, 0), grow(-2.5))
        else:  # drop shadow, white rim outside the outline, then the fill
            edge = {"mac": 1.3, "figma": 1.2}[kind]
            border = grow(edge)
            shadow = Image.new("RGBA", size, (0, 0, 0))
            a, blur = {"mac": (0.3, 4), "figma": (0.25, 3)}[kind]
            shadow.putalpha(border.filter(ImageFilter.GaussianBlur(blur * u / 3.2)).point(lambda v: int(v * a)))
            im.alpha_composite(shadow, (0, round(u)))
            im.paste((255, 255, 255, 255), (0, 0), border)
            im.paste((17, 17, 17, 255) if kind == "mac" else (*rgb, 255), (0, 0), mask)
        out = (im.resize((size[0] // 4, size[1] // 4), Image.LANCZOS), half // 4)
        self.cache[("sprite", k)] = out
        return out

    def tag(self):
        """Name tag (style.label) in the style colour, or None without a label."""
        if not self.style["label"]:
            return None
        if "tag" not in self.cache:
            s = self.s
            probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            tw = probe.textlength(self.style["label"], font=self.f_tag)
            w, h = round(tw + 26 * s), round(35 * s)
            im = Image.new("RGBA", (w, h))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([0, 0, w - 1, h - 1], radius=round(10 * s), fill=(*self.color, 255))
            d.text((13 * s, h / 2), self.style["label"], font=self.f_tag, fill=(255, 255, 255, 255), anchor="lm")
            self.cache["tag"] = im
        return self.cache["tag"]

    def paste(self, ov, im, x, y):
        """alpha_composite im at (x, y), clipped to the frame."""
        x, y = round(x), round(y)
        box = (max(0, -x), max(0, -y), min(im.width, self.w - x), min(im.height, self.h - y))
        if box[0] < box[2] and box[1] < box[3]:
            ov.alpha_composite(im.crop(box), (x + box[0], y + box[1]))

    def track(self, gs):
        return Track(gs, self.style, lambda x, y: (x * self.sx / self.s, y * self.sy / self.s))

    def radial(self, ov, X, Y, r, rgb, alpha):
        """Soft disc: alpha at the centre falling linearly to 0 at radius r."""
        x0, y0, x1, y1 = max(0, int(X - r)), max(0, int(Y - r)), min(self.w, int(X + r) + 1), min(self.h, int(Y + r) + 1)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        a = alpha * np.clip(1 - np.hypot(xx + 0.5 - X, yy + 0.5 - Y) / r, 0, 1)
        ov.alpha_composite(Image.fromarray(np.dstack([np.broadcast_to(rgb, a.shape + (3,)), a * 255]).astype(np.uint8), "RGBA"), (x0, y0))

    def cursor(self, ov, track, gs, t):
        """The mouse pointer on its track, its speed glow and comet trail (by style.motion), shrinking while
        pressing; the name tag stays upright beside the tip."""
        s, fx = self.s, cm.lift(self.color)
        x, y, heading, traj, lt = track.at(t)
        if traj and "trail" in traj.effects:
            layer = Image.new("RGBA", (self.w, self.h))
            d = ImageDraw.Draw(layer)
            for a, b, w, al in cm.trail(traj, lt, cm.ANCHOR_OFFSET * FX):
                d.line([(a[0] * s, a[1] * s), (b[0] * s, b[1] * s)], fill=(*fx, int(255 * al)), width=max(1, round(w * FX * s)), joint="curve")
            ov.alpha_composite(layer)
        if traj and "glow" in traj.effects and (g := cm.glow(traj, lt, cm.anchor(x, y, heading, cm.ANCHOR_OFFSET * FX))):
            gx, gy = cm.anchor(x, y, heading, cm.ANCHOR_OFFSET * FX)  # glow sits off the body by FX x Cua's offset
            self.radial(ov, (gx + (g[0] - gx) * FX) * s, (gy + (g[1] - gy) * FX) * s, g[2] * FX * s, fx, g[3])
        im, half = self.sprite(press_k(gs, t))
        rot = heading - cm.REST_HEADING
        if abs(rot) > 0.005:
            im = im.rotate(-np.degrees(rot), resample=Image.BICUBIC, center=(half, half))
        X, Y = x * s, y * s
        self.paste(ov, im, X - half, Y - half)
        if tag := self.tag():
            self.paste(ov, tag, X + 29 * s, Y + 38 * s)

    def gesture(self, ov, d, g, t, pointer):
        """Rings at the press (and a drag's or hold's release), the drag trail, and for touch a fingertip dot."""
        s = self.s
        t0, t1 = g["t0"], g["t1"]
        X, Y = self.xy(*pos_at(g, t))
        if g["kind"] == "drag" and self.style["trail"] and t0 <= t <= t1 + 0.5:  # trail from the start to the finger, fading after release
            a = 1 - max(0, t - t1) / 0.5
            line = [self.xy(px, py) for pt, px, py in g["pts"] if pt <= t] + [(X, Y)]
            d.line(line, fill=(*self.color, int(140 * a)), width=max(2, round(12 * s)), joint="curve")
        self.ring(ov, *self.xy(*pos_at(g, t0)), t - t0)
        if g["kind"] != "tap":
            self.ring(ov, X, Y, t - t1)
        if pointer == "touch":
            vis = max(0.0, min(1, (t1 + 0.3 - t) / 0.3))  # appears on the press itself: a finger has no hover
            if t >= t0 and vis > 0:
                self.circle(ov, X, Y, 28 * s * press_k([g], t), (255, 255, 255), 0.95 * vis, (0, 0, 0), 0.25 * vis, 4 * s)

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
    def panel(self, n, title, note):
        key = (n, title, note)
        if key in self.cache:
            return self.cache[key]
        s = self.s
        pad, badge = round(16 * s), round(36 * s)
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        note = note or ""
        while note and probe.textlength(note, font=self.f_note) > 1000 * s:
            note = note[:-2].rstrip() + "…" if not note.endswith("…") else note[:-2] + "…"
        tw = max(probe.textlength(title, font=self.f_title), probe.textlength(note, font=self.f_note))
        w = round(pad * 3 + badge + tw)
        h = round(pad * 2 + 34 * s + (24 * s if note else 0))
        im = Image.new("RGBA", (w + 24, h + 24))
        sh = Image.new("RGBA", im.size)
        ImageDraw.Draw(sh).rounded_rectangle([12, 16, w + 12, h + 14], radius=round(14 * s), fill=(0, 0, 0, 120))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([12, 12, w + 12, h + 12], radius=round(14 * s), fill=(18, 20, 28, 196), outline=(255, 255, 255, 40), width=1)
        bx, by = 12 + pad, 12 + pad
        d.ellipse([bx, by, bx + badge, by + badge], fill=ACCENT)
        d.text((bx + badge / 2, by + badge / 2), str(n), font=self.f_badge, fill=(24, 22, 18), anchor="mm")
        tx = bx + badge + pad
        d.text((tx, by + badge / 2), title, font=self.f_title, fill=(255, 255, 255), anchor="lm")
        if note:
            d.text((tx, by + badge + 4 * s), note, font=self.f_note, fill=(205, 214, 228), anchor="lt")
        self.cache[key] = im
        return im

    def corner(self, ov, text):
        s = self.s
        d = ImageDraw.Draw(ov)
        tw = d.textlength(text, font=self.f_small)
        x, y = 10 * s, self.h - 30 * s
        d.rounded_rectangle([x, y, x + tw + 16 * s, y + 20 * s], radius=10 * s, fill=(0, 0, 0, 140))
        d.text((x + 8 * s, y + 10 * s), text, font=self.f_small, fill=(230, 230, 230, 230), anchor="lm")


def blend(frame, ov):
    """Alpha-composite the RGBA overlay onto the RGB frame in place, only inside the overlay's bounding box."""
    box = ov.getbbox()
    if box:
        x0, y0, x1, y1 = box
        o = np.asarray(ov.crop(box), dtype=np.float32)
        a = o[:, :, 3:4] / 255
        frame[y0:y1, x0:x1] = (frame[y0:y1, x0:x1].astype(np.float32) * (1 - a) + o[:, :, :3] * a).astype(np.uint8)


def zoom_frame(frame, region, space):
    """Crop `region` (event-space [x,y,w,h]) out of the frame and scale it back to the frame size."""
    H, W = frame.shape[:2]
    x, y, w, h = region
    x0, y0 = min(max(round(x * W / space[0]), 0), W - 2), min(max(round(y * H / space[1]), 0), H - 2)
    x1, y1 = min(max(x0 + 2, round((x + w) * W / space[0])), W), min(max(y0 + 2, round((y + h) * H / space[1])), H)
    return cv2.resize(frame[y0:y1, x0:x1], (W, H), interpolation=cv2.INTER_LINEAR)


# ---------------------------------------------------------------- render

def encoder_args():
    """NVENC when a one-frame probe encode works (the -encoders list only says it was compiled in), else libx264."""
    ok = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256", "-frames:v", "1",
                         "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True).returncode == 0
    return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "27"] if ok else ["-c:v", "libx264", "-crf", "23"]


def frame_indices(times, start, ss, fps, nframes):
    """Frame numbers for wall `times` (HH:MM:SS.fff strings) in a clip that starts ss s after `start`.
    Times outside the clip are reported on stderr and dropped."""
    out = set()
    for f in times:
        n = round((hms(f) - start - ss) * fps)
        if 0 <= n < nframes:
            out.add(n)
        else:
            print(f"[annotate] warning: --frames {f} is outside the cut, skipped", file=sys.stderr, flush=True)
    return out


def clip_bounds(start, frm, to, total):
    """(ss, dur): seconds into the video where the cut starts, and its length. --from/--to are wall times.
    Exits when --from precedes --start (ffmpeg would decode from 0 and shift every annotation by the gap)."""
    ss = hms(frm) - start if frm else 0.0
    if ss < 0:
        sys.exit(f"--from {frm} is {-ss:.1f} s before --start {fmt(start)}: the video has nothing there")
    dur = (hms(to) - start - ss) if to else total - ss
    if dur <= 0:
        sys.exit(f"the cut is empty: --from/--to give {dur:.1f} s (video length {total:.1f} s)")
    return ss, dur


def render(args):
    doc = json.loads(Path(args.events).read_text(encoding="utf-8"))
    space = parse_space(doc, "events")
    gs = shift(gestures(doc["events"]), args.offset)
    pointer = doc.get("pointer", "touch")
    style = load_style(doc)
    if pointer not in POINTERS:
        sys.exit(f"events: pointer must be one of {', '.join(POINTERS)}, got {pointer!r}")
    steps = load_steps(args.steps) if args.steps else []
    masks, mspace = load_masks(args.masks) if args.masks else ([], space)
    start = hms(args.start)
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                       "stream=width,height,r_frame_rate:format=duration", "-of", "json", args.video],
                                      capture_output=True, text=True, check=True).stdout)
    st = probe["streams"][0]
    W, H = st["width"], st["height"]
    num, den = map(int, st["r_frame_rate"].split("/"))
    fps = num / den
    ss, dur = clip_bounds(start, getattr(args, "from"), args.to, float(probe["format"]["duration"]))
    print(f"[annotate] {len(gs)} gestures, {len(steps)} steps, {len(masks)} masks, clip {ss:.1f}+{dur:.1f}s", flush=True)
    spans = mask_spans(args.video, ss, dur, masks, mspace) if masks else []
    paint = Painter(W, H, space, pick_font(args.font), style)
    track = paint.track(gs) if pointer == "mouse" and gs else None
    want = frame_indices(args.frames.split(","), start, ss, fps, int(dur * fps)) if args.frames else set()
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", args.video,
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = None if args.no_video else subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{num}/{den}",
         "-i", "-", *encoder_args(), "-pix_fmt", "yuv420p", "-movflags", "+faststart", args.out], stdin=subprocess.PIPE)
    n, size, gi = 0, W * H * 3, 0
    while (buf := dec.stdout.read(size)) and len(buf) == size:
        tv = n / fps  # clip time
        t = start + ss + tv  # wall time
        frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        apply_masks(frame, tv, masks, spans, mspace)
        cur = step_at(steps, t)
        ov = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(ov)
        if cur:  # boxes and touches live in the zoomed picture
            for x, y, w, h, *label in cur[1].get("boxes", []):
                paint.box(d, x, y, w, h, label[0] if label else "", cur[2])
        while gi < len(gs) and gs[gi]["t1"] + 0.7 < t:
            gi += 1
        j = gi
        while j < len(gs) and gs[j]["t0"] - 0.3 <= t:
            paint.gesture(ov, d, gs[j], t, pointer)
            j += 1
        if track:
            paint.cursor(ov, track, gs, t)
        blend(frame, ov)
        region = zoom_region(cur[1], t, space) if cur else None
        if region:
            frame = zoom_frame(frame, region, space)
        ov = Image.new("RGBA", (W, H))  # captions stay put
        if cur:
            i, step, alpha = cur
            pan = paint.panel(i + 1, step["title"], step.get("note"))
            if alpha < 1:
                pan = pan.copy()
                pan.putalpha(pan.getchannel("A").point(lambda v: int(v * alpha)))
            ov.alpha_composite(pan, ((W - pan.width) // 2, H - pan.height - round(8 * paint.s)))
        paint.corner(ov, fmt(t) + (f"  ·  步驟 {cur[0] + 1}/{len(steps)}" if cur else ""))
        blend(frame, ov)
        if n in want:
            png = Path(args.out).with_name(f"{Path(args.out).stem}_{fmt(t, 3).replace(':', '')}.png")
            Image.fromarray(frame).save(png)
            print(f"[annotate] frame {png}", flush=True)
        if enc:
            enc.stdin.write(frame.tobytes())
        n += 1
        if n % 1800 == 0:
            print(f"[annotate] {n} frames ({tv:.0f}s)", flush=True)
    if enc:
        enc.stdin.close()
        enc.wait()
    dec.wait()
    if n == 0 or dec.returncode or (enc and enc.returncode):
        sys.exit(f"no output: ffmpeg decode rc {dec.returncode}, encode rc {enc.returncode if enc else '-'}, {n} frames "
                 f"(check VIDEO, --from/--to and --start)")
    print(f"[annotate] done ({n} frames)" + ("" if args.no_video else f", wrote {args.out}"), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--events", required=True)
    ap.add_argument("--steps")
    ap.add_argument("--masks")
    ap.add_argument("--from")
    ap.add_argument("--to")
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--frames")
    ap.add_argument("--font")
    ap.add_argument("--no-video", action="store_true")
    render(ap.parse_args(argv))


if __name__ == "__main__":
    main()
