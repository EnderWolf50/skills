"""The drawn pointer: presses and moves from the events (gestures), the mouse pointer's track between them, and
PointerLayer, which draws the pointer, its name tag, the press marks, drag trails and the touch dot."""
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import cursor_motion as cm
from common import KEYS, Canvas, ease, fade, hms

HOLD_S = 0.3  # a press without movement longer than this is a hold
FLOAT_AMP = 0.5  # style.float drift, x Cua's own: ours is drawn larger on a smaller frame
RING_S = 0.4  # click ring: grows and fades after a press (and a drag's or hold's release), never before; CleanShot X's
# lasts about this long
PRESS_S = 0.08  # pointer shrinks to PRESS_K over this long before a press (ease-out), as Figma's snaps down
RELEASE_S = 0.3  # and springs back over this long after the release (back-out, a 2.5 % overshoot)
PRESS_K = 0.8
MARK_SIZE = 0.6  # the style.size at which the touch dot is 22 px in radius and the click ring grows to RING_R (at
# 1280 wide); they and the drag trail follow size from there
RING_R = 60  # px: about 1.5 times the arrow's height, as CleanShot X's click ring grows to
CURSOR_MOTION = {"cua": {"arc": 0.25, "tilt": 1.0, "glow": True, "click": "sparks"},  # Cua's own swing; an upright arrow reads calmer
                 "mac": {"arc": 0.1, "tilt": 0.0, "glow": False, "click": "shrink"},
                 "figma": {"arc": 0.1, "tilt": "aim", "glow": False, "click": "shrink"}}
CLICKS = {"ring": PRESS_K, "shrink": 0.75, "sparks": 1.0}  # the mouse pointer's press mark -> its scale while pressed: a
# ring, Figma's shrink (no ring, about 0.75), Cua's sparks off the tip (no shrink); touch and none always ring
SPARK_S = 0.25
CURSORS = ("mac", "cua", "figma")
COLORS = {"mac": "#4785ff", "cua": "#5ec0e8", "figma": "#4785ff"}
TAG = {  # name tag at style.size 1, px at 1280 wide: its top-left off the tip at rest; traced off Figma's (at the
    # arrow's corner) and Cua's (beside the arrow, rounder and glowing, dark text)
    "figma": {"at": (58, 60), "glow": False}, "cua": {"at": (46, 33), "glow": True}, "mac": {"at": (36, 52), "glow": False}}
TAG_H = 64  # name tag height, the same for every cursor
TAG_LAG = (0.06, 48)  # the tag lags the tip by this many seconds, at most this many px: it falls back while gliding
FX = 2.5  # pointers are drawn this many times Cua's 42 pt cursor, so its glow and trail scale with them
# pointer outlines in pointer units (3.2 px at 1280 wide), tip at 0,0, and where each tip points at rest
SHAPES = {"mac": [(0, 0), (0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12.5), (12.5, 12.5)],
          "figma": [(0, 0), (4.61, 13.22), (6.24, 6.56), (12.94, 4.73)]}  # figma: fitted to the cursor image
# Figma's editor sets on its canvas: sides at 71 and 20 degrees, the notch 0.65 in, corners rounded (ROUND)
ROUND = {"figma": 0.42}  # corner radius in pointer units
TIPS = {"mac": float(np.arctan2(-1, -0.62)), "figma": float(np.arctan2(-0.713, -0.701)), "cua": cm.TIP_ANGLE}
AIM = (2 * np.pi * 1.6, 0.4)  # "tilt": "aim" swings on a spring (rad/s, damping ratio): about 25 % overshoot, as in
# Figma's own cursor animation, which turns the arrow about its tip toward a target on its right
AIM_TURN = np.radians(64)  # aimed, Figma's dart has its sides at 85 and 135 degrees (from its 20 and 71 at rest)
AIM_MIN_DX = 60  # px of a 1280-wide frame: a target closer to straight above or below keeps the current side
LEAN = (300, 1500)  # px/s of a 1280-wide frame: no lean into the motion below the first, the full tilt from the second
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


