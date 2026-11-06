# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Record one window with ffmpeg (Windows Graphics Capture, native size at 30 fps, HEVC) to MKV, remuxed to MP4 on stop.

uv run screenrec.py start --window TITLE_SUBSTRING --out DIR [--profile NAME] [--crop-top N] [--height N] [--cursor]
uv run screenrec.py stop   [--profile NAME]
uv run screenrec.py status [--profile NAME]

start:  find the window, refuse a missing or minimised one, warn on a black first frame or none within 10 s, then record into DIR.
        One ffmpeg captures and pipes raw frames to a second that encodes, so ending a stuck capture still ends the file.
stop:   end the capture (a detached runner sends it `q`, then kills it), let the encoder finish, remux the MKV to MP4
        with -c copy, print the file and every stretch of over STALL_S s without a new frame.
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

FPS = 30
PREFIX = "rec_"  # every file this script writes in --out starts with this
FFMPEG_IMAGE = "ffmpeg.exe"
FIRST_FRAME_S = 5  # `start` waits this long for the first captured frame before it warns
STALL_S = 10  # longer than this without a new frame is a stall: logged, and reported by `status` and `stop`
Q_WAIT_S = 3  # the runner kills a capture that has not ended this long after `q`
ENC_WAIT_S = 30  # the runner waits this long for the encoder to finish once the capture ended
END_GAP_S = 2  # `stop` warns when the last frame came this long before it, stall or not
PROGRESS_TAIL = 4096  # bytes of the -progress file progress() reads: its last blocks
NOT_DRAWING = ("the window is not redrawing (a static window, a display that is off or asleep, or an app that "
               "stopped drawing) or the capture stopped passing its repaints: gfxcapture sends a frame only on a repaint")
STUCK = "if the window is still changing, the capture is stuck: stop, then start a new recording"


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


def capture_chain(hwnd, crop_top, t0_us=None, cursor=False):
    """The filter chain up to the CPU: gfxcapture of hwnd (the mouse cursor only with `cursor`), frames downloaded as BGRA.

    gfxcapture stamps its first frame 0, however long ffmpeg took to start. With t0_us (wall clock, epoch
    microseconds) every frame is shifted by the first frame's wall time minus t0_us, so pts 0 is t0_us."""
    shift = (f",setpts=0*if(eq(N\\,0)\\,st(0\\,RTCTIME))+PTS+(ld(0)-{t0_us})/1000000/TB" if t0_us is not None else "")
    return f"gfxcapture=hwnd={hwnd}:capture_cursor={str(cursor).lower()}:max_framerate={FPS}:crop_top={crop_top}{shift},hwdownload,format=bgra"


def out_size(w, crop_top, height=0):
    """(out_w, out_h): the window minus the crop, scaled to `height` (0 = its own height), both even.
    Exits when the crop eats the window."""
    bh = w["h"] - crop_top
    if bh <= 0:
        sys.exit(f"--crop-top {crop_top} leaves nothing of a {w['h']}px-high window")
    if not height or height >= bh:  # never upscale
        return w["w"] // 2 * 2, bh // 2 * 2
    return round(w["w"] * height / bh / 2) * 2, height // 2 * 2


