# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Record one window with ffmpeg (Windows Graphics Capture, 720p30) to MKV, remuxed to MP4 on stop.

uv run screenrec.py start --window TITLE_SUBSTRING --out DIR [--profile NAME] [--crop-top N]
uv run screenrec.py stop   [--profile NAME]
uv run screenrec.py status [--profile NAME]

start:  find the window, refuse a minimised one, refuse a black first frame or none within 10 s, then record into DIR.
stop:   end ffmpeg gracefully (a detached runner sends it `q`), remux the MKV to MP4 with -c copy, print the file.
--profile (letters, digits, _ and -) only names the state file, so two recordings can run side by side (default "default").
Needs ffmpeg 8+ (gfxcapture) on PATH. Windows only.
"""
import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

H = 720  # output height; width follows the window, rounded even
FPS = 30
PREFIX = "rec_"  # every file this script writes in --out starts with this
FFMPEG_IMAGE = "ffmpeg.exe"


# ---------------------------------------------------------------- window lookup

def set_dpi_aware():
    """Per-monitor aware v2, so GetClientRect returns physical pixels (what gfxcapture's crop_top counts) at any scaling."""
    f = ctypes.windll.user32.SetProcessDpiAwarenessContext
    f.argtypes = [ctypes.c_void_p]
    f(ctypes.c_void_p(-4))


def find_windows(substr):
    """[{hwnd, title, w, h, iconic}] of visible top-level windows whose title contains substr (case-insensitive)."""
    set_dpi_aware()
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, buf, 512)
        if buf.value and substr.lower() in buf.value.lower():
            r = wintypes.RECT()
            u.GetClientRect(hwnd, ctypes.byref(r))
            found.append({"hwnd": hwnd, "title": buf.value, "w": r.right, "h": r.bottom, "iconic": bool(u.IsIconic(hwnd))})
        return True

    u.EnumWindows(visit, 0)
    return found


def pick_window(wins, substr):
    """The largest match; exits when none matches or the pick is minimised."""
    if not wins:
        sys.exit(f"no visible window with {substr!r} in its title")
    w = max(wins, key=lambda w: w["w"] * w["h"])
    if w["iconic"] or w["w"] == 0 or w["h"] == 0:
        sys.exit(f"window {w['title']!r} is minimised: restore it first")
    return w


def capture_chain(hwnd, crop_top):
    """The filter chain up to the CPU: gfxcapture of hwnd (no cursor), frames downloaded as BGRA."""
    return f"gfxcapture=hwnd={hwnd}:capture_cursor=false:max_framerate={FPS}:crop_top={crop_top},hwdownload,format=bgra"


def out_size(w, crop_top):
    """(out_w, out_h): the window minus the crop scaled to H, even width. Exits when the crop eats the window."""
    bh = w["h"] - crop_top
    if bh <= 0:
        sys.exit(f"--crop-top {crop_top} leaves nothing of a {w['h']}px-high window")
    return round(w["w"] * H / bh / 2) * 2, H


# ---------------------------------------------------------------- encoder, disk

def nvenc_ok():
    """True when a one-frame h264_nvenc encode works (the -encoders list only says it was compiled in)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256", "-frames:v", "1",
                        "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True)
    return r.returncode == 0


def encoder_args(choice="auto"):
    return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "27"] if choice == "nvenc" or (choice == "auto" and nvenc_ok()) else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]


def prune(out_dir, keep_gb):
    """Delete the oldest recordings this script wrote (rec_<profile>_<date>_<time>.mp4) until they fit in keep_gb."""
    files = sorted(out_dir.glob(f"{PREFIX}*_????????_??????.mp4"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    while files and total > keep_gb * 2**30:
        p = files.pop(0)
        total -= p.stat().st_size
        p.unlink()
        print("pruned", p.name)


# ---------------------------------------------------------------- state

def profile_name(v):
    if not re.fullmatch(r"[\w-]+", v):
        raise argparse.ArgumentTypeError(f"{v!r}: a profile name is letters, digits, _ and - only")
    return v


def pointer(profile):
    """Temp file that tells `stop`/`status` which --out folder a profile records into."""
    return Path(tempfile.gettempdir()) / f"screenrec-{profile}.out"


def state_file(out, profile):
    return Path(out) / f"{PREFIX}{profile}.state.json"


def pointed_state(profile):
    """The state file the profile's pointer names, or None when there is no pointer or the state is gone."""
    p = pointer(profile)
    if not p.exists():
        return None
    sp = state_file(p.read_text(encoding="utf-8"), profile)
    return sp if sp.exists() else None