def gestures(events):
    """Gestures in event space: {"kind": tap|hold|drag|move, "t0", "t1", "pts": [(t, x, y), ...]} sorted by t0. A
    `move` while a press is held is a point on its path; any other `move` is a gesture of its own (t0 = t1): a
    point the mouse pointer glides to without pressing (presses() leaves those out).

    ponytail: one contact; a second `down` while one is open closes the first at that time."""
    out, held = [], None
    for e in sorted((e for e in events if e["kind"] not in KEYS), key=lambda e: hms(e["t"])):
        t, k = hms(e["t"]), e["kind"]
        need = {"tap": "xy", "swipe": ("x", "y", "x2", "y2"), "down": "xy", "move": "xy"}.get(k, ())
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
        elif k == "move":
            if held:
                held["pts"].append((t, e["x"], e["y"]))
            else:
                out.append({"kind": "move", "t0": t, "t1": t, "pts": [(t, e["x"], e["y"])]})
        else:
            raise ValueError(f"bad event {e}")
    if held:
        held["t1"] = max(held["t1"], held["t0"] + 0.05)
    for g in out:
        if g.get("kind") == "move":
            continue
        x0, y0 = g["pts"][0][1:]
        moved = any(abs(x - x0) > 4 or abs(y - y0) > 4 for _, x, y in g["pts"])
        g["kind"] = "drag" if moved else "hold" if g["t1"] - g["t0"] > HOLD_S else "tap"
    return sorted(out, key=lambda g: g["t0"])


def presses(gs):
    """The gestures that press (rings, the touch dot, the press shrink, the camera): all but the moves."""
    return [g for g in gs if g["kind"] != "move"]


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
    """Where a mouse pointer is: at rest on the gestures (presses and moves), gliding between them as Cua Driver
    moves its cursor (cursor_motion), arriving as each one starts. Glides are planned in 1280-wide frame pixels."""

    def __init__(self, gs, style, to_px):
        self.gs, self.to_px = gs, to_px  # to_px: event space -> 1280-wide pixels
        self.glides = []  # (start s, gesture, trajectory, glide end point)
        for prev, g in zip(gs, gs[1:]):
            a, b = to_px(*pos_at(prev, prev["t1"])), to_px(*pos_at(g, g["t0"]))
            gap = g["t0"] - prev["t1"]
            if gap < 0.02 or np.hypot(b[0] - a[0], b[1] - a[1]) < 1:
                continue
            aim = style["tilt"] == "aim"
            traj = cm.plan(a, b, style["motion"], arc_size=style["arc"], tilt=0.0 if aim else style["tilt"],
                           tip_angle=TIPS[style["cursor"]], effects={"glow": style["glow"]})
            if traj.arrival > gap:  # the log leaves less time than the move takes: play it faster
                traj = traj.scaled(gap / traj.arrival)
            self.glides.append((g["t0"] - traj.arrival, g, traj, b))
        self.moving = sorted([(st, st + tr.duration()) for st, _, tr, _ in self.glides] + [(g["t0"], g["t1"]) for g in gs])
        self.swings, side = [], 0.0  # aim: (start s, from, to) each time the next target changes side
        for st, g, tr, b in self.glides:
            dx = b[0] - tr.samples[0][1]
            to = AIM_TURN if dx > AIM_MIN_DX else 0.0 if dx < -AIM_MIN_DX else side
            if to != side:
                self.swings.append((st, self.aim(st), to))  # from where the last swing has got to
                side = to

    def aim(self, t):
        """"tilt": "aim": the arrow's turn (rad, clockwise) toward the side of its next target, on a spring."""
        w, z = AIM
        wd, rot = w * np.sqrt(1 - z * z), 0.0
        for st, a, b in self.swings:
            u = t - st
            rot = a + (b - a) * (1 - np.exp(-z * w * u) * (np.cos(wd * u) + z / np.sqrt(1 - z * z) * np.sin(wd * u))) if u > 0 else rot
        return rot

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