def size_filter(w, crop_top, ow, oh):
    """Native size: crop the odd pixel off, no resampling; otherwise scale."""
    if (ow, oh) == (w["w"] // 2 * 2, (w["h"] - crop_top) // 2 * 2):
        return f"crop={ow}:{oh}:0:0"
    return f"scale={ow}:{oh}:flags=lanczos"


# ---------------------------------------------------------------- encoder, disk

def nvenc_ok():
    """True when a one-frame hevc_nvenc encode works (the -encoders list only says it was compiled in)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256", "-frames:v", "1",
                        "-c:v", "hevc_nvenc", "-f", "null", "-"], capture_output=True)
    return r.returncode == 0


def encoder_args(choice="auto"):
    """A near-transparent intermediate (evidence-annotate re-encodes it): HEVC on the GPU, else x264 (x265 is
    too slow to record live). cq 20 measured about 6 GB an hour on a 2489x1460 game battle (VMAF 99.4); a desktop
    far less. x264 gets umh with a 64 px motion range: its default 16 px cannot follow a scrolling page and bloats it.
    x264 ultrafast keeps real time on 4 threads where veryfast fell to 19 fps on a 1440p game clip, and its final
    encode measured higher (VMAF 97.6 against 96.6), at about 57 Mbps for the intermediate."""
    if choice == "nvenc" or (choice == "auto" and nvenc_ok()):
        return ["-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "20"]
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-x264-params", "me=umh:merange=64"]


def pipeline(chain, mkv, progress_path, enc):
    """(capture, encode) commands: the first runs the lavfi `chain` and writes raw frames as NUT to stdout, the
    second reads them from stdin and encodes to `mkv`.

    ffmpeg 9 blocked on a gfxcapture that sends no frame ignores `q`, and a killed encoder leaves an MKV without its
    end. Split, only the capture blocks: killing it closes the pipe, and the encoder finishes the file at EOF,
    with the frame fps still held. -copyts on both keeps the wall-clock offset the capture stamped on the first
    frame (ffmpeg would shift it to 0), and start_time=0 repeats that frame back to the start. The capture writes
    the progress, so its frame count grows as frames arrive; the encoder holds seconds of them until more come."""
    capture = ["ffmpeg", "-v", "error", "-y", "-copyts", "-f", "lavfi", "-i", chain, "-c:v", "rawvideo",
               "-progress", str(progress_path), "-stats_period", "0.5", "-f", "nut", "pipe:1"]
    encode = ["ffmpeg", "-v", "error", "-y", "-nostdin", "-copyts", "-f", "nut", "-i", "pipe:0",
              "-vf", f"fps={FPS}:start_time=0", *enc, str(mkv)]
    return capture, encode


def prune(out_dir, keep_gb):
    """Delete the oldest recordings this script wrote (rec_<profile>_<date>_<time>.mp4) until they fit in keep_gb."""
    own = re.compile(rf"{PREFIX}(?:[\w-]+_)?\d{{8}}_\d{{6}}\.mp4")  # also rec_<date>_<time>.mp4 from before profiles
    files = sorted((p for p in out_dir.glob(f"{PREFIX}*.mp4") if own.fullmatch(p.name)), key=lambda p: p.stat().st_mtime)
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


def progress(sp):
    """Frames captured so far, from the last block of the capture's -progress file next to state file sp; 0 before
    the first frame. ffmpeg writes no block until a frame comes, then one every stats period even while the
    capture stalls, with frame= frozen. (Its out_time is no clock: with -copyts ffmpeg subtracts the pts it had at
    its first report, which comes up to a stats period after the first frame.) Only the last PROGRESS_TAIL bytes are
    read: the file grows all through the recording, and the runner reads it five times a second."""
    try:
        with sp.with_suffix(".progress").open("rb") as f:
            f.seek(max(0, f.seek(0, os.SEEK_END) - PROGRESS_TAIL))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except FileNotFoundError:
        return 0
    kv = dict(line.partition("=")[::2] for line in lines)  # the last block wins; a cut first line is never the last
    return int(kv.get("frame") or 0)


def clock(t):
    return f"{t:%H:%M:%S.%f}"[:-5]  # tenths


def track_stall(watch, frames, now):
    """Stall bookkeeping in `watch` ({"frames", "at", "stalls"}): `at` is when the capture's frame count last grew
    (the start, before any frame), `stalls` is [[from, to or None], ...] in ISO times. A stall opens after STALL_S s
    without a new frame and closes on the next one; both times are as the runner saw them, within about a second.
    Returns a line for the log when a stall opens or closes, else None."""
    stalls = watch["stalls"]
    if frames != watch["frames"]:
        watch["frames"], watch["at"] = frames, now
        if stalls and not stalls[-1][1]:
            stalls[-1][1] = now.isoformat(timespec="milliseconds")
            return f"{clock(now)} frames again"
        return None
    if (not stalls or stalls[-1][1]) and (now - watch["at"]).total_seconds() > STALL_S:
        stalls.append([watch["at"].isoformat(timespec="milliseconds"), None])
        return f"{clock(now)} no new frame since {clock(watch['at'])}"
    return None


def stall_lines(stalls, stopped):
    """One warning per stall; one still open at `stopped` ran to the end, so the clip ends where it began."""
    lines = []
    for a, b in stalls:
        a, end = datetime.fromisoformat(a), datetime.fromisoformat(b) if b else stopped
        tail = "" if b else f", until the stop: the clip ends at {clock(a)}"
        lines.append(f"warning: no new frame {clock(a)}-{clock(end)} ({(end - a).total_seconds():.0f} s){tail}; {NOT_DRAWING}")
    return lines


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
    """Read a state file. A read racing the writer's os.replace fails with a sharing violation on Windows
    (PermissionError), or with a torn read elsewhere; both are retried for about a second."""
    for i in range(10):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, PermissionError):
            if i == 9:
                raise
            time.sleep(0.1)


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
    """True while a recording of this state can still be stopped. Once ffmpeg's pid is known only ffmpeg counts:
    a stale runner pid is easily reused by another python.exe, which would block `start` and `stop` for good."""
    if st.get("ended"):
        return False
    return ffmpeg_alive(st) if st.get("ffmpeg_pid") else runner_alive(st)


# ---------------------------------------------------------------- checks

def is_black(gray_frame, floor=6.0):
    """True when the mean of a gray frame's bytes is under `floor` (0-255)."""
    return sum(gray_frame) / len(gray_frame) < floor


PROBE_BYTES = 320 * 180  # one gray frame at the probe's scale=320:180


def probe_frame(hwnd, crop_top):
    """Grab the first 320x180 gray frame (10 s limit): "ok", "black", or "none" when no frame arrives. Exits on an ffmpeg error."""
    n = PROBE_BYTES
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", capture_chain(hwnd, crop_top) + ",scale=320:180,format=gray",
                            "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, timeout=10)
    except subprocess.TimeoutExpired as e:
        # The lavfi input waits for a second frame before ffmpeg exits, and a static window sends none:
        # the first frame is already on stdout, so only a stdout shorter than a frame means no frame.
        out = e.stdout or b""
        if len(out) < n:
            return "none"
    else:
        out = r.stdout
        if len(out) < n:
            sys.exit(f"no frame from the capture (ffmpeg rc {r.returncode}): {r.stderr.decode(errors='replace').strip()[-300:]}")
    return "black" if is_black(out[:n]) else "ok"


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
    ow, oh = out_size(win, a.crop_top, a.height)
    prune(out, a.keep_gb)
    free = shutil.disk_usage(out).free / 2**30
    if free < a.min_free_gb:
        sys.exit(f"only {free:.0f} GB free in {out}")
    # A silent or black capture is no refusal: a frozen app or a sleeping display draws nothing, and the recording
    # must already be running when it draws again. Only a missing or minimised window cannot be recorded at all.
    probe = probe_frame(win["hwnd"], a.crop_top)
    if probe == "none":
        print(f"warning: no frame from the capture within 10 s; {NOT_DRAWING}. Recording anyway")
    elif probe == "black":
        print(f"warning: the test frame of {win['title']!r} is black (a black screen, or a capture that cannot see the "
              "window). Recording anyway")
    started = datetime.now()
    mkv = out / f"{PREFIX}{a.profile}_{started:%Y%m%d_%H%M%S}.mkv"
    # The encoder's fps start_time=0 repeats the first frame back to `started`, so video time = wall time - started
    chain = f"{capture_chain(win['hwnd'], a.crop_top, round(started.timestamp() * 1e6), a.cursor)},{size_filter(win, a.crop_top, ow, oh)},format=yuv420p"
    capture, encode = pipeline(chain, mkv, sp.with_suffix(".progress"), encoder_args(a.encoder))
    sp.with_suffix(".progress").unlink(missing_ok=True)  # an earlier recording's counts must not pass for this one's
    save(sp, {"capture": capture, "encode": encode, "mkv": str(mkv), "started": started.isoformat(timespec="milliseconds"),
              "window": win["title"], "size": [ow, oh], "runner_image": Path(sys.executable).name})
    pointer(a.profile).write_text(str(out), encoding="utf-8")
    flags = 0x08000000  # CREATE_NO_WINDOW: a hidden console, which ffmpeg needs to read `q` from stdin
    log = open(out / f"{PREFIX}{a.profile}.log", "a", encoding="utf-8")  # one log per profile, every recording in it
    log.write(f"{started:%Y-%m-%d %H:%M:%S} start {mkv.name}\n")
    log.flush()
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
    if probe == "none":
        return  # already warned
    for _ in range(FIRST_FRAME_S * 10):
        if progress(sp):
            return
        time.sleep(0.1)
    # Not a refusal: a static window is still recordable once it repaints.
    print(f"warning: no frame encoded within {FIRST_FRAME_S} s; {NOT_DRAWING}. The recording stays empty until it "
          "does; `status` says when frames arrive")


def end_capture(cap):
    """`q` to the capture; kill it when it does not end within Q_WAIT_S (it blocks while the window sends nothing)."""
    if cap.poll() is not None:
        return
    try:
        cap.stdin.write(b"q\n")
        cap.stdin.flush()
        cap.wait(timeout=Q_WAIT_S)
    except (OSError, subprocess.TimeoutExpired):
        cap.kill()
        cap.wait()


def run(a):
    """Detached runner: owns both ffmpegs and the capture's stdin; logs stalls; ends the capture when the stop file
    appears and waits for the encoder to finish the file."""
    sp = Path(a.state)
    stop_file = sp.with_suffix(".stop")
    stop_file.unlink(missing_ok=True)
    for _ in range(100):  # `start` records our pid first, so a liveness check never sees a gap
        if load(sp).get("runner_pid"):
            break
        time.sleep(0.05)
    else:
        sys.exit("start never recorded the runner pid; not recording")
    st = load(sp)
    cap = subprocess.Popen(st["capture"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    enc = subprocess.Popen(st["encode"], stdin=cap.stdout)
    cap.stdout.close()  # the encoder holds the only read end, so it sees EOF once the capture ends
    update(sp, ffmpeg_pid=enc.pid, capture_pid=cap.pid)
    watch = {"frames": 0, "at": datetime.fromisoformat(st["started"]), "stalls": []}
    while enc.poll() is None and not stop_file.exists():
        if line := track_stall(watch, progress(sp), datetime.now()):
            print(line, flush=True)
            update(sp, stalls=watch["stalls"])
        time.sleep(0.2)
    end_capture(cap)
    try:
        enc.wait(timeout=ENC_WAIT_S)
    except subprocess.TimeoutExpired:  # should not happen: the encoder's input has ended
        enc.kill()
        enc.wait()
    update(sp, ended=True, rc=enc.returncode, last_frame=watch["at"].isoformat(timespec="milliseconds"))


def stop(a):
    stopped = datetime.now()  # a stall still open ends here, not after the capture's `q` timed out
    sp = state_path(a.profile)
    st = load(sp)
    if not st.get("ended"):
        if runner_alive(st):
            sp.with_suffix(".stop").write_text("stop")
            budget = Q_WAIT_S + ENC_WAIT_S + 5  # the runner's worst case, and its poll
            for _ in range(budget * 5):
                time.sleep(0.2)
                if load(sp).get("ended"):
                    break
            else:
                if ffmpeg_alive(load(sp)):
                    sys.exit(f"recorder did not finish within {budget} s; encoder ffmpeg pid {st.get('ffmpeg_pid')}")
                # ffmpeg is gone and only the runner bookkeeping is stale: remux what it wrote
        elif ffmpeg_alive(st):  # the runner died but Windows ffmpeg keeps recording: end the capture, so the
            if alive(st.get("capture_pid", 0), FFMPEG_IMAGE):  # encoder finishes the file at the pipe's EOF
                kill_tree(st["capture_pid"])
            for _ in range(50):
                if not ffmpeg_alive(st):
                    break
                time.sleep(0.2)
            else:
                kill_tree(st["ffmpeg_pid"])  # the MKV stays remuxable without its end
        st = load(sp)
    mkv = Path(st["mkv"])
    if not mkv.exists() or mkv.stat().st_size == 0:
        frames = progress(sp)
        why = (f"no frame was encoded; {NOT_DRAWING}" if not frames else
               f"ffmpeg ended before it wrote any of its {frames} frames")
        for p in (sp, sp.with_suffix(".stop"), sp.with_suffix(".progress"), pointer(a.profile)):
            p.unlink(missing_ok=True)
        sys.exit(f"no recording written ({mkv}): {why}. The stale state was removed")
    mp4 = mkv.with_suffix(".mp4")
    enc = st.get("encode") or st.get("cmd", [])  # "cmd": a recording started before the capture was split off
    tag = ["-tag:v", "hvc1"] if "hevc_nvenc" in enc else []  # MKV keeps no tag; Apple players want hvc1
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mkv), "-c", "copy", *tag, "-movflags", "+faststart", str(mp4)])
    if r.returncode:
        sys.exit(f"remux failed (rc {r.returncode}); the recording is intact at {mkv}")
    mkv.unlink()
    sp.unlink()
    sp.with_suffix(".stop").unlink(missing_ok=True)
    sp.with_suffix(".progress").unlink(missing_ok=True)
    pointer(a.profile).unlink(missing_ok=True)
    print("saved", mp4)
    print("started", st["started"])
    stalls = st.get("stalls", [])
    for line in stall_lines(stalls, stopped):
        print(line)
    if st.get("last_frame") and not (stalls and not stalls[-1][1]):  # an open stall already said where the clip ends
        last = datetime.fromisoformat(st["last_frame"])
        if (gap := (stopped - last).total_seconds()) > END_GAP_S:
            print(f"warning: the clip ends at {clock(last)}, {gap:.0f} s before the stop; {NOT_DRAWING}")