def state_path(profile):
    sp = pointed_state(profile)
    if not sp:
        sys.exit(f"no recording named {profile!r}: run `start` first")
    return sp


def load(path):
    """Read a state file; a torn read (the writer is mid-replace) is retried once."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        time.sleep(0.1)
        return json.loads(path.read_text(encoding="utf-8"))


def save(path, st):
    """Write a state file atomically (temp file + os.replace); retries while a reader holds the target open."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(st), encoding="utf-8")
    for i in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 19:
                raise
            time.sleep(0.05)


def update(path, **kv):
    st = load(path)
    st.update(kv)
    save(path, st)
    return st


def alive(pid, image):
    """True when process `pid` exists and runs the executable `image` (guards PID reuse and PID 0, the idle process)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return f'"{pid}"' in out


def kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def runner_alive(st):
    return alive(st.get("runner_pid", 0), st.get("runner_image", "python.exe"))


def ffmpeg_alive(st):
    return alive(st.get("ffmpeg_pid", 0), FFMPEG_IMAGE)


def running(st):
    """True while a recording of this state can still be stopped: not ended, runner or ffmpeg still alive."""
    return not st.get("ended") and (runner_alive(st) or ffmpeg_alive(st))


# ---------------------------------------------------------------- checks

def is_black(gray_frame, floor=6.0):
    """True when the mean of a gray frame's bytes is under `floor` (0-255)."""
    return sum(gray_frame) / len(gray_frame) < floor


def test_frame_black(hwnd, crop_top):
    """Grab the first 320x180 gray frame (10 s limit). Exits when none arrives; True when it is black."""
    n = 320 * 180
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", capture_chain(hwnd, crop_top) + ",scale=320:180,format=gray",
                            "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        sys.exit("no frame from the capture within 10 s: the window is not drawing, or the capture cannot see it")
    if len(r.stdout) < n:
        sys.exit(f"no frame from the capture (ffmpeg rc {r.returncode}): {r.stderr.decode(errors='replace').strip()[-300:]}")
    return is_black(r.stdout)


# ---------------------------------------------------------------- commands

def start(a):
    if sys.platform != "win32":
        sys.exit("screen-record works on Windows only")
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sp = state_file(out, a.profile)
    for prior in (sp, pointed_state(a.profile)):  # the same profile under another --out counts too
        if prior and prior.exists() and running(load(prior)):
            sys.exit(f"profile {a.profile!r} is already recording ({prior}): run `stop --profile {a.profile}`")
    win = pick_window(find_windows(a.window), a.window)
    ow, oh = out_size(win, a.crop_top)
    prune(out, a.keep_gb)
    free = shutil.disk_usage(out).free / 2**30
    if free < a.min_free_gb:
        sys.exit(f"only {free:.0f} GB free in {out}")
    if test_frame_black(win["hwnd"], a.crop_top):
        sys.exit(f"test frame of {win['title']!r} is black: the capture does not see the window")
    started = datetime.now()
    mkv = out / f"{PREFIX}{a.profile}_{started:%Y%m%d_%H%M%S}.mkv"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
           f"{capture_chain(win['hwnd'], a.crop_top)},scale={ow}:{oh},fps={FPS},format=yuv420p",
           *encoder_args(a.encoder), str(mkv)]
    save(sp, {"cmd": cmd, "mkv": str(mkv), "started": started.isoformat(timespec="milliseconds"),
              "window": win["title"], "size": [ow, oh], "runner_image": Path(sys.executable).name})
    pointer(a.profile).write_text(str(out), encoding="utf-8")
    flags = 0x08000000  # CREATE_NO_WINDOW: a hidden console, which ffmpeg needs to read `q` from stdin
    log = open(out / f"{PREFIX}{a.profile}.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, __file__, "_run", str(sp)], creationflags=flags, stdout=log, stderr=log,
                            stdin=subprocess.DEVNULL, close_fds=True)
    update(sp, runner_pid=proc.pid)  # the runner waits for this before it starts ffmpeg
    for _ in range(100):  # the runner writes ffmpeg_pid once ffmpeg is up
        time.sleep(0.1)
        if load(sp).get("ffmpeg_pid") or proc.poll() is not None:
            break
    if not load(sp).get("ffmpeg_pid"):
        kill_tree(proc.pid)  # a slow runner must not start recording after we gave up
        if pid := load(sp).get("ffmpeg_pid"):
            kill_tree(pid)
        sys.exit(f"recorder did not start; see {log.name}")
    time.sleep(1)
    if load(sp).get("ended"):
        sys.exit(f"ffmpeg exited at once; see {log.name}")
    print(f"window {win['title']!r} {win['w']}x{win['h']} -> {ow}x{oh}")
    print(f"recording since {started:%H:%M:%S.%f}"[:-3] + f" -> {mkv}")


