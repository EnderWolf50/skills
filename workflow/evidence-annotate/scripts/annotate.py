# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "numpy", "opencv-python-headless"]
# ///
"""Burn touch events, step captions, boxes, zoom and privacy masks into a screen recording.

uv run annotate.py VIDEO -o OUT.mp4 --start HH:MM:SS[.fff] --events events.json \
    [--steps steps.json] [--masks masks.json] [--from T --to T] [--frames T,T,...] [--offset S]
    [--font FILE] [--no-video]

--start   wall time of the first video frame; every other time (events, steps, --from, --to, --frames) is wall time
--events  {"space":[w,h],"pointer"?:"touch|mouse|none","style"?:{...},"events":[{"t","kind":"tap|swipe|down|up","x","y","x2"?,"y2"?,"ms"?}
          or {"t","kind":"key","keys":"Ctrl+S"} or {"t","kind":"type","text":"...","ms"?}]}; coordinates in
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
from queue import Queue
from threading import Thread

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
         "tilt": 1.0, "zoom": 0, "idle_fade": 0, "float": False, "frame": None, "caption": "pill"}  # events.json "style"; color None = the
# cursor's own (COLORS); zoom and idle_fade 0 = off
CURSORS = ("mac", "cua", "figma")
CAPTIONS = ("pill", "callout", "chapter")  # bottom-centre capsule, a card beside the step's press, top-left capsule
ZOOM_DEFAULT = 1.5  # "zoom": true (Cap's default for a zoom added by hand; Recordly's autozoom is 1.8)
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
    for e in sorted((e for e in events if e["kind"] not in KEYS), key=lambda e: hms(e["t"])):
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
        self.moving = sorted([(st, st + tr.duration()) for st, _, tr, _ in self.glides] + [(g["t0"], g["t1"]) for g in gs])

    def rest(self, t):
        """(seconds at rest so far, seconds until the next move): (0, 0) while moving or pressing."""
        if any(a <= t <= b for a, b in self.moving):
            return 0.0, 0.0
        since = t - max((b for a, b in self.moving if b < t), default=-np.inf)
        return since, min((a for a, b in self.moving if a > t), default=np.inf) - t

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
    if st["caption"] not in CAPTIONS:
        sys.exit(f"events: style.caption must be one of {', '.join(CAPTIONS)}, got {st['caption']!r}")
    if isinstance(st["zoom"], bool):  # true is the default magnification, false is off
        st["zoom"] = ZOOM_DEFAULT if st["zoom"] else 0
    for k, lo, hi in (("arc", 0, 1), ("tilt", 0, 1), ("zoom", 0, 4), ("idle_fade", 0, 600)):
        if not isinstance(st[k], (int, float)) or not lo <= st[k] <= hi:
            sys.exit(f"events: style.{k} must be a number from {lo} to {hi}, got {st[k]!r}")
    given, st["color"] = st["color"], rgb(st["color"] or COLORS[st["cursor"]])
    if st["color"] is None:
        sys.exit(f"events: style.color must be #rrggbb, got {given!r}")
    if st["frame"] is not None:
        stops = st["frame"] if isinstance(st["frame"], list) else [st["frame"]]
        if not 1 <= len(stops) <= 2 or None in (stops := [rgb(c) for c in stops]):
            sys.exit(f"events: style.frame must be #rrggbb or [#rrggbb, #rrggbb], got {st['frame']!r}")
        st["frame"] = stops
    return st


def rgb(c):
    """'#rrggbb' -> (r, g, b), or None when it is not one."""
    c = str(c).lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else None
    except ValueError:
        return None


def press_k(gs, t):
    """Pointer scale at t: PRESS_K while pressed, eased over PRESS_S before the press and after the release."""
    p = max((min(ease((t - g["t0"] + PRESS_S) / PRESS_S), ease((g["t1"] + PRESS_S - t) / PRESS_S)) for g in gs), default=0)
    return 1 - (1 - PRESS_K) * p


KEY_HOLD_S = 1.0  # a key pill stays this long after its last key
TYPE_MS = 45  # a `type` event reveals one character this often unless it gives "ms"
TYPE_JOIN_S = 1.2  # typing that starts this soon after the last character joins the same pill
KEYS = ("key", "type")


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


def step_anchor(step, gs):
    """Where a callout points: the first press inside the step, else the centre of its first box, else None."""
    g = next((g for g in gs if step["from"] <= g["t0"] < step["to"]), None)
    if g:
        return pos_at(g, g["t0"])
    if step.get("boxes"):
        x, y, w, h, *_ = step["boxes"][0]
        return x + w / 2, y + h / 2
    return None


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


CAM_HOLD_S = 1.0  # the camera stays in this long after a zoomed group's last action
CAM_LEAD_S = 0.6  # starts moving this long before a group's first press: the spring settles in ~0.55 s
CAM_GAP_S = 2.5  # a quieter gap than this ends a run of activity (Cap merges zooms closer than 2.5 s)
CAM_PAD = 1.4  # the framed presses fill at most 1/CAM_PAD of the view
CAM_WIDE = 1.15  # a fit looser than this stays at the full frame instead of a barely-there zoom
SPRING = (200.0, 40.0, 2.25)  # stiffness, damping, mass: Cap's zoom spring
SPRING_DT = 1 / 120


class Camera:
    """Auto zoom on a spring (Cap's constants). Presses group while they still fit one view at `scale`; a group
    zooms when it holds two or more presses, a drag, or is the only one in its run of activity. A lone press amid
    scattered ones keeps the full frame, so busy, spread-out work stays wide instead of pumping in and out; groups
    side by side in time pan from one to the next. Typing keeps the view. Regions in event space."""

    def __init__(self, gs, keys, space, scale):
        self.space = sw, sh = space
        fit = lambda grp: min(scale, *(n / max((max(v) - min(v)) * CAM_PAD, 1) for n, v in (
            (sw, [x for g in grp for _, x, _ in g["pts"]]), (sh, [y for g in grp for _, _, y in g["pts"]]))))
        groups, run, end = [], 0, None  # [presses, run]
        for g in sorted(gs, key=lambda g: g["t0"]):
            busy = max([end] + [k["t1"] for k in keys if k["t0"] < g["t0"]]) if end is not None else None
            if busy is None or g["t0"] - busy > CAM_GAP_S:
                run += 1
                groups.append([[g], run])
            elif groups[-1][1] == run and fit(groups[-1][0] + [g]) >= min(scale, fit(groups[-1][0])) - 1e-6:
                groups[-1][0].append(g)
            else:
                groups.append([[g], run])
            end = max(end or g["t1"], g["t1"])
        alone = lambda r: sum(1 for _, q in groups if q == r) == 1
        self.spans = []  # (from, to, z, cx, cy): the target while t is inside
        for i, (grp, r) in enumerate(groups):
            z = fit(grp)
            drag = len({(x, y) for g in grp for _, x, y in g["pts"]}) > 1
            if z < CAM_WIDE or not (len(grp) > 1 or drag or alone(r)):
                continue
            t1 = max([g["t1"] for g in grp] + [k["t1"] for k in keys if grp[0]["t0"] <= k["t0"]
                                                and (i + 1 == len(groups) or k["t0"] < groups[i + 1][0][0]["t0"])])
            nxt = groups[i + 1][0][0]["t0"] - CAM_LEAD_S if i + 1 < len(groups) else t1 + CAM_HOLD_S
            xs = [x for g in grp for _, x, _ in g["pts"]]
            ys = [y for g in grp for _, _, y in g["pts"]]
            self.spans.append((grp[0]["t0"] - CAM_LEAD_S, min(t1 + CAM_HOLD_S, nxt), z, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
        self.t0 = min([g["t0"] for g in gs] + [k["t0"] for k in keys], default=0) - 1
        self.reset()

    def reset(self):
        cx, cy = self.space[0] / 2, self.space[1] / 2
        self.t, self.x, self.v = self.t0, [1.0, cx, cy], [0.0, 0.0, 0.0]

    def target(self, t):
        span = next((sp for sp in self.spans if sp[0] <= t < sp[1]), None)
        return span[2:] if span else (1.0, self.x[1], self.x[2])  # zoom out where it is

    def region(self, t):
        """[x, y, w, h] shown at t, or None at full frame."""
        if t < self.t:  # the spring only runs forward: start over
            self.reset()
        k, c, m = SPRING
        while self.t < t:
            self.t += SPRING_DT
            tgt = self.target(self.t)
            if self.x[0] <= 1.0005:  # aim while still wide, so the zoom goes straight in
                self.x[1:], self.v[1:] = list(tgt[1:]), [0.0, 0.0]
            for i in range(3):
                self.v[i] += (-k * (self.x[i] - tgt[i]) - c * self.v[i]) / m * SPRING_DT
                self.x[i] += self.v[i] * SPRING_DT
        z, cx, cy = self.x
        if z <= 1.0005:
            return None
        sw, sh = self.space
        w, h = sw / z, sh / z
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
        self.f_key = font(round(22 * s), 600)
        self.f_cap, self.f_cap_n = font(round(28 * s), 600), font(round(22 * s), 600)
        self.cache = {}
        self.view = None  # (x0, y0, kx, ky): the zoom's crop box in frame pixels and its magnification

    def xy(self, x, y):
        """Event space -> output pixels, through the zoom when one is on."""
        return self.vp(x * self.sx, y * self.sy)

    def vp(self, X, Y):
        """Frame pixels -> output pixels: overlays are drawn after the zoom, so they stay sharp and their size."""
        if not self.view:
            return X, Y
        x0, y0, kx, ky = self.view
        return (X - x0) * kx, (Y - y0) * ky

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
        outside = cv2.distanceTransform(255 - m, cv2.DIST_L2, 5)  # pixels to the shape, 0 inside
        inside = cv2.distanceTransform(m, cv2.DIST_L2, 5)  # pixels to the edge, 0 outside

        def grow(w):  # mask grown (w > 0) or shrunk by w units: round corners, one-pixel soft edge
            d = w * u - outside if w > 0 else inside + w * u
            return Image.fromarray((np.clip(d + 0.5, 0, 1) * 255).astype(np.uint8))

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
                d.line([self.vp(a[0] * s, a[1] * s), self.vp(b[0] * s, b[1] * s)], fill=(*fx, int(255 * al)), width=max(1, round(w * FX * s)), joint="curve")
            ov.alpha_composite(layer)
        if traj and "glow" in traj.effects and (g := cm.glow(traj, lt, cm.anchor(x, y, heading, cm.ANCHOR_OFFSET * FX))):
            gx, gy = cm.anchor(x, y, heading, cm.ANCHOR_OFFSET * FX)  # glow sits off the body by FX x Cua's offset
            self.radial(ov, *self.vp((gx + (g[0] - gx) * FX) * s, (gy + (g[1] - gy) * FX) * s), g[2] * FX * s, fx, g[3])
        im, half = self.sprite(press_k(gs, t))
        rot = heading - cm.REST_HEADING
        since, until = track.rest(t)
        if self.style["float"] and since > 0:  # Cua's resting drift: a slow 4 s loop, a few points and degrees
            a = (since % 4) / 4 * 2 * np.pi
            x, y = x + np.sin(a) * 5 * FX * k_float(since), y + (6 * np.cos(a) - 6) * FX * k_float(since)
            rot += np.radians(2.5) * np.sin(a) * k_float(since)
        alpha = 1.0
        if self.style["idle_fade"] and since > 0:
            alpha = 1 - ease((since - self.style["idle_fade"]) / 0.4) * (1 - ease(1 - until / 0.25))
        if alpha <= 0.01:
            return
        if abs(rot) > 0.005:
            im = im.rotate(-np.degrees(rot), resample=Image.BICUBIC, center=(half, half))
        tag = self.tag()
        if alpha < 1:
            im, tag = (fade(i, alpha) if i else None for i in (im, tag))
        X, Y = self.vp(x * s, y * s)
        self.paste(ov, im, X - half, Y - half)
        if tag:
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
    def capsule(self, n, total, title, note):
        """The pill / chapter caption: a translucent dark capsule, "n/total", a hairline, the title; the note,
        when there is one, as a smaller second line."""
        key = ("capsule", n, total, title, note)
        if key not in self.cache:
            s = self.s
            probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            num = f"{n}/{total}"
            nw, tw = probe.textlength(num, font=self.f_cap_n), probe.textlength(title, font=self.f_cap)
            note = note or ""
            while note and probe.textlength(note, font=self.f_note) > 900 * s:
                note = note[:-2].rstrip() + "…" if not note.endswith("…") else note[:-2] + "…"
            pad, gap = 32 * s, 16 * s
            w = round(pad * 2 + nw + gap * 2 + max(tw, probe.textlength(note, font=self.f_note)))
            h = round((92 if note else 64) * s)
            im = Image.new("RGBA", (w, h))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([0, 0, w - 1, h - 1], radius=round(min(h / 2, 32 * s)), fill=(15, 17, 24, 170))
            cy = 32 * s
            d.text((pad, cy), num, font=self.f_cap_n, fill=(255, 255, 255, 140), anchor="lm")
            lx = pad + nw + gap
            d.line([(lx, cy - 14 * s), (lx, cy + 14 * s)], fill=(255, 255, 255, 64), width=max(1, round(2 * s)))
            d.text((lx + gap, cy), title, font=self.f_cap, fill=(255, 255, 255, 255), anchor="lm")
            if note:
                d.text((lx + gap, cy + 34 * s), note, font=self.f_note, fill=(205, 214, 228, 230), anchor="lm")
            self.cache[key] = im
        return self.cache[key]

    def callout(self, n, title, note):
        """The callout card: white, soft shadow, "STEP n" in the accent colour over the title (and the note);
        (image, shadow margin)."""
        key = ("callout", n, title, note)
        if key not in self.cache:
            s = self.s
            probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            pad, m = 28 * s, round(32 * s)
            w = round(2 * pad + max(probe.textlength(title, font=self.f_cap), probe.textlength(note or "", font=self.f_note)))
            h = round((112 if note else 84) * s)
            im = Image.new("RGBA", (w + 2 * m, h + 2 * m))
            shade = Image.new("L", im.size)
            ImageDraw.Draw(shade).rounded_rectangle([m, m + 8 * s, m + w, m + h + 8 * s], radius=round(20 * s), fill=255)
            im.paste((0, 0, 0, 255), (0, 0), shade.filter(ImageFilter.GaussianBlur(14 * s)).point(lambda v: int(v * 0.18)))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([m, m, m + w, m + h], radius=round(20 * s), fill=(255, 255, 255, 255))
            d.text((m + pad, m + 30 * s), f"STEP {n}", font=self.f_cap_n, fill=(*self.color, 255), anchor="lm")
            d.text((m + pad, m + 62 * s), title, font=self.f_cap, fill=(20, 24, 32, 255), anchor="lm")
            if note:
                d.text((m + pad, m + 92 * s), note, font=self.f_note, fill=(90, 98, 112, 255), anchor="lm")
            self.cache[key] = (im, m)
        return self.cache[key]

    def caption(self, ov, step, n, total, alpha, anchor):
        """Draw the step caption in style.caption; returns how much of the bottom edge it covers (for the key pill)."""
        s, kind = self.s, self.style["caption"]
        if kind == "callout" and anchor:
            card, m = self.callout(n, step["title"], step.get("note"))
            X, Y = self.xy(*anchor)
            w, h = card.width - 2 * m, card.height - 2 * m
            gap, edge = 40 * s, 16 * s
            # the pointer and its name tag hang below and right of the tip: try left, above, right, below
            sides = {"left": (X - gap - w, Y - h / 2), "above": (X - w / 2, Y - gap - h),
                     "right": (X + gap + 150 * s, Y - h / 2), "below": (X - w / 2, Y + gap + 60 * s)}
            fits = lambda xy: edge <= xy[0] <= self.w - edge - w and edge <= xy[1] <= self.h - edge - h
            side = next((k for k, xy in sides.items() if fits(xy)), "left")
            x, y = sides[side]
            x, y = min(max(x, edge), self.w - edge - w), min(max(y, edge), self.h - edge - h)
            card = fade(card, alpha) if alpha < 1 else card.copy()
            d, a = ImageDraw.Draw(card), int(255 * alpha)
            k = 14 * s  # the arrow, on the side facing the press
            if side in ("left", "right"):
                ax, ay = (m + w, min(max(Y - y, 24 * s), h - 24 * s) + m) if side == "left" else (m, min(max(Y - y, 24 * s), h - 24 * s) + m)
                tip = ax + (k if side == "left" else -k)
                d.polygon([(ax, ay - k), (tip, ay), (ax, ay + k)], fill=(255, 255, 255, a))
            else:
                ax, ay = min(max(X - x, 24 * s), w - 24 * s) + m, (m + h if side == "above" else m)
                tip = ay + (k if side == "above" else -k)
                d.polygon([(ax - k, ay), (ax, tip), (ax + k, ay)], fill=(255, 255, 255, a))
            self.paste(ov, card, x - m, y - m)
            return 0
        cap = self.capsule(n, total, step["title"], step.get("note"))
        if alpha < 1:
            cap = fade(cap, alpha)
        rise = (1 - ease(alpha)) * 12 * s  # slides up as it fades in
        if kind == "chapter":
            self.paste(ov, cap, 28 * s, 24 * s + rise)
            return 0
        self.paste(ov, cap, (self.w - cap.width) / 2, self.h - 40 * s - cap.height + rise)
        return cap.height + 40 * s

    def keys(self, ov, item, t, alpha, bottom):
        """The key pill, centred with its bottom edge at y = bottom: keycaps joined by +, or the text typed so far."""
        s = self.s
        d = ImageDraw.Draw(ov)
        pad, h, cap_h, gap = 12 * s, 54 * s, 38 * s, 22 * s
        if "caps" in item:
            widths = [d.textlength(c, font=self.f_key) + 28 * s for c in item["caps"]]
            w = sum(widths) + gap * (len(widths) - 1) + 2 * pad
        else:
            text = "".join(ch for ct, ch in item["chars"] if ct <= t)[-32:]  # the tail of a long text
            w = d.textlength(text, font=self.f_key) + 2 * pad + 14 * s
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
            d.text((x + pad, y + h / 2), text, font=self.f_key, fill=(255, 255, 255, int(255 * alpha)), anchor="lm")
            if int(t * 2) % 2 == 0:  # caret blinks at 1 Hz
                cx = x + pad + d.textlength(text, font=self.f_key) + 3 * s
                d.rectangle([cx, y + 14 * s, cx + 2 * s, y + h - 14 * s], fill=(255, 255, 255, int(220 * alpha)))

    def corner(self, ov, text):
        s = self.s
        d = ImageDraw.Draw(ov)
        tw = d.textlength(text, font=self.f_small)
        x, y = 10 * s, self.h - 30 * s
        d.rounded_rectangle([x, y, x + tw + 16 * s, y + 20 * s], radius=10 * s, fill=(0, 0, 0, 140))
        d.text((x + 8 * s, y + 10 * s), text, font=self.f_small, fill=(230, 230, 230, 230), anchor="lm")


class Framer:
    """Puts each frame on a background (a colour or a diagonal two-colour gradient) with padding, rounded
    corners and a soft shadow. The output grows by the padding, so the recording keeps its full size."""

    def __init__(self, w, h, stops):
        s = w / 1280
        self.px, self.py = round(w * 0.04) // 2 * 2, round(h * 0.06) // 2 * 2
        self.w, self.h = w + 2 * self.px, h + 2 * self.py
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        u = ((xx / self.w + yy / self.h) / 2)[..., None]
        a, b = np.array(stops[0], float), np.array(stops[-1], float)
        bg = a * (1 - u) + b * u
        box = Image.new("L", (self.w, self.h))
        self.r = round(14 * s)
        ImageDraw.Draw(box).rounded_rectangle([self.px, self.py + round(10 * s), self.px + w, self.py + h + round(10 * s)], radius=self.r, fill=255)
        shade = np.asarray(box.filter(ImageFilter.GaussianBlur(24 * s)), float)[..., None] / 255 * 0.35
        self.bg = (bg * (1 - shade)).astype(np.uint8)
        corner = Image.new("L", (2 * self.r, 2 * self.r))
        ImageDraw.Draw(corner).ellipse([0, 0, 2 * self.r - 1, 2 * self.r - 1], fill=255)
        self.round = np.asarray(corner.resize((self.r, self.r), Image.LANCZOS, box=(0, 0, self.r, self.r)), float)[..., None] / 255
        self.fw, self.fh = w, h

    def __call__(self, frame):
        out = self.bg.copy()
        x, y, w, h, r = self.px, self.py, self.fw, self.fh, self.r
        out[y:y + h, x:x + w] = frame
        for flip_y in (False, True):  # blend the four corners into the background
            for flip_x in (False, True):
                m = self.round[::-1 if flip_y else 1, ::-1 if flip_x else 1]
                ys = slice(y + h - r, y + h) if flip_y else slice(y, y + r)
                xs = slice(x + w - r, x + w) if flip_x else slice(x, x + r)
                out[ys, xs] = (frame[ys.start - y:ys.stop - y, xs.start - x:xs.stop - x] * m + self.bg[ys, xs] * (1 - m)).astype(np.uint8)
        return out


def k_float(since):
    """The float eases in over its first second, so the pointer leaves its press point gently."""
    return ease(since)


def fade(im, alpha):
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    return im


def blend(frame, ov):
    """Alpha-composite the RGBA overlay onto the RGB frame in place, only inside the overlay's bounding box."""
    box = ov.getbbox()
    if box:
        x0, y0, x1, y1 = box
        o = np.asarray(ov.crop(box), dtype=np.float32)
        a = o[:, :, 3:4] / 255
        frame[y0:y1, x0:x1] = (frame[y0:y1, x0:x1].astype(np.float32) * (1 - a) + o[:, :, :3] * a).astype(np.uint8)


def crop_box(region, W, H, space):
    """Region (event-space [x,y,w,h]) -> its pixel box (x0, y0, x1, y1) in a W x H frame, at least 2 px."""
    x, y, w, h = region
    x0, y0 = min(max(round(x * W / space[0]), 0), W - 2), min(max(round(y * H / space[1]), 0), H - 2)
    x1, y1 = min(max(x0 + 2, round((x + w) * W / space[0])), W), min(max(y0 + 2, round((y + h) * H / space[1])), H)
    return x0, y0, x1, y1


def zoom_frame(frame, region, space):
    """Crop `region` (event-space [x,y,w,h]) out of the frame and scale it back to the frame size."""
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = crop_box(region, W, H, space)
    return cv2.resize(frame[y0:y1, x0:x1], (W, H), interpolation=cv2.INTER_CUBIC)


# ---------------------------------------------------------------- render

def encoder_args():
    """HEVC on the GPU when a one-frame probe encode works (the -encoders list only says it was compiled in),
    else libx264. cq 24 / crf 20 keep small UI text sharp at the source's own size."""
    ok = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256", "-frames:v", "1",
                         "-c:v", "hevc_nvenc", "-f", "null", "-"], capture_output=True).returncode == 0
    return ["-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "24", "-tag:v", "hvc1"] if ok else ["-c:v", "libx264", "-crf", "20"]


IDLE_EDGE_S = 0.3  # an idle span starts and ends this far inside its quiet gap, so motion around it plays at 1x


def idle_spans(gs, keys, steps, after):
    """Wall-time spans [a, b] with nothing to follow for more than `after` seconds: no glide, press or ring
    (0.8 s before a press to 1 s after), no key pill, no step caption appearing (its first 1.5 s)."""
    busy = sorted([(g["t0"] - 0.8, g["t1"] + 1.0) for g in gs] + [(k["t0"] - 0.3, k["t1"]) for k in keys]
                  + [(st["from"] - 0.3, st["from"] + 1.5) for st in steps])
    spans, end = [], -np.inf
    for a, b in busy:
        if end > -np.inf and a - end > after:
            spans.append((end + IDLE_EDGE_S, a - IDLE_EDGE_S))
        end = max(end, b)
    return spans


def read_frames(pipe, size):
    """Frames of `size` bytes from a pipe, read ahead on a thread so decoding overlaps drawing."""
    q = Queue(maxsize=8)

    def run():
        while (buf := pipe.read(size)) and len(buf) == size:
            q.put(buf)
        q.put(None)

    Thread(target=run, daemon=True).start()
    return iter(q.get, None)


class FrameWriter:
    """Writes frames to a pipe on a thread so encoding overlaps drawing; a dead encoder is reported by close()."""

    def __init__(self, pipe):
        self.pipe, self.q, self.error = pipe, Queue(maxsize=8), None
        self.thread = Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while (b := self.q.get()) is not None:
            if self.error is None:
                try:
                    self.pipe.write(b)
                except OSError as e:  # keep draining so put() never blocks forever
                    self.error = e
        self.pipe.close()

    def write(self, b):
        self.q.put(b)

    def close(self):
        self.q.put(None)
        self.thread.join()
        return self.error


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
    keys = key_items(doc["events"], args.offset)
    pointer = doc.get("pointer", "touch")
    style = load_style(doc)
    if pointer not in POINTERS:
        sys.exit(f"events: pointer must be one of {', '.join(POINTERS)}, got {pointer!r}")
    steps = load_steps(args.steps) if args.steps else []
    for st in steps:
        st["anchor"] = step_anchor(st, gs)
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
    print(f"[annotate] {len(gs)} gestures, {len(keys)} key pills, {len(steps)} steps, {len(masks)} masks, clip {ss:.1f}+{dur:.1f}s", flush=True)
    spans = mask_spans(args.video, ss, dur, masks, mspace) if masks else []
    paint = Painter(W, H, space, pick_font(args.font), style)
    track = paint.track(gs) if pointer == "mouse" and gs else None
    cam = Camera(gs, keys, space, style["zoom"]) if style["zoom"] > 1 else None
    want = frame_indices(args.frames.split(","), start, ss, fps, int(dur * fps)) if args.frames else set()
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", args.video,
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    framer = Framer(W, H, style["frame"]) if style["frame"] else None
    OW, OH = (framer.w, framer.h) if framer else (W, H)
    enc = None if args.no_video else subprocess.Popen(  # the crop keeps both sides even, as 4:2:0 needs
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-r", f"{num}/{den}",
         "-i", "-", "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2", *encoder_args(), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", args.out], stdin=subprocess.PIPE)
    n, size, gi = 0, W * H * 3, 0
    out = FrameWriter(enc.stdin) if enc else None
    fast = idle_spans(gs, keys, steps, args.idle_after) if args.idle_speed > 1 else []
    if fast:
        print(f"[annotate] {len(fast)} idle spans at {args.idle_speed}x, {sum(b - a for a, b in fast):.1f}s of wall time", flush=True)
    kept = 0
    for buf in read_frames(dec.stdout, size):
        tv = n / fps  # clip time
        t = start + ss + tv  # wall time
        span = next((sp for sp in fast if sp[0] <= t < sp[1]), None)
        if span and round((t - span[0]) * fps) % args.idle_speed and n not in want:  # dropped: skip the drawing
            n += 1
            continue
        frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        apply_masks(frame, tv, masks, spans, mspace)
        cur = step_at(steps, t)
        region = (zoom_region(cur[1], t, space) if cur else None) or (cam.region(t) if cam else None)
        paint.view = None
        if region:  # zoom the picture first, then draw on it through the zoom: overlays stay sharp
            frame = zoom_frame(frame, region, space)
            x0, y0, x1, y1 = crop_box(region, W, H, space)
            paint.view = (x0, y0, W / (x1 - x0), H / (y1 - y0))
        ov = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(ov)
        if cur:
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
        ov = Image.new("RGBA", (W, H))  # captions stay put
        covered = 0
        if cur:
            i, step, alpha = cur
            covered = paint.caption(ov, step, i + 1, len(steps), alpha, step.get("anchor"))
        if k := key_at(keys, t):  # above a bottom caption
            paint.keys(ov, k[0], t, k[1], H - round(24 * paint.s) - (covered and covered - round(12 * paint.s)))
        paint.corner(ov, fmt(t) + (f"  ·  步驟 {cur[0] + 1}/{len(steps)}" if cur else "") + (f"  ·  快轉 {args.idle_speed}×" if span else ""))
        blend(frame, ov)
        if framer:
            frame = framer(frame)
        if n in want:
            png = Path(args.out).with_name(f"{Path(args.out).stem}_{fmt(t, 3).replace(':', '')}.png")
            Image.fromarray(frame).save(png)
            print(f"[annotate] frame {png}", flush=True)
        if out and not (span and round((t - span[0]) * fps) % args.idle_speed):
            out.write(frame.tobytes())
            kept += 1
        n += 1
        if n % 1800 == 0:
            print(f"[annotate] {n} frames ({tv:.0f}s)", flush=True)
    if out:
        out.close()
        enc.wait()
    dec.wait()
    if n == 0 or dec.returncode or (enc and enc.returncode):
        sys.exit(f"no output: ffmpeg decode rc {dec.returncode}, encode rc {enc.returncode if enc else '-'}, {n} frames "
                 f"(check VIDEO, --from/--to and --start)")
    print(f"[annotate] done ({n} frames" + (f", {kept} written" if kept != n and not args.no_video else "") + ")"
          + ("" if args.no_video else f", wrote {args.out}"), flush=True)


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
    ap.add_argument("--idle-speed", type=int, default=1, help="play quiet stretches this many times faster (1 = off)")
    ap.add_argument("--idle-after", type=float, default=2.0, help="seconds without activity before a stretch speeds up")
    ap.add_argument("--frames")
    ap.add_argument("--font")
    ap.add_argument("--no-video", action="store_true")
    render(ap.parse_args(argv))


if __name__ == "__main__":
    main()
