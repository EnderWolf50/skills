# /// script
# requires-python = ">=3.10"
# dependencies = ["obsws-python", "pillow"]
# ///
"""Record one window with OBS (NVENC, 720p30) under its own profile and scene collection.

uv run obsrec.py start --window TITLE_SUBSTRING --profile NAME --out DIR [--crop-top N]
uv run obsrec.py stop
uv run obsrec.py status

start: find the window, refuse a minimised one, write profile + scene collection NAME, launch OBS on them,
       refuse a black 1-second test frame, then record into DIR.
stop:  stop recording, print the file, quit OBS, put the user's own OBS profile back in user.ini.
Windows only (window lookup and OBS paths).
"""
import argparse
import base64
import ctypes
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from ctypes import wintypes
from pathlib import Path

APPDATA = Path(os.environ.get("APPDATA", "")) / "obs-studio"
STATE = Path(tempfile.gettempdir()) / "obsrec-state.json"  # remembers where the user's user.ini copy lives
DEFAULT_EXE = r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"
SOURCE = "capture"  # scene and source names inside the generated collection


# ---------------------------------------------------------------- window lookup

def find_windows(substr):
    """[{title, cls, exe, w, h, iconic}] of visible top-level windows whose title contains substr (case-insensitive)."""
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if not title or substr.lower() not in title.lower():
            return True
        u.GetClassNameW(hwnd, buf, 512)
        cls = buf.value
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = k.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
        exe, n = "", wintypes.DWORD(512)
        if h:
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                exe = Path(buf.value).name
            k.CloseHandle(h)
        r = wintypes.RECT()
        u.GetClientRect(hwnd, ctypes.byref(r))
        found.append({"title": title, "cls": cls, "exe": exe, "w": r.right, "h": r.bottom, "iconic": bool(u.IsIconic(hwnd))})
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


# ---------------------------------------------------------------- OBS config

def video_size(w, crop_top, out_h=720):
    """(base_w, base_h, out_w, out_h): canvas = window client area minus the crop, output scaled to out_h (even width)."""
    bw, bh = w["w"], w["h"] - crop_top
    if bh <= 0:
        sys.exit(f"--crop-top {crop_top} leaves nothing of a {w['h']}px-high window")
    ow = round(bw * out_h / bh / 2) * 2
    return bw, bh, ow, out_h


def profile_ini(name, out_dir, size):
    bw, bh, ow, oh = size
    esc = str(out_dir).replace("\\", "\\\\")
    return f"""[General]
Name={name}

[Output]
Mode=Advanced

[AdvOut]
RecType=Standard
RecFilePath={esc}
RecFormat2=hybrid_mp4
RecEncoder=obs_nvenc_h264_tex
RecTracks=1
RecSplitFile=true
RecSplitFileType=Size
RecSplitFileSize=2048
RecFileNameWithoutSpace=true

[SimpleOutput]
FilePath={esc}

[Video]
BaseCX={bw}
BaseCY={bh}
OutputCX={ow}
OutputCY={oh}
FPSType=1
FPSInt=30
ScaleType=bicubic

[Audio]
SampleRate=48000
ChannelSetup=Mono
"""


def scene_collection(name, win, crop_top, size):
    """Minimal OBS scene collection: one scene holding one window_capture of `win`, fitted to the canvas."""
    bw, bh = size[:2]
    src_id, scene_id = str(uuid.uuid4()), str(uuid.uuid4())
    common = {"prev_ver": 537001985, "mixers": 0, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5, "enabled": True,
              "muted": True, "push-to-mute": False, "push-to-mute-delay": 0, "push-to-talk": False,
              "push-to-talk-delay": 0, "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0,
              "private_settings": {}}
    item = {"name": SOURCE, "source_uuid": src_id, "visible": True, "locked": False, "rot": 0.0, "align": 5,
            "bounds_type": 2, "bounds_align": 0, "bounds_crop": False, "crop_left": 0, "crop_top": crop_top,
            "crop_right": 0, "crop_bottom": 0, "id": 1, "group_item_backup": False, "pos": {"x": 0.0, "y": 0.0},
            "scale": {"x": 1.0, "y": 1.0}, "bounds": {"x": float(bw), "y": float(bh)}, "scale_filter": "disable",
            "blend_method": "default", "blend_type": "normal", "private_settings": {}}
    return {
        "name": name,
        "sources": [
            {**common, "name": SOURCE, "uuid": src_id, "id": "window_capture", "versioned_id": "window_capture",
             "hotkeys": {}, "settings": {"window": f"{win['title']}:{win['cls']}:{win['exe']}", "priority": 2,
                                         "method": 2, "cursor": False, "client_area": True}},
            {**common, "name": name, "uuid": scene_id, "id": "scene", "versioned_id": "scene", "muted": False,
             "hotkeys": {}, "settings": {"id_counter": 1, "custom_size": False, "items": [item]}},
        ],
        "groups": [], "scene_order": [{"name": name}], "current_scene": name, "current_program_scene": name,
        "transitions": [], "quick_transitions": [],
    }