def run(a):
    """Detached runner: owns ffmpeg and its stdin, sends `q` when the stop file appears."""
    sp = Path(a.state)
    stop_file = sp.with_suffix(".stop")
    stop_file.unlink(missing_ok=True)
    for _ in range(100):  # `start` records our pid first, so a liveness check never sees a gap
        if load(sp).get("runner_pid"):
            break
        time.sleep(0.05)
    else:
        sys.exit("start never recorded the runner pid; not recording")
    p = subprocess.Popen(load(sp)["cmd"], stdin=subprocess.PIPE)
    update(sp, ffmpeg_pid=p.pid)
    while p.poll() is None:
        if stop_file.exists():
            p.stdin.write(b"q\n")
            p.stdin.flush()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:  # `q` not honoured: the MKV is still remuxable
                p.kill()
                p.wait()
            break
        time.sleep(0.2)
    update(sp, ended=True, rc=p.returncode)


def stop(a):
    sp = state_path(a.profile)
    st = load(sp)
    if not st.get("ended"):
        if runner_alive(st):
            sp.with_suffix(".stop").write_text("stop")
            for _ in range(150):
                time.sleep(0.2)
                if load(sp).get("ended"):
                    break
            else:
                sys.exit(f"recorder did not finish within 30 s; ffmpeg pid {st.get('ffmpeg_pid')}")
        elif ffmpeg_alive(st):  # the runner died but Windows ffmpeg keeps recording: end it hard, the MKV survives
            kill_tree(st["ffmpeg_pid"])
            time.sleep(0.5)
        st = load(sp)
    mkv = Path(st["mkv"])
    if not mkv.exists() or mkv.stat().st_size == 0:
        sp.unlink(missing_ok=True)
        pointer(a.profile).unlink(missing_ok=True)
        sys.exit(f"no recording written ({mkv}); the stale state was removed")
    mp4 = mkv.with_suffix(".mp4")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mkv), "-c", "copy", "-movflags", "+faststart", str(mp4)])
    if r.returncode:
        sys.exit(f"remux failed (rc {r.returncode}); the recording is intact at {mkv}")
    mkv.unlink()
    sp.unlink()
    sp.with_suffix(".stop").unlink(missing_ok=True)
    pointer(a.profile).unlink(missing_ok=True)
    print("saved", mp4)
    print("started", st["started"])


def status(a):
    sp = state_path(a.profile)
    st = load(sp)
    mkv = Path(st["mkv"])
    on = not st.get("ended") and ffmpeg_alive(st)
    size = mkv.stat().st_size if mkv.exists() else 0
    secs = (datetime.now() - datetime.fromisoformat(st["started"])).total_seconds()
    print("active", on, "started", st["started"], f"elapsed {secs:.0f}s" if on else "", f"{size / 2**20:.1f} MB", mkv)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    prof = dict(type=profile_name, default="default", help="names the state file only, so two recordings can coexist")
    s = sub.add_parser("start")
    s.add_argument("--window", required=True, help="substring of the window title")
    s.add_argument("--profile", **prof)
    s.add_argument("--out", required=True, help="recording folder")
    s.add_argument("--crop-top", type=int, default=0, help="pixels cut from the top of the window (title bar)")
    s.add_argument("--keep-gb", type=float, default=20, help="recordings kept in --out; oldest deleted first")
    s.add_argument("--min-free-gb", type=float, default=30, help="refuse to start below this much free space")
    s.add_argument("--encoder", choices=["auto", "nvenc", "x264"], default="auto", help="auto = NVENC if a probe encode works")
    s.set_defaults(fn=start)
    for name, fn in (("stop", stop), ("status", status)):
        p = sub.add_parser(name)
        p.add_argument("--profile", **prof)
        p.set_defaults(fn=fn)
    r = sub.add_parser("_run")
    r.add_argument("state")
    r.set_defaults(fn=run)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