def status(a):
    sp = state_path(a.profile)
    st = load(sp)
    mkv = Path(st["mkv"])
    on = not st.get("ended") and ffmpeg_alive(st)
    size = mkv.stat().st_size if mkv.exists() else 0
    now = datetime.now()
    secs = (now - datetime.fromisoformat(st["started"])).total_seconds()
    frames = progress(sp)
    print("active", on, "started", st["started"], f"elapsed {secs:.0f}s" if on else "", f"{size / 2**20:.1f} MB", mkv,
          f"frames {frames}")
    stalls = st.get("stalls", [])
    for line in stall_lines([s for s in stalls if s[1]], now):  # the open one follows
        print(line)
    if on and not frames and secs > STALL_S:
        print(f"warning: no frame yet after {secs:.0f} s; {NOT_DRAWING}")
    elif on and stalls and not stalls[-1][1]:  # the runner opened it
        since = datetime.fromisoformat(stalls[-1][0])
        print(f"warning: no new frame for {(now - since).total_seconds():.0f} s (since {clock(since)}); {NOT_DRAWING}; {STUCK}")


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
    s.add_argument("--height", type=int, default=0, help="scale to this height; 0 = the window's own (default)")
    s.add_argument("--cursor", action="store_true", help="record the mouse cursor (desktop and browser runs)")
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
