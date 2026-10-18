# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "numpy", "opencv-python-headless"]
# ///
"""Burn touch events, step captions, boxes, zoom and privacy masks into a screen recording.

uv run annotate.py VIDEO -o OUT.mp4 --start HH:MM:SS[.fff] --events events.json \
    [--steps steps.json] [--masks masks.json] [--from T --to T] [--frames T,T,...] [--offset S]
    [--font FILE] [--no-video]

--start   wall time of the first video frame; every other time (events, steps, --from, --to, --frames) is wall time
--events  {"space":[w,h],"events":[{"t","kind":"tap|swipe|down|up","x","y","x2"?,"y2"?,"ms"?}]}; coordinates in
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
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ACCENT = (255, 196, 64)  # amber: steps, boxes
TOUCH = (90, 200, 255)  # sky blue: taps, trails
FONTS = [  # CJK first: Windows, then Linux
    "C:/Windows/Fonts/NotoSansTC-VF.ttf", "C:/Windows/Fonts/msjh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
EMOJI = [("C:/Windows/Fonts/seguiemj.ttf", 64), ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109)]
HOLD_S = 0.3  # a press without movement longer than this is a hold
FADE_S = 0.35  # step caption and box fade
ZOOM_S = 0.6  # zoom ease-in / ease-out


# ---------------------------------------------------------------- time

def hms(s):
    """'14:30:41.2' -> seconds of the day."""
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def fmt(t):
    t = t % 86400
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:04.1f}"


# ---------------------------------------------------------------- events -> gestures

def gestures(events):
    """Gestures in event space: {"kind": tap|hold|drag, "t0", "t1", "pts": [(t, x, y), ...]} sorted by t0.

    ponytail: one contact; a second `down` while one is open closes the first at that time."""
    out, held = [], None
    for e in sorted(events, key=lambda e: hms(e["t"])):
        t, k = hms(e["t"]), e["kind"]
        if k in ("tap", "swipe"):
            d = e.get("ms", 50 if k == "tap" else 200) / 1000
            pts = [(t, e["x"], e["y"])] + ([(t + d, e["x2"], e["y2"])] if k == "swipe" else [])
            out.append({"t0": t, "t1": t + d, "pts": pts})
        elif k == "down":
            if held:
                held["t1"] = t
            held = {"t0": t, "t1": t, "pts": [(t, e["x"], e["y"])]}
            out.append(held)
        elif k == "up" and held:
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
        out.append((tpl, m.get("threshold", 0.8), m["boxes"]))
    return out, tuple(doc["space"])


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
    p.wait()
    return [merge_spans(h) for h in hits]


def apply_masks(frame, tv, masks, spans, space):
    """Black out the boxes of every mask whose span covers clip time tv."""
    H, W = frame.shape[:2]
    for (_, _, boxes), sp in zip(masks, spans):
        if any(a <= tv <= b for a, b in sp):
            for x, y, w, h in boxes:
                frame[round(y * H / space[1]):round((y + h) * H / space[1]),
                      round(x * W / space[0]):round((x + w) * W / space[0])] = 0


# ---------------------------------------------------------------- drawing

def pick_font(arg):
    for p in ([arg] if arg else FONTS):
        if Path(p).exists():
            return p
    sys.exit("no CJK font found: pass --font FILE")


class Painter:
    def __init__(self, w, h, space, font_path):
        self.w, self.h, self.space = w, h, space
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
        self.hand = self.hand_shadow = self.tip = None
        for path, px in EMOJI:
            if Path(path).exists():
                self._load_hand(path, px)
                break
        self.cache = {}

    def _load_hand(self, path, px):
        im = Image.new("RGBA", (px + 32, px + 32))
        ImageDraw.Draw(im).text((8, 4), "\U0001F446", font=ImageFont.truetype(path, px), embedded_color=True)
        hand = im.crop(im.getbbox())
        size = round(46 * self.s)
        hand = hand.resize((size, round(size * hand.height / hand.width)), Image.LANCZOS)
        a = np.array(hand)[:, :, 3]
        tip_y = int(np.argmax(a.max(1) > 128))
        self.tip = (int(np.mean(np.nonzero(a[tip_y] > 128))), tip_y)  # fingertip pixel = touch point
        shadow = Image.new("RGBA", (hand.width + 16, hand.height + 16))
        shadow.paste((0, 0, 0, 255), (8, 8), hand)
        self.hand_shadow, self.hand = shadow.filter(ImageFilter.GaussianBlur(4)), hand

    def xy(self, x, y):
        return x * self.sx, y * self.sy

    # --- touches
    def _hand(self, ov, x, y, alpha, press):
        if self.hand is None:
            return
        k = 0.88 if press else 1.0
        hand, sh = self.hand, self.hand_shadow
        if k != 1:
            hand = hand.resize((round(hand.width * k), round(hand.height * k)), Image.LANCZOS)
        px, py = round(x - self.tip[0] * k), round(y - self.tip[1] * k + (2 if press else 0))
        if alpha < 1:
            hand = hand.copy()
            hand.putalpha(hand.getchannel("A").point(lambda v: int(v * alpha)))
        sm = sh.copy()
        sm.putalpha(sh.getchannel("A").point(lambda v: int(v * 0.45 * alpha)))
        ov.alpha_composite(sm, (max(0, px - 4), max(0, py + 2)))
        ov.alpha_composite(hand, (max(0, px), max(0, py)))

    def gesture(self, ov, d, g, t):
        s = self.s
        t0, t1 = g["t0"], g["t1"]
        if not (t0 - 0.3 <= t <= t1 + 0.7):
            return
        pts = g["pts"]
        if t <= pts[0][0]:
            x, y = pts[0][1:]
        elif t >= pts[-1][0]:
            x, y = pts[-1][1:]
        else:
            i = next(i for i in range(1, len(pts)) if pts[i][0] >= t)
            (ta, xa, ya), (tb, xb, yb) = pts[i - 1], pts[i]
            u = (t - ta) / (tb - ta) if tb > ta else 1
            x, y = xa + (xb - xa) * u, ya + (yb - ya) * u
        X, Y = self.xy(x, y)
        held = t0 <= t <= t1
        fade = min(1, (t - (t0 - 0.3)) / 0.25, (t1 + 0.7 - t) / 0.35)
        if g["kind"] == "drag":  # fading trail of the last 0.9 s
            trail = [(pt, *self.xy(px, py)) for pt, px, py in pts if t - 0.9 <= pt <= t] + [(t, X, Y)]
            for (ta, xa, ya), (tb, xb, yb) in zip(trail, trail[1:]):
                a = max(0, 1 - (t - tb) / 0.9) * fade
                d.line([(xa, ya), (xb, yb)], fill=(10, 20, 40, int(120 * a)), width=max(5, round(15 * s * a)))
                d.line([(xa, ya), (xb, yb)], fill=(*TOUCH, int(240 * a)), width=max(3, round(9 * s * a)))
            sx, sy = self.xy(*pts[0][1:])
            r = 7 * s
            d.ellipse([sx - r, sy - r, sx + r, sy + r], outline=(*TOUCH, int(200 * fade)), width=max(1, round(2 * s)))
        if held:
            r = 14 * s * (1 + (0.12 * np.sin((t - t0) * 9) if g["kind"] == "hold" else 0))
            d.ellipse([X - r, Y - r, X + r, Y + r], fill=(*TOUCH, 110), outline=(255, 255, 255, 230), width=max(2, round(2.5 * s)))
        for tr, big in ((t0, True), (t1, False)) if g["kind"] != "tap" else ((t0, True),):  # press / release ripples
            p = (t - tr) / 0.55
            if 0 <= p <= 1:
                r = (12 + (48 if big else 28) * p) * s
                d.ellipse([X - r, Y - r, X + r, Y + r], outline=(*TOUCH, int(230 * (1 - p))), width=max(2, round(4 * s * (1 - p) + 1)))
        self._hand(ov, X, Y, fade, held or abs(t - t0) < 0.12)

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
    x0, y0 = round(x * W / space[0]), round(y * H / space[1])
    x1, y1 = max(x0 + 2, round((x + w) * W / space[0])), max(y0 + 2, round((y + h) * H / space[1]))
    return cv2.resize(frame[y0:y1, x0:x1], (W, H), interpolation=cv2.INTER_LINEAR)


# ---------------------------------------------------------------- render

def encoder_args():
    have = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "27"] if "h264_nvenc" in have else ["-c:v", "libx264", "-crf", "23"]


def render(args):
    doc = json.loads(Path(args.events).read_text(encoding="utf-8"))
    space = tuple(doc["space"])
    gs = shift(gestures(doc["events"]), args.offset)
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
    ss = hms(getattr(args, "from")) - start if getattr(args, "from") else 0.0
    dur = (hms(args.to) - start - ss) if args.to else float(probe["format"]["duration"]) - ss
    print(f"[annotate] {len(gs)} gestures, {len(steps)} steps, {len(masks)} masks, clip {ss:.1f}+{dur:.1f}s", flush=True)
    spans = mask_spans(args.video, ss, dur, masks, mspace) if masks else []
    paint = Painter(W, H, space, pick_font(args.font))
    want = {round((hms(f) - start - ss) * fps) for f in args.frames.split(",")} if args.frames else set()
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
            paint.gesture(ov, d, gs[j], t)
            j += 1
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
            png = Path(args.out).with_name(f"{Path(args.out).stem}_{fmt(t).replace(':', '')}.png")
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
