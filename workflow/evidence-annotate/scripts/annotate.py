# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "numpy", "opencv-python-headless"]
# ///
"""Burn touch events, step captions, boxes, zoom and privacy masks into a screen recording.

uv run annotate.py VIDEO -o OUT.mp4 --start HH:MM:SS[.fff] --events events.json \
    [--steps steps.json] [--masks masks.json] [--from T --to T] [--frames T,T,...] [--offset S]
    [--idle-speed N [--idle-after S]] [--preset NAME] [--font FILE] [--no-video]

--start   wall time of the first video frame; every other time (events, steps, --from, --to, --frames) is wall time
--events  {"space":[w,h],"pointer"?:"touch|mouse|none","style"?:{...},"events":[{"t","kind":"tap|swipe|down|up|move","x","y","x2"?,"y2"?,"ms"?}
          or {"t","kind":"key","keys":"Ctrl+S"} or {"t","kind":"type","text":"...","ms"?}]}; coordinates in
          `space`, mapped to the frame by its own size. swipe runs x,y -> x2,y2 over ms; down/up bracket a press
          (up may carry x,y = the release point); move takes the mouse pointer there without pressing
--steps   [{"from","to","title","note"? (not drawn: for the report),"boxes"?:[[x,y,w,h,"label"]],"zoom"?:[x,y,w,h]}] in the events' space
--masks   {"space":[w,h],"masks":[{"template":"a.png","threshold":0.8,"boxes":[[x,y,w,h]]}]}: a box is blacked out
          while its template matches (2 fps scan, +-1 s around each hit); template paths relative to the masks file
--blocks  {"canvas"?:{"top","bottom","left","right","color"},"space"?:[w,h],"blocks":[{...}]}: bands round the
          recording and the text blocks the project lays out itself (BLOCKS.md)
--from/--to  cut a clip; --frames also saves those annotated frames as PNG next to OUT; --no-video writes only them
--offset  calibration: seconds added to every event time before mapping to video time
--font    a CJK-capable font file (default: first of the usual Windows / Linux ones)
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from queue import Queue
from threading import Thread

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import cursor_motion as cm
from common import ease, fmt, hms, load_font, rgb
from pointer import CLICKS, COLORS, CURSOR_MOTION, CURSORS, PointerLayer, gestures, pos_at, presses, shift
from text import (CAPTIONS, CORNER, TextLayer, block_text, check_block, key_at, key_items, load_blocks, load_steps,
                  read_s, step_at, step_label)

POINTERS = ("touch", "mouse", "none")
FONTS = [  # CJK first: Windows, then Linux
    "C:/Windows/Fonts/NotoSansTC-VF.ttf", "C:/Windows/Fonts/msjh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
ZOOM_S = 0.6  # zoom ease-in / ease-out
STYLE = {"cursor": "mac", "color": None, "label": "", "label_color": None, "label_text": None, "trail": None, "motion": "signature_arc", "arc": None,
         "tilt": None, "glow": None, "click": None, "size": 0.4, "zoom": 0, "idle_fade": 0, "float": False, "frame": None, "caption": "pill", "caption_size": 18, "dot": False, "corner": True}  # events.json "style"; color None = the
# cursor's own (COLORS), arc / tilt / glow None = the cursor's own (CURSOR_MOTION); zoom and idle_fade 0 = off
PRESETS = {  # --preset: a whole look by use; events.json "style" keys override it, the cursor brings its own motion
    "evidence": {},  # bug reports, test proof: plain, nothing moves the frame
    "tutorial": {"zoom": True, "dot": True},  # steps for someone to follow
    "demo": {"cursor": "figma", "zoom": True, "float": True, "dot": True,
             "frame": ["#e0c3fc", "#8ec5fc"]},  # a showcase to share
    "agent": {"cursor": "cua", "zoom": True, "float": True, "caption": "chapter", "frame": ["#141e30", "#243b55"]},  # an AI agent at work
}
ZOOM_DEFAULT = 1.5  # "zoom": true (Cap's default for a zoom added by hand; Recordly's autozoom is 1.8)
CAM_HOLD_S = 1.0  # the camera stays in this long after a zoomed group's last action
CAM_LEAD_S = 0.6  # starts moving this long before a group's first press: the spring settles in ~0.55 s
CAM_GAP_S = 2.5  # a quieter gap than this ends a run of activity (Cap merges zooms closer than 2.5 s)
CAM_PAD = 1.4  # the framed presses fill at most 1/CAM_PAD of the view
CAM_WIDE = 1.15  # a fit looser than this stays at the full frame instead of a barely-there zoom
SPRING = (200.0, 40.0, 2.25)  # stiffness, damping, mass: Cap's zoom spring
SPRING_DT = 1 / 120
IDLE_EDGE_S = 0.3  # an idle span starts and ends this far inside its quiet gap, so motion around it plays at 1x


def load_style(doc, preset="evidence"):
    """events.json "style" over PRESETS[preset] over STYLE, checked: cursor one of CURSORS, color #rrggbb (-> RGB tuple)."""
    if preset not in PRESETS:
        sys.exit(f"--preset must be one of {', '.join(PRESETS)}, got {preset!r}")
    if not isinstance(doc.get("style", {}), dict):
        sys.exit(f"events: style must be an object, got {doc['style']!r}")
    st = {**STYLE, **PRESETS[preset], **doc.get("style", {})}
    if unknown := set(st) - set(STYLE):
        sys.exit(f"events: unknown style keys {sorted(unknown)}; known: {', '.join(STYLE)}")
    if st["cursor"] not in CURSORS:
        sys.exit(f"events: style.cursor must be one of {', '.join(CURSORS)}, got {st['cursor']!r}")
    st.update({k: v for k, v in CURSOR_MOTION[st["cursor"]].items() if st[k] is None})
    if not isinstance(st["glow"], bool):
        sys.exit(f"events: style.glow must be true or false, got {st['glow']!r}")
    if st["click"] not in CLICKS:
        sys.exit(f"events: style.click must be one of {', '.join(CLICKS)}, got {st['click']!r}")
    if st["motion"] not in cm.STYLES:
        sys.exit(f"events: style.motion must be one of {', '.join(cm.STYLES)}, got {st['motion']!r}")
    for k in ("dot", "float") + (() if st["trail"] is None else ("trail",)):
        if not isinstance(st[k], bool):
            sys.exit(f"events: style.{k} must be true or false, got {st[k]!r}")
    if not isinstance(st["label"], str):
        sys.exit(f"events: style.label must be text, got {st['label']!r}")
    if st["caption"] not in CAPTIONS:
        sys.exit(f"events: style.caption must be one of {', '.join(CAPTIONS)}, got {st['caption']!r}")
    if isinstance(st["zoom"], bool):  # true is the default magnification, false is off
        st["zoom"] = ZOOM_DEFAULT if st["zoom"] else 0
    for k, lo, hi in (("arc", 0, 1), ("tilt", 0, 1), ("size", 0.3, 2), ("zoom", 0, 4), ("idle_fade", 0, 600), ("caption_size", 8, 64)):
        if k == "tilt" and st[k] == "aim":
            continue
        if not isinstance(st[k], (int, float)) or not lo <= st[k] <= hi:
            sys.exit(f"events: style.{k} must be a number from {lo} to {hi}{' or \"aim\"' if k == 'tilt' else ''}, got {st[k]!r}")
    given, st["color"] = st["color"], rgb(st["color"] or COLORS[st["cursor"]])
    if st["color"] is None:
        sys.exit(f"events: style.color must be #rrggbb, got {given!r}")
    for k in ("label_color", "label_text"):  # None: the pointer colour; white text, Cua's dark
        if st[k] is not None and (c := rgb(st[k])) is None:
            sys.exit(f"events: style.{k} must be #rrggbb, got {st[k]!r}")
        st[k] = st[k] and c
    if st["frame"] is not None:
        stops = st["frame"] if isinstance(st["frame"], list) else [st["frame"]]
        if not 1 <= len(stops) <= 2 or None in (stops := [rgb(c) for c in stops]):
            sys.exit(f"events: style.frame must be #rrggbb or [#rrggbb, #rrggbb], got {st['frame']!r}")
        st["frame"] = stops
    if st["corner"] is True or isinstance(st["corner"], dict):  # the corner block, or its keys over the default's
        st["corner"] = check_block({**CORNER, **(st["corner"] if isinstance(st["corner"], dict) else {})}, "events: style.corner")
    elif st["corner"] is not False:
        sys.exit(f"events: style.corner must be true, false or a block's keys, got {st['corner']!r}")
    return st


