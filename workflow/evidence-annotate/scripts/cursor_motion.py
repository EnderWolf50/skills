"""Agent cursor motion: three of Cua Driver's motion styles, their heading, speed glow and comet trail.

A Python port of part of @trycua/cursor-motion (libs/typescript/cursor-motion in https://github.com/trycua/cua,
MIT licence, Copyright (c) Cua AI, Inc.), itself a port of the Rust crate cua-cursor-motion; checked against
that crate's golden trajectories (test_cursor_motion.py). Ported: the spec styles signature_arc, spring_settle
and comet_swoop with every timing mode, the tangent heading, the speed glow and the comet trail. Not ported:
magnetic, adaptive and classic (simulations), the magnet glow, reduced motion.

Units are screen points, y down; times in the plan are ms, in a Trajectory seconds. Heading is the direction
from the tip to the cursor's body: REST_HEADING (pi/4) is the resting arrow, tip up-left.
"""
import math

DT_MS = 1000 / 120  # sample period of every planned trajectory
DEFAULT_TARGET_PT = 24  # target box assumed without an element rect
REST_HEADING = math.pi / 4
TIP_ANGLE = -0.75 * math.pi  # where the tip of the resting arrow points
ANCHOR_OFFSET = 16  # tip to body along the heading, pt
DEFAULT_FIXED_MS = 1430
STYLES = ("signature_arc", "spring_settle", "comet_swoop")
FLOORS = {"relaxed": 450, "steady": 600, "calm": 750}
# trail: seconds back, full-strength length, segments, tail and head width, head alpha
TRAIL = {"secs": 0.18, "fade_len": 60, "steps": 26, "tail_width": 2, "head_width": 12, "alpha": 0.38}

EASES = {
    "linear": lambda t: t,
    "min_jerk": lambda t: t * t * t * (10 - 15 * t + 6 * t * t),
    "smootherstep": lambda t: t * t * t * (t * (6 * t - 15) + 10),
    "in_out_cubic": lambda t: 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2,
    "in_out_sine": lambda t: 0.5 - 0.5 * math.cos(math.pi * t),
    "out_cubic": lambda t: 1 - (1 - t) ** 3,
}


def wrap(a):
    """Angle into (-pi, pi], the way the TS port wraps (remainder keeps the sign of a)."""
    r = math.fmod(a, 2 * math.pi)
    if r > math.pi:
        r -= 2 * math.pi
    if r < -math.pi:
        r += 2 * math.pi
    return r


def bump(base, over, at):
    """base plus a smooth bump pushing `over` past the end, peaking at `at` (follow-through)."""
    a, b = max(at * 10, 1.5), max((1 - at) * 10, 1.5)
    peak = (a / (a + b)) ** a * (b / (a + b)) ** b
    return lambda tau: base(tau) + over * (tau ** a * (1 - tau) ** b) / peak


def wobble(base, amp, cycles, decay, start):
    """base plus a damped wobble around the end from `start` on (spring settle)."""
    def f(tau):
        if tau <= start:
            return base(tau)
        u = (tau - start) / (1 - start)
        ramp = EASES["smootherstep"](min(u / 0.18, 1))
        return base(tau) + (amp * ramp * math.exp(-decay * u) * math.sin(2 * math.pi * cycles * u) * (1 - u) ** 2
                            / max(math.exp(-decay * 0.12) * 0.77, 1e-6))
    return f


class Path:
    """The Cua cubic Bezier a -> b with an arc-length table, so a speed curve acts on distance."""

    def __init__(self, a, b, start_handle, end_handle, arc_size, arc_flow, n=256):
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = max(math.hypot(dx, dy), 1)
        px, py = -dy / ln, dx / ln
        flow = (arc_flow + 1) / 2
        c1d, c2d = ln * arc_size * (1 - 0.5 * flow), ln * arc_size * (1 - 0.5 * (1 - flow))
        self.p = [a, (a[0] + dx * start_handle + px * c1d, a[1] + dy * start_handle + py * c1d),
                  (b[0] - dx * end_handle + px * c2d, b[1] - dy * end_handle + py * c2d), b]
        pts = [self.at(i / n) for i in range(n + 1)]
        self.us = [i / n for i in range(n + 1)]
        self.ss = [0.0]
        for p, q in zip(pts, pts[1:]):
            self.ss.append(self.ss[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))
        self.length = self.ss[-1]
        self.t0 = unit(self.at(1e-3), pts[0])
        self.t1 = unit(self.at(1 - 1e-3), pts[-1])

    def at(self, u):
        v = 1 - u
        k = (v * v * v, 3 * v * v * u, 3 * v * u * u, u * u * u)
        return sum(c * q[0] for c, q in zip(k, self.p)), sum(c * q[1] for c, q in zip(k, self.p))

    def at_fraction(self, frac):
        """The point frac of the way along by distance; extrapolates along the end tangents past 0 and 1."""
        ln = self.length
        if ln < 1e-9:
            return self.at(min(max(frac, 0), 1))
        if frac > 1:
            return self.p[3][0] + self.t1[0] * (frac - 1) * ln, self.p[3][1] + self.t1[1] * (frac - 1) * ln
        if frac < 0:
            return self.p[0][0] + self.t0[0] * -frac * ln, self.p[0][1] + self.t0[1] * -frac * ln
        target = frac * ln
        lo, hi = 0, len(self.ss) - 1
        while hi - lo > 1:
            mid = (lo + hi) >> 1
            if self.ss[mid] < target:
                lo = mid
            else:
                hi = mid
        span = (self.ss[hi] - self.ss[lo]) or 1
        return self.at(self.us[lo] + (self.us[hi] - self.us[lo]) * (target - self.ss[lo]) / span)