def write_config(name, out_dir, win, crop_top):
    """Create profile and scene collection `name`; every other profile and collection stays as it is."""
    size = video_size(win, crop_top)
    prof = APPDATA / "basic/profiles" / name
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "basic.ini").write_text(profile_ini(name, out_dir, size), encoding="utf-8-sig")
    scenes = APPDATA / "basic/scenes"
    scenes.mkdir(parents=True, exist_ok=True)
    (scenes / f"{name}.json").write_text(json.dumps(scene_collection(name, win, crop_top, size), indent=1), encoding="utf-8")
    return size


# ---------------------------------------------------------------- disk and process

def prune(out_dir, keep_gb):
    files = sorted(out_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    while files and total > keep_gb * 2**30:
        p = files.pop(0)
        total -= p.stat().st_size
        p.unlink()
        print("pruned", p.name)


def running():
    return "obs64.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe"], capture_output=True, text=True).stdout


def client():
    cfg = json.loads((APPDATA / "plugin_config/obs-websocket/config.json").read_text(encoding="utf-8"))
    import obsws_python as obs
    return obs.ReqClient(host="localhost", port=cfg["server_port"], password=cfg["server_password"], timeout=5)


def launch(exe, profile):
    args = ["--profile", profile, "--collection", profile, "--minimize-to-tray", "--disable-shutdown-check", "--disable-updater"]
    try:
        subprocess.Popen([exe, *args], cwd=str(Path(exe).parent))
    except OSError as e:
        if getattr(e, "winerror", 0) != 740:
            raise
        os.startfile(exe, "runas", " ".join(args), str(Path(exe).parent))  # obs64.exe is set to run as administrator


def quit_obs():
    if subprocess.run(["taskkill", "/IM", "obs64.exe"], capture_output=True).returncode:
        os.startfile("taskkill", "runas", "/IM obs64.exe")  # an elevated OBS only closes for an elevated caller
    for _ in range(20):
        if not running():
            return
        time.sleep(1)


# ---------------------------------------------------------------- checks

def is_black(png, floor=6.0):
    """True when the PNG's mean luminance is under `floor` (0-255)."""
    from PIL import Image, ImageStat
    return ImageStat.Stat(Image.open(io.BytesIO(png)).convert("L")).mean[0] < floor


def test_frame_black(c):
    time.sleep(1)
    data = c.get_source_screenshot(SOURCE, "png", 640, 360, 80).image_data
    return is_black(base64.b64decode(data.split(",", 1)[-1]))


# ---------------------------------------------------------------- commands

def start(a):
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    win = pick_window(find_windows(a.window), a.window)
    if running():
        try:
            cur = client().get_profile_list().current_profile_name
        except Exception:
            cur = None
        sys.exit(f"OBS is already running under profile {cur!r}: not touching it" if cur != a.profile
                 else f"OBS is already running under {a.profile!r}: run `status` or `stop`")
    prune(out, a.keep_gb)
    free = shutil.disk_usage(out).free / 2**30
    if free < a.min_free_gb:
        sys.exit(f"only {free:.0f} GB free in {out}")
    # OBS rewrites the last-used profile in user.ini on exit; keep the user's own copy for `stop`.
    user = APPDATA / "user.ini"
    saved = out / "user.ini.saved"
    if user.exists() and f"Profile={a.profile}\n" not in user.read_text(encoding="utf-8", errors="ignore").replace("\r", ""):
        shutil.copy(user, saved)
    STATE.write_text(json.dumps({"saved": str(saved), "exe": a.obs_exe}), encoding="utf-8")
    size = write_config(a.profile, out, win, a.crop_top)
    print(f"window {win['title']!r} {win['w']}x{win['h']}, canvas {size[0]}x{size[1]} -> {size[2]}x{size[3]}")
    launch(a.obs_exe, a.profile)
    for _ in range(60):
        try:
            c = client()
            break
        except Exception:
            time.sleep(1)
    else:
        sys.exit("OBS websocket did not come up (enable it in OBS: Tools > WebSocket Server Settings)")
    if test_frame_black(c):
        quit_obs()
        restore_user_ini()
        sys.exit(f"test frame of {win['title']!r} is black: the capture does not see the window")
    c.start_record()
    time.sleep(2)
    print("recording", c.get_record_status().output_active)


def restore_user_ini():
    if STATE.exists():
        saved = Path(json.loads(STATE.read_text(encoding="utf-8"))["saved"])
        if saved.exists():
            shutil.copy(saved, APPDATA / "user.ini")


def stop(_):
    c = client()
    print("saved", c.stop_record().output_path)
    time.sleep(2)
    quit_obs()
    restore_user_ini()


def status(_):
    s = client().get_record_status()
    print("active", s.output_active, "duration", s.output_duration)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--window", required=True, help="substring of the window title")
    s.add_argument("--profile", required=True, help="OBS profile and scene collection to create and use")
    s.add_argument("--out", required=True, help="recording folder")
    s.add_argument("--crop-top", type=int, default=0, help="pixels cut from the top of the window (title bar)")
    s.add_argument("--keep-gb", type=float, default=20, help="recordings kept in --out; oldest deleted first")
    s.add_argument("--min-free-gb", type=float, default=30, help="refuse to start below this much free space")
    s.add_argument("--obs-exe", default=DEFAULT_EXE)
    s.set_defaults(fn=start)
    sub.add_parser("stop").set_defaults(fn=stop)
    sub.add_parser("status").set_defaults(fn=status)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