def step_anchor(step, gs):
    """Where a callout points: the first press inside the step, else the centre of its first box, else None."""
    g = next((g for g in gs if step["from"] <= g["t0"] < step["to"]), None)
    if g:
        return pos_at(g, g["t0"])
    if step.get("boxes"):
        x, y, w, h, *_ = step["boxes"][0]
        return x + w / 2, y + h / 2
    return None


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
            drag = any(g["kind"] == "drag" for g in grp)
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


def zoom_region(step, t, space, base=None):
    """Region [x,y,w,h] of `space` shown at time t: eases from base (the camera's view, else the full frame) into
    step["zoom"] and back out."""
    z = step.get("zoom")
    if not z:
        return None
    p = ease(min((t - step["from"]) / ZOOM_S, (step["to"] - t) / ZOOM_S))
    full, tgt = base or (0, 0, *space), fit_region(z, space)
    return tuple(a + (b - a) * p for a, b in zip(full, tgt))


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


def pick_font(arg):
    for p in ([arg] if arg else FONTS):
        if Path(p).exists():
            return p
    sys.exit("no CJK font found: pass --font FILE")


class Painter(PointerLayer, TextLayer):
    """Draws on frames of one size: the pointer layer (pointer.py) and the text layer (text.py) share its Canvas."""

    def __init__(self, w, h, space, font_path, style=None):
        self.w, self.h, self.space = w, h, space
        self.style = style or load_style({})
        self.color = self.style["color"]
        self.sx, self.sy, self.s = w / space[0], h / space[1], w / 1280  # s scales sizes, sx/sy scale positions
        self.cache = {}
        self.view = None  # (x0, y0, kx, ky): the zoom's crop box in frame pixels and its magnification

        def font(size, weight):
            return load_font(font_path, size, weight)

        self.init_pointer(font)
        self.init_text(font)


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