def unit(a, b):
    d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
    return (b[0] - a[0]) / d, (b[1] - a[1]) / d


def fitts_ms(d, w, a=150, b=120, lo=300, hi=1000):
    return min(max(a + b * math.log2(d / max(w, 4) + 1), lo), hi)


# (arc size, arc flow, ease, settle, Fitts scale) of each style; settle: ("follow", amount, max pt, at) or
# ("spring", amount, max pt, cycles, decay, start, glide end) or None
SPECS = {
    "signature_arc": (0.16, 0.15, "min_jerk", ("follow", 0.018, 8, 0.82), 1.1),
    "spring_settle": (0.12, 0.0, "min_jerk", ("spring", 0.05, 6, 1.3, 2.6, 0.55, 0.68), 1.35),
    "comet_swoop": (0.24, 0.2, "in_out_cubic", None, 1.15),
}
EFFECTS = {"signature_arc": {"glow"}, "spring_settle": {"glow"}, "comet_swoop": {"trail"}}


class Trajectory:
    """A planned move: samples (t s, x, y, heading), arrival time (tip within 1 pt of the target), effects."""

    def __init__(self, samples, arrival, effects):
        self.samples, self.arrival, self.effects = samples, arrival, effects
        self.ts = [s[0] for s in samples]

    def duration(self):
        return self.samples[-1][0]

    def sample_at(self, t):
        """(t, x, y, heading) at t seconds, clamped to the ends; heading interpolates the short way."""
        if t <= self.samples[0][0]:
            return self.samples[0]
        if t >= self.samples[-1][0]:
            return self.samples[-1]
        lo, hi = 0, len(self.samples)
        while lo < hi:
            mid = (lo + hi) >> 1
            if self.samples[mid][0] <= t:
                lo = mid + 1
            else:
                hi = mid
        a, b = self.samples[lo - 1], self.samples[lo]
        f = (t - a[0]) / (b[0] - a[0])
        return t, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + wrap(b[3] - a[3]) * f

    def velocity_at(self, t):
        h = 0.008
        if t > self.duration() + h:
            return 0.0, 0.0
        a, b = self.sample_at(t - h), self.sample_at(t + h)
        return (b[1] - a[1]) / (2 * h), (b[2] - a[2]) / (2 * h)

    def scaled(self, k):
        """The same move played k times as long."""
        return Trajectory([(t * k, x, y, h) for t, x, y, h in self.samples], self.arrival * k, self.effects)


def plan(frm, to, style="signature_arc", timing="steady", target=None, arc_size=0.25, arc_flow=0.0,
         start_handle=0.3, end_handle=0.3, glide_ms=0.0, from_heading=REST_HEADING, end_heading=REST_HEADING,
         tilt=1.0, tip_angle=TIP_ANGLE, effects=None):
    """Plan one move of a built-in style. `tilt` (0..1, 1 = Cua) scales how far the tip turns toward the
    motion; `tip_angle` is where the drawn pointer's tip points at rest (Cua's arrow: TIP_ANGLE); `effects`
    ({"glow": bool, "trail": bool}) overrides the style's own."""
    known = target is not None and all(math.isfinite(v) for v in target) and target[2] > 0 and target[3] > 0
    h = DEFAULT_TARGET_PT / 2
    target = list(target) if known else [to[0] - h, to[1] - h, DEFAULT_TARGET_PT, DEFAULT_TARGET_PT]
    fixed_ms = glide_ms if glide_ms > 0 else DEFAULT_FIXED_MS
    if timing in ("native", "steady") and glide_ms > 0:  # a positive glide time fixes the default timings
        timing = "fixed"
    arc, flow, ease, settle, scale = SPECS[style]
    d, w = math.hypot(to[0] - frm[0], to[1] - frm[1]), max(min(target[2], target[3]), 4)
    ms = fitts_ms(d, w) * scale
    if timing in FLOORS:  # floor timings stretch short moves and ease them gently in and out
        ms, ease = max(ms, FLOORS[timing]), "in_out_sine"
    side = -1 if unit(frm, to)[0] >= 0 else 1  # bend upward for horizontal moves
    path = Path(frm, to, start_handle, end_handle, arc * arc_size / 0.25 * side, min(max(flow + arc_flow, -1), 1))
    f = EASES[ease]
    if settle and settle[0] == "follow":
        f = bump(f, min(settle[1], settle[2] / max(d, 1)), settle[3])
    elif settle:
        _, amount, max_pt, cycles, decay, start, glide_end = settle
        base = EASES[ease]
        f = wobble(lambda t: base(min(t / glide_end, 1)), min(amount, max_pt / max(d, 1)), cycles, decay, start)
    n = max(math.ceil(ms / DT_MS), 2)
    raw = [(i / n * ms, *path.at_fraction(f(i / n))) for i in range(n + 1)]
    raw[0], raw[-1] = (0.0, *frm), (raw[-1][0], *to)
    want = {"fixed": lambda: fixed_ms, "fitts": lambda: fitts_ms(d, min(target[2], target[3])),
            "deliberate": lambda: fitts_ms(d, min(target[2], target[3]), 400, 120, 450, 1300)}.get(timing)
    if want and len(raw) >= 3 and raw[-1][0] > 0:
        k = want() / raw[-1][0]
        raw = [(t * k, x, y) for t, x, y in raw]
    fx = {k for k in ("glow", "trail") if (effects or {}).get(k, k in EFFECTS[style])}
    return finish(raw, to, from_heading, end_heading, tilt, tip_angle, fx)


