"""Shared by annotate.py, pointer.py and text.py: wall-clock times, easing, colours, fading, fonts, and the Canvas
both drawing layers paint on."""
from PIL import ImageFont

KEYS = ("key", "type")  # the event kinds that are keys, not presses


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


def rgb(c):
    """'#rrggbb' -> (r, g, b), or None when it is not one."""
    c = str(c).lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else None
    except ValueError:
        return None


def rgba(c):
    """'#rrggbb' or '#rrggbbaa' -> (r, g, b, a), or None when it is neither."""
    c = str(c).lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in range(0, len(c), 2)) + ((255,) if len(c) == 6 else ()) if len(c) in (6, 8) else None
    except ValueError:
        return None


def ease(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def fade(im, alpha):
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    return im


def load_font(path, size, weight):
    """The font file at size px, set to weight when it is a variable font."""
    f = ImageFont.truetype(path, size)
    try:
        f.set_variation_by_axes([weight])  # variable fonts only
    except (OSError, AttributeError):
        pass
    return f


class Canvas:
    """The frame both layers draw on: w, h, the events' space and its scale (sx, sy for positions, s for sizes),
    the zoom (view), the style and a cache; annotate.Painter sets them."""

    def xy(self, x, y):
        """Event space -> output pixels, through the zoom when one is on."""
        return self.vp(x * self.sx, y * self.sy)

    def vp(self, X, Y):
        """Frame pixels -> output pixels: overlays are drawn after the zoom, so they stay sharp and their size."""
        if not self.view:
            return X, Y
        x0, y0, kx, ky = self.view
        return (X - x0) * kx, (Y - y0) * ky

    def paste(self, ov, im, x, y):
        """alpha_composite im at (x, y), clipped to the overlay."""
        x, y = round(x), round(y)
        box = (max(0, -x), max(0, -y), min(im.width, ov.width - x), min(im.height, ov.height - y))
        if box[0] < box[2] and box[1] < box[3]:
            ov.alpha_composite(im.crop(box), (x + box[0], y + box[1]))