def blend(frame, ov):
    """Alpha-composite the RGBA overlay onto the RGB frame in place, band by band: each run of rows with something
    drawn (runs more than 16 empty rows apart), inside that run's own box. One box round a header at the top and a
    clock at the bottom would span the whole frame."""
    a = np.asarray(ov.getchannel("A"))
    rows = np.flatnonzero(a.any(axis=1))
    if not len(rows):
        return
    cut = np.flatnonzero(np.diff(rows) > 16)
    for y0, y1 in zip(np.r_[rows[0], rows[cut + 1]], np.r_[rows[cut], rows[-1]] + 1):
        cols = np.flatnonzero(a[y0:y1].any(axis=0))
        x0, x1 = cols[0], cols[-1] + 1
        o, im = ov.crop((x0, y0, x1, y1)), Image.fromarray(frame[y0:y1, x0:x1])
        im.paste(o, (0, 0), o)  # PIL's own blend: ten times numpy's float path on a full-frame box
        frame[y0:y1, x0:x1] = np.asarray(im)


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


def encoder_args():
    """AV1, else HEVC, on the GPU when a one-frame probe encode works (the -encoders list only says it was
    compiled in), else AV1 on the CPU (libsvtav1), else libx264. On a 1440p game clip av1_nvenc cq 35 measured VMAF 98.5 at about 10 Mbps, where
    hevc_nvenc needed cq 29 for 97.5 at the same rate (AV1 plays in every browser; on Apple only from A17 Pro / M3).
    libsvtav1 preset 8 crf 35 beat x264 medium crf 24 by about 6 dB PSNR on a UI clip at the same rate, and on
    a game clip matched it at 20-35% less bitrate, at about x264 medium's speed.
    x264's default 16 px motion search cannot follow a scrolling page and bloats it about tenfold: umh with a
    64 px range can."""
    for args in (["-c:v", "av1_nvenc", "-preset", "p7", "-cq", "35"],
                 ["-c:v", "hevc_nvenc", "-preset", "p7", "-cq", "29", "-tag:v", "hvc1"],
                 ["-c:v", "libsvtav1", "-preset", "8", "-crf", "35"]):
        if subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256", "-frames:v", "1",
                           *args[:2], "-f", "null", "-"], capture_output=True).returncode == 0:
            return args
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "24", "-x264-params", "me=umh:merange=64"]