def lean(traj, t, heading):
    """The pointer's turn into the motion (rad): the trajectory's heading, scaled by speed between LEAN's bounds, so
    a slow or short move stays nearly upright and a fast one leans fully."""
    rot = (heading - cm.REST_HEADING + np.pi) % (2 * np.pi) - np.pi
    if traj is None:
        return rot
    return rot * ease((np.hypot(*traj.velocity_at(t)) - LEAN[0]) / (LEAN[1] - LEAN[0]))


def press_k(gs, t, k=PRESS_K):
    """Pointer scale at t: k while pressed, eased in over PRESS_S before the press, sprung back over RELEASE_S after."""
    p = 0.0
    for g in gs:  # presses never overlap, so at most one term is non-zero
        if 0 <= (u := (t - g["t0"] + PRESS_S) / PRESS_S) and t <= g["t1"]:
            p += 1 - (1 - min(u, 1)) ** 3
        elif 0 <= (v := (t - g["t1"]) / RELEASE_S) <= 1:
            p += -(1.7 + 1) * (v - 1) ** 3 - 1.7 * (v - 1) ** 2  # 1 - back-out(v): 1 at the release, dips below 0, ends at 0
    return 1 - (1 - k) * min(p, 1)  # a quick second press can catch the first's rebound


def shift(gs, offset):
    for g in gs:
        g["t0"] += offset
        g["t1"] += offset
        g["pts"] = [(t + offset, x, y) for t, x, y in g["pts"]]
    return gs


def tag_at(w, h, rot, s, at=TAG["figma"]["at"]):
    """Top-left of a w x h name tag off the tip, behind the arrow as it turns by rot (Figma's tags trail the
    arrow): its near corner at rest, its near edge's middle when the arrow points straight across."""
    a = np.arctan2(at[1], at[0]) + rot
    dx, dy = np.cos(a), np.sin(a)
    d = np.hypot(*at) * s
    # the tag switches side once the body leans past 17° off straight down (dx 0.3, about where "aim" turns it):
    # Figma's then hangs below the arrow aimed up right, its right edge a third of the gap past the tip
    side = np.clip((dx - 0.3) * 40, -1, 1)  # a 3° band: it jumps sides, never resting centred
    cx, cy = d * dx + w / 2 * side + d / 3 * max(0, -side), d * dy + h / 2 * np.clip(dy * 10, -1, 1)
    return round(cx - w / 2), round(cy - h / 2)


def k_float(since):
    """The float eases in over its first second, so the pointer leaves its press point gently."""
    return ease(since) * FLOAT_AMP