def finish(raw, to, from_heading, end_heading, tilt, tip_angle, effects):
    """Turn the tip toward the motion (eased in with speed, low-passed at 22/s), then settle back to rest."""
    n = len(raw)
    rot = wrap(from_heading - end_heading)
    samples = []
    for i in range(n):
        a, b = raw[max(i - 2, 0)], raw[min(i + 2, n - 1)]
        dt = max((b[0] - a[0]) / 1000, 1e-3)
        vx, vy = (b[1] - a[1]) / dt, (b[2] - a[2]) / dt
        w = min(max((math.hypot(vx, vy) - 40) / 260, 0), 1)
        want = wrap(math.atan2(vy, vx) - tip_angle) * w * tilt
        step = (raw[i][0] - raw[i - 1][0]) / 1000 if i else 0
        rot += wrap(want - rot) * (1 - math.exp(-step * 22))
        samples.append((raw[i][0] / 1000, raw[i][1], raw[i][2], end_heading + rot))
    end, t, dt = samples[-1], samples[-1][0], DT_MS / 1000
    for _ in range(36):
        if abs(rot) < 0.002:
            break
        t += dt
        rot -= rot * (1 - math.exp(-dt * 22))
        samples.append((t, end[1], end[2], end_heading + rot))
    samples[-1] = (*samples[-1][:3], end_heading)
    arrival = next((s[0] for s in samples if math.hypot(s[1] - to[0], s[2] - to[1]) <= 1), samples[-1][0])
    return Trajectory(samples, arrival, effects)


def anchor(x, y, heading, offset=ANCHOR_OFFSET):
    """The cursor's body point for a tip at (x, y)."""
    return x + math.cos(heading) * offset, y + math.sin(heading) * offset


def glow(traj, t, pos):
    """Speed glow (x, y, r, alpha) around the body point pos, trailing the motion, or None when slow."""
    if t >= traj.duration():
        return None
    vx, vy = traj.velocity_at(t)
    speed = math.hypot(vx, vy)
    alpha = min(speed * 0.00014, 0.42)
    if alpha <= 0.02:
        return None
    off = min(speed * 0.009, 18)
    return pos[0] - vx / speed * off, pos[1] - vy / speed * off, 30 * (1 + min(speed * 0.00024, 0.44)), alpha


def trail(traj, t, offset=ANCHOR_OFFSET):
    """Comet trail at t: [(a, b, width, alpha)] tail first, following the cursor's body (`offset` behind the tip)."""
    steps = TRAIL["steps"]
    pts = []
    for i in range(steps + 1):
        s = traj.sample_at(t - TRAIL["secs"] + TRAIL["secs"] * i / steps)
        pts.append(anchor(s[1], s[2], s[3], offset))
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
    fade = min(length / TRAIL["fade_len"], 1)
    out = []
    for i in range(1, steps + 1):
        a, b, k = pts[i - 1], pts[i], i / steps
        if math.hypot(b[0] - a[0], b[1] - a[1]) > 0.3:
            out.append((a, b, TRAIL["tail_width"] + (TRAIL["head_width"] - TRAIL["tail_width"]) * k, TRAIL["alpha"] * k * k * fade))
    return out


def lift(rgb):
    """Effect colour: the cursor fill lifted toward white."""
    return tuple(round(c + (255 - c) * 0.45) for c in rgb)