def idle_spans(gs, keys, steps, after, blocks=()):
    """Wall-time spans [a, b] with nothing to follow for more than `after` seconds: no glide, press, move or ring
    (0.8 s before one to 1 s after), no key pill, no step caption or block still being read (read_s of its words
    from its start, ending with it; a block without `from` or with `read` false never counts)."""
    busy = sorted([(g["t0"] - 0.8, g["t1"] + 1.0) for g in gs] + [(k["t0"] - 0.3, k["t1"]) for k in keys]
                  + [(st["from"] - 0.3, min(st["to"], st["from"] + read_s(st["title"]))) for st in steps]
                  + [(b["from"] - 0.3, min(np.inf if b["to"] is None else b["to"], b["from"] + read_s(block_text(b))))
                     for b in blocks if b["from"] is not None and b["read"]])
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
    items = shift(gestures(doc["events"]), args.offset)
    keys = key_items(doc["events"], args.offset)
    pointer = doc.get("pointer", "touch")
    style = load_style(doc, args.preset)
    if pointer not in POINTERS:
        sys.exit(f"events: pointer must be one of {', '.join(POINTERS)}, got {pointer!r}")
    gs = presses(items)
    if pointer != "mouse":  # a move only steers the drawn mouse pointer
        items = gs
    steps = load_steps(args.steps) if args.steps else []
    for st in steps:
        st["anchor"] = step_anchor(st, gs)
    masks, mspace = load_masks(args.masks) if args.masks else ([], space)
    canvas, blocks, bspace = load_blocks(args.blocks) if args.blocks else (None, [], None)
    bspace = parse_space({"space": bspace}, "blocks") if bspace else space
    start = hms(args.start)
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                       "stream=width,height,r_frame_rate:format=duration", "-of", "json", args.video],
                                      capture_output=True, text=True, check=True).stdout)
    st = probe["streams"][0]
    W, H = st["width"], st["height"]
    num, den = map(int, st["r_frame_rate"].split("/"))
    fps = num / den
    ss, dur = clip_bounds(start, getattr(args, "from"), args.to, float(probe["format"]["duration"]))
    print(f"[annotate] {len(gs)} gestures, {len(items) - len(gs)} moves, {len(keys)} key pills, {len(steps)} steps, "
          f"{len(blocks)} blocks, {len(masks)} masks, clip {ss:.1f}+{dur:.1f}s", flush=True)
    spans = mask_spans(args.video, ss, dur, masks, mspace) if masks else []
    paint = Painter(W, H, space, pick_font(args.font), style)
    s = paint.s
    ox, oy = (round(canvas["left"] * s), round(canvas["top"] * s)) if canvas else (0, 0)
    CW, CH = (W + ox + round(canvas["right"] * s), H + oy + round(canvas["bottom"] * s)) if canvas else (W, H)
    paint.ow, paint.oh, paint.ox, paint.oy = CW, CH, ox, oy  # text goes on the recording with its bands
    covers = [b for b in blocks if b["rect"]]
    corner = [style["corner"]] if style["corner"] else []
    track = paint.track(items) if pointer == "mouse" and items else None
    cam = Camera(gs, keys, space, style["zoom"]) if style["zoom"] > 1 else None
    want = frame_indices(args.frames.split(","), start, ss, fps, int(dur * fps)) if args.frames else set()
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", args.video,
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    framer = Framer(CW, CH, style["frame"]) if style["frame"] else None
    OW, OH = (framer.w, framer.h) if framer else (CW, CH)
    enc = None if args.no_video else subprocess.Popen(  # the crop keeps both sides even, as 4:2:0 needs
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-r", f"{num}/{den}",
         "-i", "-", "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2", *encoder_args(), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", args.out], stdin=subprocess.PIPE,
        env={**os.environ, "SVT_LOG": "1"})  # libsvtav1 prints its banner past -v error unless told
    n, size, gi = 0, W * H * 3, 0
    out = FrameWriter(enc.stdin) if enc else None
    fast = idle_spans(items, keys, steps, args.idle_after, blocks) if args.idle_speed > 1 else []
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
        view = cam.region(t) if cam else None
        region = (zoom_region(cur[1], t, space, view) if cur else None) or view
        paint.view = None
        if region:  # zoom the picture first, then draw on it through the zoom: overlays stay sharp
            frame = zoom_frame(frame, region, space)
            x0, y0, x1, y1 = crop_box(region, W, H, space)
            paint.view = (x0, y0, W / (x1 - x0), H / (y1 - y0))
        ov = Image.new("RGBA", (W, H))
        d = ImageDraw.Draw(ov)
        tokens = {"clock": fmt(t), "step": step_label(steps, cur), "speed": f"快轉 {args.idle_speed}×" if span else ""}
        for blk in covers:  # under every other mark, through the zoom
            paint.cover(ov, blk, t, tokens, bspace)
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
        if canvas:
            out_frame = np.empty((CH, CW, 3), np.uint8)
            out_frame[:] = canvas["color"]
            out_frame[oy:oy + H, ox:ox + W] = frame
            frame = out_frame
        ov = Image.new("RGBA", (CW, CH))  # captions and blocks stay put
        kind = style["caption"]
        callout = cur and kind == "callout" and cur[1].get("anchor")
        cap = paint.caption_block(cur[1], cur[0] + 1, len(steps)) if cur and kind != "none" and not callout else None
        placed = paint.blocks(ov, corner + ([cap] if cap else []) + blocks, t, tokens)
        if callout:
            paint.callout(ov, cur[1], cur[0] + 1, len(steps), cur[2], cur[1]["anchor"])
        covered = CH - placed[id(cap)][1] if cap and cap["at"] == "bottom" and id(cap) in placed else 0
        if k := key_at(keys, t):  # above a bottom caption
            paint.keys(ov, k[0], t, k[1], CH - round(24 * s) - (covered and covered - round(12 * s)))
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
    ap.add_argument("--blocks")
    ap.add_argument("--from")
    ap.add_argument("--to")
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--idle-speed", type=int, default=1, help="play quiet stretches this many times faster (1 = off)")
    ap.add_argument("--idle-after", type=float, default=2.0, help="seconds without activity before a stretch speeds up")
    ap.add_argument("--preset", default="evidence", help=f"the look: {', '.join(PRESETS)}; events.json style overrides it")
    ap.add_argument("--frames")
    ap.add_argument("--font")
    ap.add_argument("--no-video", action="store_true")
    render(ap.parse_args(argv))


if __name__ == "__main__":
    main()