class PointerLayer(Canvas):
    """Draws the pointer and its marks (annotate.Painter mixes this layer and the text layer onto one Canvas)."""

    def init_pointer(self, font):
        """Sizes from style.size; font(size, weight) loads the CJK font."""
        s = self.s
        self.fx = FX * self.style["size"]
        self.mark_k = self.style["size"] / MARK_SIZE  # the touch dot, click ring and drag trail follow size
        self.tag_spec = TAG[self.style["cursor"]]
        self.tag_h = TAG_H * s * self.style["size"]
        self.f_tag = font(round(self.tag_h * 0.52), 700 if self.tag_spec["glow"] else 600)

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

    def sparks(self, d, X, Y, u):
        """Cua's press: three short strokes flying off the tip, away from the body, fading over SPARK_S (u 0..1)."""
        L = 62 * self.fx / FX * self.s  # the arrow's length
        a0 = TIPS[self.style["cursor"]]
        for da in (-0.7, 0, 0.7):
            v = np.array([np.cos(a0 + da), np.sin(a0 + da)])
            r0, r1 = (0.12 + 0.2 * u) * L, (0.32 + 0.12 * u) * L
            d.line([(X + v[0] * r0, Y + v[1] * r0), (X + v[0] * r1, Y + v[1] * r1)], fill=(*self.color, round(255 * (1 - u) ** 0.7)),
                   width=max(1, round(0.045 * L)))

    def ring(self, ov, X, Y, age):
        """Click ring, as CleanShot X's: from half of RING_R (at 1280 wide and size MARK_SIZE) it eases out to RING_R over
        RING_S after the press, keeping its opacity until near the end."""
        p = age / RING_S
        if 0 <= p <= 1:
            R, a = RING_R * self.s * self.mark_k, 0.8 * (1 - p ** 4)
            self.circle(ov, X, Y, R * (0.5 + 0.5 * (1 - (1 - p) ** 2)), self.color, 0.12 * a, self.color, a, 0.08 * R)

    def sprite(self, k):
        """Pointer sprite at press scale k, drawn 4x and scaled down, square with the tip at its centre (so it
        rotates about the tip): (image, half size). Look by style.cursor; cua and figma take style.color."""
        k = round(k * 50) / 50  # a dozen sizes between PRESS_K and the overshoot: each is a 4x draw and blur, so cache few
        if ("sprite", k) in self.cache:
            return self.cache[("sprite", k)]
        kind, rgb = self.style["cursor"], self.color
        if kind == "cua":  # 128-unit canvas shown 42 pt x FX x style.size, tip at (55, 30)
            u = 42 * self.fx / 128 * self.s * k * 4
            pts, tip = svg_points(CUA_PATH), (55, 30)
        else:
            u = {"mac": 3.2, "figma": 4.5}[kind] * self.fx / FX * self.s * k * 4  # both about as tall as cua's
            pts, tip = SHAPES[kind], (0, 0)
        half = round(130 * u) if kind == "cua" else round(30 * u)  # room for the shape, its glow and any rotation
        size = (2 * half, 2 * half)
        mask = Image.new("L", size)
        poly = [(half + (x - tip[0]) * u, half + (y - tip[1]) * u) for x, y in pts]
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        if r := round(ROUND.get(kind, 0) * u):  # round every corner, the notch too: close, then open
            disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
            mask = Image.fromarray(cv2.morphologyEx(cv2.morphologyEx(np.asarray(mask), cv2.MORPH_CLOSE, disc), cv2.MORPH_OPEN, disc))
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
            edge = {"mac": 1.3, "figma": 1.1}[kind]
            border = grow(edge)
            shadow = Image.new("RGBA", size, (0, 0, 0))
            a, blur = {"mac": (0.3, 4), "figma": (0.35, 3)}[kind]
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
        if "tag" not in self.cache:  # (image, margin round the body left for Cua's glow)
            h = round(self.tag_h)
            tw = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(self.style["label"], font=self.f_tag)
            w, m = round(tw + 0.64 * h), round(0.3 * h)
            r = round((0.3 if self.tag_spec["glow"] else 0.1) * h)  # Cua's rounder, Figma's squarer
            im = Image.new("RGBA", (w + 2 * m, h + 2 * m))
            body = [m, m, m + w - 1, m + h - 1]
            fill = self.style["label_color"] or self.color
            text = (*(self.style["label_text"] or (255, 255, 255)), 255)
            if self.tag_spec["glow"]:  # Cua's: a soft glow in the colour, dark text
                glow = Image.new("RGBA", im.size)
                ImageDraw.Draw(glow).rounded_rectangle(body, radius=r, fill=(*fill, 140))
                im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(0.12 * h)))
                ImageDraw.Draw(im).rounded_rectangle(body, radius=r, fill=(*fill, 255))
                text = (*(self.style["label_text"] or [round(c * 0.18) for c in fill]), 255)
            else:
                ImageDraw.Draw(im).rounded_rectangle(body, radius=r, fill=(*fill, 255))
            ImageDraw.Draw(im).text((m + w / 2, m + h / 2), self.style["label"], font=self.f_tag, fill=text, anchor="mm")
            self.cache["tag"] = (im, m)
        return self.cache["tag"]

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
        s, lit = self.s, cm.lift(self.color)
        x, y, heading, traj, lt = track.at(t)
        if traj and "trail" in traj.effects:
            layer = Image.new("RGBA", (self.w, self.h))
            d = ImageDraw.Draw(layer)
            for a, b, w, al in cm.trail(traj, lt, cm.ANCHOR_OFFSET * self.fx):
                d.line([self.vp(a[0] * s, a[1] * s), self.vp(b[0] * s, b[1] * s)], fill=(*lit, int(255 * al)), width=max(1, round(w * self.fx * s)), joint="curve")
            ov.alpha_composite(layer)
        gx, gy = cm.anchor(x, y, heading, cm.ANCHOR_OFFSET * self.fx)  # glow sits off the body, scaled as the pointer
        if traj and "glow" in traj.effects and (g := cm.glow(traj, lt, (gx, gy))):
            self.radial(ov, *self.vp((gx + (g[0] - gx) * self.fx) * s, (gy + (g[1] - gy) * self.fx) * s), g[2] * self.fx * s, lit, g[3])
        im, half = self.sprite(press_k(gs, t, CLICKS[self.style["click"]]))
        rot = track.aim(t) if self.style["tilt"] == "aim" else lean(traj, lt, heading)
        since, until = track.rest(t)
        x0, y0 = x, y  # the lag below is the glide's, not the float's
        if self.style["float"] and 0 < since < np.inf:  # Cua's resting drift (not before the first move: since is inf): a slow 4 s loop, a few points and degrees
            a = (since % 4) / 4 * 2 * np.pi
            x, y = x + np.sin(a) * 5 * self.fx * k_float(since), y + (6 * np.cos(a) - 6) * self.fx * k_float(since)
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
            im, tag = fade(im, alpha), tag and (fade(tag[0], alpha), tag[1])
        X, Y = self.vp(x * s, y * s)
        self.paste(ov, im, X - half, Y - half)
        if tag:
            tag, m = tag
            tx, ty = tag_at(tag.width - 2 * m, tag.height - 2 * m, rot, s * self.fx / FX, self.tag_spec["at"])
            tx, ty = tx - m, ty - m
            lx, ly = np.subtract(self.vp(x0 * s, y0 * s), self.vp(*np.multiply(track.at(t - TAG_LAG[0])[:2], s)))
            if (m := np.hypot(lx, ly)) > TAG_LAG[1] * s:
                lx, ly = lx / m * TAG_LAG[1] * s, ly / m * TAG_LAG[1] * s
            self.paste(ov, tag, X + tx - lx, Y + ty - ly)

    def gesture(self, ov, d, g, t, pointer):
        """Rings at the press (and a drag's or hold's release), the drag trail, and for touch a fingertip dot."""
        s = self.s * self.mark_k
        t0, t1 = g["t0"], g["t1"]
        X, Y = self.xy(*pos_at(g, t))
        trail = pointer != "mouse" if self.style["trail"] is None else self.style["trail"]  # no mouse cursor draws one
        if g["kind"] == "drag" and trail and t0 <= t <= t1 + 0.5:  # trail from the start to the finger, fading after release
            a = 1 - max(0, t - t1) / 0.5
            line = [self.xy(px, py) for pt, px, py in g["pts"] if pt <= t] + [(X, Y)]
            d.line(line, fill=(*self.color, int(140 * a)), width=max(2, round(12 * s)), joint="curve")
        click = self.style["click"] if pointer == "mouse" else "ring"
        if click == "ring":
            self.ring(ov, *self.xy(*pos_at(g, t0)), t - t0)
            if g["kind"] != "tap":
                self.ring(ov, X, Y, t - t1)
        elif click == "sparks" and 0 <= t - t0 <= SPARK_S:
            self.sparks(d, *self.xy(*pos_at(g, t0)), (t - t0) / SPARK_S)
        if pointer == "touch":
            vis = max(0.0, min(1, (t1 + 0.3 - t) / 0.3))  # appears on the press itself: a finger has no hover
            if t >= t0 and vis > 0:
                self.circle(ov, X, Y, 22 * s * press_k([g], t), (255, 255, 255), 0.95 * vis, (0, 0, 0), 0.25 * vis, 4 * s)
