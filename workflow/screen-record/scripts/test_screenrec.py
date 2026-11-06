# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Checks for screenrec.py: window pick, output size, capture chain, black-frame test, pruning, and the
start/stop/status process handling with tasklist, taskkill and ffmpeg mocked.

uv run test_screenrec.py
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import screenrec

WIN = {"hwnd": 4242, "title": "Some App", "w": 1920, "h": 1140, "iconic": False}


def test_pick_window_takes_the_largest_match():
    small = {**WIN, "w": 100, "h": 100}
    assert screenrec.pick_window([small, WIN], "app") is WIN


def test_pick_window_refuses_none_and_minimised():
    with pytest.raises(SystemExit):
        screenrec.pick_window([], "app")
    with pytest.raises(SystemExit):
        screenrec.pick_window([{**WIN, "iconic": True}], "app")
    with pytest.raises(SystemExit):
        screenrec.pick_window([{**WIN, "w": 0, "h": 0}], "app")  # minimised windows report an empty client area


def test_out_size_keeps_the_window_size_unless_asked_and_stays_even():
    assert screenrec.out_size(WIN, 60) == (1920, 1080)
    assert screenrec.out_size({**WIN, "w": 1001, "h": 721}, 0) == (1000, 720)
    assert screenrec.out_size(WIN, 60, 720) == (1280, 720)  # 1920x1080 left -> 1280x720
    assert screenrec.out_size(WIN, 60, 4000) == (1920, 1080)  # never upscale
    assert screenrec.size_filter(WIN, 60, 1920, 1080) == "crop=1920:1080:0:0"
    assert screenrec.size_filter(WIN, 60, 1280, 720).startswith("scale=1280:720")
    with pytest.raises(SystemExit):
        screenrec.out_size(WIN, 1140)


def test_capture_chain_targets_the_hwnd_without_cursor_and_downloads_frames():
    c = screenrec.capture_chain(4242, 30)
    assert "hwnd=4242" in c and "capture_cursor=false" in c and "crop_top=30" in c
    assert c.endswith("hwdownload,format=bgra")
    assert "capture_cursor=true" in screenrec.capture_chain(4242, 0, cursor=True)


def test_capture_chain_shifts_pts_to_the_wall_clock_start():
    assert "setpts" not in screenrec.capture_chain(4242, 0)  # the black-frame probe needs no shift
    c = screenrec.capture_chain(4242, 0, 1_700_000_000_000_000)
    assert "st(0\\,RTCTIME)" in c and "ld(0)-1700000000000000" in c
    assert c.index("setpts") < c.index("hwdownload")  # stamped as captured, before the download


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_the_shift_puts_the_first_frame_at_its_wall_clock_offset():
    t0 = int(time.time() * 1e6) - 500_000  # recording started half a second before the first frame
    expr = screenrec.capture_chain(1, 0, t0).split(",setpts=")[1].split(",hwdownload")[0]
    r = subprocess.run(["ffmpeg", "-v", "info", "-f", "lavfi", "-i", "testsrc=size=32x32:rate=30", "-frames:v", "2",
                        "-vf", f"setpts={expr},showinfo", "-f", "null", "-"], capture_output=True, text=True)
    first = float(re.search(r"n:\s*0 .*?pts_time:([\d.]+)", r.stderr).group(1))
    assert 0.4 < first < 3  # not RTCTIME itself: st() returns the value it stores


def test_is_black_uses_mean_brightness():
    assert screenrec.is_black(bytes(100))
    assert not screenrec.is_black(bytes([200]) * 100)
    assert not screenrec.is_black(bytes([0] * 90 + [255] * 10))  # mean 25.5


def test_frame_probe_keeps_a_frame_written_before_the_timeout(monkeypatch):
    # gfxcapture of a window that stops repainting sends one frame; ffmpeg then waits for a second and never exits
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"], output=bytes([200]) * screenrec.PROBE_BYTES)
    monkeypatch.setattr(screenrec.subprocess, "run", run)
    assert screenrec.probe_frame(4242, 0) == "ok"


def test_frame_probe_without_any_frame_says_none(monkeypatch):
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"], output=b"")
    monkeypatch.setattr(screenrec.subprocess, "run", run)
    assert screenrec.probe_frame(4242, 0) == "none"


def test_frame_probe_names_a_black_frame(monkeypatch):
    monkeypatch.setattr(screenrec.subprocess, "run", lambda c, **kw: SimpleNamespace(stdout=bytes(screenrec.PROBE_BYTES), returncode=0, stderr=b""))
    assert screenrec.probe_frame(4242, 0) == "black"


def test_prune_deletes_only_our_oldest_mp4(tmp_path):
    mine = [tmp_path / f"rec_p_20260101_00000{i}.mp4" for i in range(3)]
    other = tmp_path / "rec_notes.mp4"  # starts with rec_ but is not one of ours
    for i, p in enumerate(mine + [other]):
        p.write_bytes(b"x" * 1024)
        os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    screenrec.prune(tmp_path, 2048 / 2**30)  # room for two files
    assert [p.exists() for p in mine] == [False, True, True] and other.exists()


def test_prune_still_counts_names_from_before_profiles(tmp_path):
    old = tmp_path / "rec_20251231_235959.mp4"  # written before files carried a profile
    new = tmp_path / "rec_p_20260101_000000.mp4"
    for i, p in enumerate((old, new)):
        p.write_bytes(b"x" * 1024)
        os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    screenrec.prune(tmp_path, 1024 / 2**30)  # room for one file
    assert not old.exists() and new.exists()


def test_load_retries_a_read_that_races_the_writer(tmp_path, monkeypatch):
    sp = tmp_path / "s.json"
    sp.write_text('{"ok": 1}', encoding="utf-8")
    real, calls = type(sp).read_text, []

    def flaky(self, *a, **k):  # Windows: reading while another process os.replace()s gives a sharing violation
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "sharing violation")
        return real(self, *a, **k)

    monkeypatch.setattr(type(sp), "read_text", flaky)
    monkeypatch.setattr(screenrec.time, "sleep", lambda s: None)
    assert screenrec.load(sp) == {"ok": 1} and len(calls) == 3


# ---------------------------------------------------------------- process handling (mocked)

@pytest.fixture
def env(tmp_path, monkeypatch):
    """A pointer inside tmp, no sleeping, and a process table the tests edit: {pid: image}."""
    procs, killed = {}, []
    monkeypatch.setattr(screenrec, "pointer", lambda profile: tmp_path / f"ptr-{profile}")
    monkeypatch.setattr(screenrec.time, "sleep", lambda s: None)
    monkeypatch.setattr(screenrec, "alive", lambda pid, image: procs.get(pid) == image)
    monkeypatch.setattr(screenrec, "kill_tree", lambda pid: (killed.append(pid), procs.pop(pid, None)))
    return SimpleNamespace(procs=procs, killed=killed, tmp=tmp_path, mp=monkeypatch)


def write_state(path, **kv):
    screenrec.save(path, {"capture": ["ffmpeg"], "encode": ["ffmpeg"], "mkv": str(path.with_suffix(".mkv")), "started": "2026-01-01T10:00:00.000",
                          "runner_image": "python.exe", **kv})


def start_args(out, profile="p"):
    return argparse.Namespace(window="app", out=str(out), profile=profile, crop_top=0, keep_gb=20, min_free_gb=0, encoder="x264", cursor=False, height=0)


def stub_start(env, popen, probe="ok", cause=None):
    m = env.mp
    m.setattr(screenrec.sys, "platform", "win32")
    m.setattr(screenrec, "find_windows", lambda s: [WIN])
    m.setattr(screenrec, "probe_frame", lambda h, c: probe)
    m.setattr(screenrec, "silent_cause", lambda h: cause)
    m.setattr(screenrec.subprocess, "Popen", popen)


def test_alive_is_false_for_pid_zero_and_checks_pid_and_image(monkeypatch):
    calls = []
    idle = '"System Idle Process","0","Services","0","8 K"\n'
    monkeypatch.setattr(screenrec.subprocess, "run", lambda c, **kw: (calls.append(c), SimpleNamespace(stdout=idle))[1])
    assert not screenrec.alive(0, "python.exe") and not screenrec.alive(-5, "python.exe") and calls == []
    monkeypatch.setattr(screenrec.subprocess, "run", lambda c, **kw: (calls.append(c), SimpleNamespace(stdout='"python.exe","123","Console","1","9 K"\n'))[1])
    assert screenrec.alive(123, "python.exe") and not screenrec.alive(12, "python.exe")
    assert "IMAGENAME eq python.exe" in calls[-1] and "PID eq 12" in calls[-1]
    monkeypatch.setattr(screenrec.subprocess, "run", lambda c, **kw: SimpleNamespace(stdout="INFO: No tasks are running which match the specified criteria.\n"))
    assert not screenrec.alive(123, "ffmpeg.exe")  # the pid now belongs to another image: tasklist filters it out


def test_save_is_atomic_and_load_retries_one_torn_read(tmp_path, monkeypatch):
    sp = tmp_path / "s.json"
    screenrec.save(sp, {"a": 1})
    assert json.loads(sp.read_text()) == {"a": 1} and not (tmp_path / "s.json.tmp").exists()
    monkeypatch.setattr(screenrec.time, "sleep", lambda s: None)
    reads = iter(['{"a": ', '{"a": 2}'])
    assert screenrec.load(SimpleNamespace(read_text=lambda encoding=None: next(reads))) == {"a": 2}
    with pytest.raises(json.JSONDecodeError):  # a second bad read is a real error
        screenrec.load(SimpleNamespace(read_text=lambda encoding=None: "{"))


def test_profile_name_rejects_path_tricks():
    assert screenrec.profile_name("run-1_a") == "run-1_a"
    for bad in ("../x", "a/b", "a\\b", "", "a.b", "a b"):
        with pytest.raises(argparse.ArgumentTypeError):
            screenrec.profile_name(bad)
    with pytest.raises(SystemExit):
        screenrec.main(["status", "--profile", "../x"])


def test_start_refuses_a_live_profile_under_another_out(env):
    a_dir, b_dir = env.tmp / "a", env.tmp / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    write_state(screenrec.state_file(a_dir, "p"), runner_pid=500, ffmpeg_pid=501)
    env.procs.update({500: "python.exe", 501: "ffmpeg.exe"})
    screenrec.pointer("p").write_text(str(a_dir))
    stub_start(env, lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(SystemExit, match="already recording"):
        screenrec.start(start_args(b_dir))
    assert screenrec.pointer("p").read_text() == str(a_dir)  # the first recording's pointer is untouched


def test_running_ignores_a_reused_pid_and_an_ended_state(env):
    d = env.tmp
    sp = screenrec.state_file(d, "p")
    # Before ffmpeg is up, the runner decides; a reused runner pid does not count.
    write_state(sp, runner_pid=500)
    env.procs[500] = "chrome.exe"
    assert not screenrec.running(screenrec.load(sp))
    env.procs[500] = "python.exe"
    assert screenrec.running(screenrec.load(sp))
    # Once ffmpeg's pid is known, only ffmpeg decides: a stale runner pid reused by another python.exe
    # must not keep the profile "recording" forever.
    write_state(sp, runner_pid=500, ffmpeg_pid=501)
    assert not screenrec.running(screenrec.load(sp))
    env.procs[501] = "ffmpeg.exe"
    assert screenrec.running(screenrec.load(sp))
    assert not screenrec.running({**screenrec.load(sp), "ended": True})
    assert not screenrec.running({"encode": []})  # a state with no pids at all (pid 0) is not "recording"


def test_start_that_gives_up_kills_the_runner_and_leaves_no_blocking_state(env):
    d = env.tmp / "a"
    proc = SimpleNamespace(pid=700, poll=lambda: None)
    env.procs[700] = "python.exe"
    stub_start(env, lambda *a, **k: proc)
    with pytest.raises(SystemExit, match="did not start"):
        screenrec.start(start_args(d))
    sp = screenrec.state_file(d.resolve(), "p")
    assert env.killed == [700]  # the slow runner is killed, not left to start recording later
    assert screenrec.load(sp)["runner_pid"] == 700  # written right after Popen
    assert not screenrec.running(screenrec.load(sp))  # so the next start is not refused
    with pytest.raises(SystemExit, match="no recording written"):  # stop on it: no KeyError on ffmpeg_pid
        screenrec.stop(argparse.Namespace(profile="p"))
    assert not sp.exists()


def test_stop_with_a_dead_runner_kills_ffmpeg_and_remuxes(env):
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    mkv = d / "rec_p_20260101_100000.mkv"
    mkv.write_bytes(b"x" * 10)
    write_state(sp, mkv=str(mkv), runner_pid=800, ffmpeg_pid=801, capture_pid=802)  # runner gone, ffmpeg still recording
    env.procs.update({801: "ffmpeg.exe", 802: "ffmpeg.exe"})
    screenrec.pointer("p").write_text(str(d))

    def kill(pid):  # the encoder reads the capture's pipe: it finishes the file once the capture is gone
        env.killed.append(pid)
        env.procs.pop(pid, None)
        if pid == 802:
            env.procs.pop(801, None)

    def fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"mp4")
        return SimpleNamespace(returncode=0)

    env.mp.setattr(screenrec, "kill_tree", kill)
    env.mp.setattr(screenrec.subprocess, "run", fake_run)
    screenrec.stop(argparse.Namespace(profile="p"))
    assert env.killed == [802]  # only the capture: killing the encoder would truncate the MKV
    assert (d / "rec_p_20260101_100000.mp4").exists() and not mkv.exists() and not sp.exists()


def test_stop_asks_a_live_runner_to_finish_instead_of_killing(env):
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    mkv = d / "rec_p_20260101_100000.mkv"
    mkv.write_bytes(b"x")
    write_state(sp, mkv=str(mkv), runner_pid=800, ffmpeg_pid=801)
    env.procs.update({800: "python.exe", 801: "ffmpeg.exe"})
    screenrec.pointer("p").write_text(str(d))

    def fake_sleep(s):  # the runner reacts to the stop file
        if sp.with_suffix(".stop").exists():
            screenrec.update(sp, ended=True)

    def fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"m")
        return SimpleNamespace(returncode=0)

    env.mp.setattr(screenrec.time, "sleep", fake_sleep)
    env.mp.setattr(screenrec.subprocess, "run", fake_run)
    screenrec.stop(argparse.Namespace(profile="p"))
    assert env.killed == [] and (d / "rec_p_20260101_100000.mp4").exists()


def test_progress_reads_the_last_block_and_is_zero_before_the_first_frame(tmp_path):
    sp = screenrec.state_file(tmp_path, "p")
    assert screenrec.progress(sp) == 0  # ffmpeg writes no block until a frame comes
    sp.with_suffix(".progress").write_text("frame=57\nout_time_us=1900000\nprogress=continue\n"
                                           "frame=86\nout_time_us=2866667\nprogress=continue\n", encoding="utf-8")
    assert screenrec.progress(sp) == 86
    sp.with_suffix(".progress").write_text("frame=0\nout_time_us=N/A\n", encoding="utf-8")
    assert screenrec.progress(sp) == 0


def test_start_warns_when_no_frame_is_encoded(env, capsys):
    d = env.tmp / "a"
    cmds = []

    def popen(cmd, **kw):  # the runner: ffmpeg comes up, but the window never repaints, so no progress block
        sp = Path(cmd[-1])
        cmds.append(screenrec.load(sp)["capture"])
        env.procs[901] = "ffmpeg.exe"
        screenrec.update(sp, ffmpeg_pid=901)
        return SimpleNamespace(pid=900, poll=lambda: None)

    stub_start(env, popen)
    screenrec.start(start_args(d))
    out = capsys.readouterr().out
    assert "recording since" in out and "warning: no frame encoded" in out and "not redrawing" in out
    assert cmds[0][cmds[0].index("-progress") + 1].endswith("rec_p.state.progress")


@pytest.mark.parametrize("probe, warning", [("none", "no frame from the capture within 10 s"), ("black", "is black")])
def test_start_records_after_a_silent_or_black_probe(env, capsys, probe, warning):
    # a frozen game or a sleeping display draws nothing: warn, and record so the clip has it once it draws again
    def popen(cmd, **kw):
        sp = Path(cmd[-1])
        env.procs[901] = "ffmpeg.exe"
        screenrec.update(sp, ffmpeg_pid=901)
        return SimpleNamespace(pid=900, poll=lambda: None)

    stub_start(env, popen, probe)
    screenrec.start(start_args(env.tmp / "a"))
    out = capsys.readouterr().out
    assert warning in out and "Recording anyway" in out and "recording since" in out


def test_status_warns_before_the_first_frame_and_during_an_open_stall(env, capsys):
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    ago = lambda s: (datetime.now() - timedelta(seconds=s)).isoformat(timespec="milliseconds")
    write_state(sp, started=ago(60), runner_pid=800, ffmpeg_pid=801)
    env.procs.update({800: "python.exe", 801: "ffmpeg.exe"})
    screenrec.pointer("p").write_text(str(d))
    screenrec.status(argparse.Namespace(profile="p"))
    assert "frames 0" in (out := capsys.readouterr().out) and "warning: no frame yet after 60 s" in out
    sp.with_suffix(".progress").write_text("frame=300\n", encoding="utf-8")
    screenrec.status(argparse.Namespace(profile="p"))
    assert "frames 300" in (out := capsys.readouterr().out) and "warning" not in out  # frames come: no stall
    screenrec.update(sp, stalls=[[ago(50), None, None]])  # the runner saw none for STALL_S s
    screenrec.status(argparse.Namespace(profile="p"))
    out = capsys.readouterr().out
    # no cause Windows can show (a state from before `hwnd` was kept has none to check): it may be a stuck capture
    assert "warning: no new frame for 50 s (since " in out and "the capture is stuck: stop, then start" in out


def test_status_names_a_minimised_window_instead_of_a_stuck_capture(env, capsys):
    # #45: the #451 clip ends at 04:13:28.9 because MuMu's window was minimised at 04:13:29.5 (its shell log), not
    # because the capture stuck: frames come back once the window is restored, and a new `start` refuses it.
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    ago = lambda s: (datetime.now() - timedelta(seconds=s)).isoformat(timespec="milliseconds")
    write_state(sp, started=ago(60), runner_pid=800, ffmpeg_pid=801, hwnd=4242, stalls=[[ago(20), None, None]])
    env.procs.update({800: "python.exe", 801: "ffmpeg.exe"})
    sp.with_suffix(".progress").write_text("frame=300\n", encoding="utf-8")
    screenrec.pointer("p").write_text(str(d))
    asked = []
    env.mp.setattr(screenrec, "silent_cause", lambda h: (asked.append(h), "minimised")[1])
    screenrec.status(argparse.Namespace(profile="p"))
    out = capsys.readouterr().out
    now, do, _ = screenrec.CAUSES["minimised"]
    assert "warning: no new frame for 20 s (since " in out and f"; {now}: {do}" in out and "stuck" not in out
    assert set(asked) == {4242}
    screenrec.update(sp, stalls=[])  # minimised a moment ago: no stall yet, and none of its frames will come
    screenrec.status(argparse.Namespace(profile="p"))
    assert f"warning: {now}: {do}" in capsys.readouterr().out


def test_status_of_a_recording_that_ended_with_its_window(env, capsys):
    # A closed window ends gfxcapture within 0.1 s (measured), so the recording is no longer active when status runs.
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    write_state(sp, runner_pid=800, ffmpeg_pid=801, hwnd=4242, ended=True)
    screenrec.pointer("p").write_text(str(d))
    for cause, said in (("gone", True), ("minimised", False), (None, False)):  # only a closed window ends a recording
        env.mp.setattr(screenrec, "silent_cause", lambda h, c=cause: c)
        screenrec.status(argparse.Namespace(profile="p"))
        out = capsys.readouterr().out
        assert "active False" in out and ("warning: the recording ended: the window is gone" in out) == said


def test_start_names_no_display_when_the_probe_gets_no_frame(env, capsys):
    # #45: in #453 the only monitor left the bus at 04:22:32.3 (Kernel-PnP 1010), 0.4 s after the last frame, and two
    # later starts got no frame. The warning says so instead of blaming a window that does not redraw.
    def popen(cmd, **kw):
        sp = Path(cmd[-1])
        env.procs[901] = "ffmpeg.exe"
        screenrec.update(sp, ffmpeg_pid=901)
        return SimpleNamespace(pid=900, poll=lambda: None)

    stub_start(env, popen, "none", cause="no display")
    screenrec.start(start_args(env.tmp / "a"))
    out = capsys.readouterr().out
    now, do, _ = screenrec.CAUSES["no display"]
    assert f"no frame from the capture within 10 s; {now}: {do}. Recording anyway" in out
    assert screenrec.load(screenrec.state_file((env.tmp / "a").resolve(), "p"))["hwnd"] == WIN["hwnd"]  # for status


def fake_user32(monkeypatch, window=True, iconic=False, visible=True, displays=1):
    user32 = SimpleNamespace(IsWindow=lambda h: window, IsIconic=lambda h: iconic, IsWindowVisible=lambda h: visible)
    monkeypatch.setattr(screenrec.ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    monkeypatch.setattr(screenrec, "active_displays", lambda: displays)


@pytest.mark.parametrize("state, cause", [
    ({}, None),
    ({"window": False}, "gone"),
    ({"iconic": True, "visible": True}, "minimised"),  # Windows counts a minimised window as visible
    ({"visible": False}, "hidden"),
    ({"displays": 0}, "no display"),
    ({"displays": None}, None),  # the display query failed: no claim
    ({"iconic": True, "displays": 0}, "minimised"),  # the window's own state first
])
def test_silent_cause_reads_the_window_then_the_displays(monkeypatch, state, cause):
    fake_user32(monkeypatch, **state)
    assert screenrec.silent_cause(4242) == cause


def test_a_stall_keeps_the_cause_seen_when_it_opened():
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    watch = {"frames": 5, "at": t0, "stalls": []}
    line = screenrec.track_stall(watch, 5, t0 + timedelta(seconds=screenrec.STALL_S + 1), cause=lambda: "minimised")
    now, do, was = screenrec.CAUSES["minimised"]
    assert line.endswith(f"no new frame since 10:00:00.0: {now}")
    assert watch["stalls"] == [["2026-01-01T10:00:00.000", None, "minimised"]]
    old = ["2026-01-01T09:00:00.000", "2026-01-01T09:00:30.000"]  # a state written before stalls kept a cause
    lines = screenrec.stall_lines(watch["stalls"] + [old], datetime(2026, 1, 1, 10, 1, 0))
    # stop prints these once the recording ended: what held, without "restore it and this recording goes on"
    assert lines[0].endswith(f"; {was}") and do not in lines[0] and lines[1].endswith(screenrec.NOT_DRAWING)


def test_runner_logs_the_cause_of_a_stall_and_of_an_end_by_itself(tmp_path, monkeypatch, capsys):
    import threading
    monkeypatch.setattr(screenrec, "silent_cause", lambda h: {4242: "minimised", 4343: "gone"}.get(h))
    # A capture that sends one frame and blocks: no progress file, so no frame counts, and the stall opens at once
    # (the state's start is long past).
    sp = screenrec.state_file(tmp_path, "p")
    write_state(sp, capture=[sys.executable, "-c", CAPTURE_STUCK], encode=[sys.executable, "-c", ENCODER, str(tmp_path / "a")],
                runner_pid=4321, hwnd=4242)
    monkeypatch.setattr(screenrec, "Q_WAIT_S", 1)
    threading.Timer(1.5, lambda: sp.with_suffix(".stop").write_text("stop")).start()
    screenrec.run(argparse.Namespace(state=str(sp)))
    out = capsys.readouterr().out
    assert f"no new frame since 10:00:00.0: {screenrec.CAUSES['minimised'][0]}" in out and "by itself" not in out
    assert screenrec.load(sp)["stalls"][-1][2] == "minimised"
    # A capture that ends on its own, as gfxcapture does when its window closes: the encoder ends, and so the run.
    sp = screenrec.state_file(tmp_path, "q")
    write_state(sp, capture=[sys.executable, "-c", "print('frame')"], encode=[sys.executable, "-c", ENCODER, str(tmp_path / "b")],
                runner_pid=4321, hwnd=4343)
    screenrec.run(argparse.Namespace(state=str(sp)))
    assert f"the recording ended by itself: {screenrec.CAUSES['gone'][2]}" in capsys.readouterr().out


def test_stop_says_what_held_once_the_recording_ended(env, capsys):
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    mkv = d / "rec_p_20260101_100000.mkv"
    mkv.write_bytes(b"x")
    last = datetime.now() - timedelta(seconds=8)
    write_state(sp, mkv=str(mkv), runner_pid=800, ffmpeg_pid=801, ended=True, hwnd=4242,
                last_frame=last.isoformat(timespec="milliseconds"))
    screenrec.pointer("p").write_text(str(d))
    env.mp.setattr(screenrec, "silent_cause", lambda h: "minimised" if h == 4242 else None)

    def fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"m")
        return SimpleNamespace(returncode=0)

    env.mp.setattr(screenrec.subprocess, "run", fake_run)
    screenrec.stop(argparse.Namespace(profile="p"))
    _, do, was = screenrec.CAUSES["minimised"]
    out = capsys.readouterr().out
    assert f"8 s before the stop; {was}" in out and do not in out
    # nothing written: the same cause, as it was
    write_state(sp, runner_pid=800, ffmpeg_pid=801, ended=True, hwnd=4242)
    screenrec.pointer("p").write_text(str(d))
    with pytest.raises(SystemExit, match=f"no frame was encoded; {was}"):
        screenrec.stop(argparse.Namespace(profile="p"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_silent_cause_reads_a_real_window():
    # A top-level window of our own, off screen and never activated: shown, hidden, minimised, destroyed.
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                  wintypes.HINSTANCE, wintypes.LPVOID]
    hwnd = u.CreateWindowExW(0x08000000, "STATIC", "screenrec test", 0x00CF0000, -3000, -3000, 200, 100,
                             None, None, None, None)  # WS_EX_NOACTIVATE, WS_OVERLAPPEDWINDOW
    assert hwnd
    try:
        u.ShowWindow(wintypes.HWND(hwnd), 4)  # SW_SHOWNOACTIVATE
        displays = screenrec.active_displays()
        assert isinstance(displays, int)
        assert screenrec.silent_cause(hwnd) == ("no display" if displays == 0 else None)
        u.ShowWindow(wintypes.HWND(hwnd), 0)  # SW_HIDE
        assert screenrec.silent_cause(hwnd) == "hidden"
        u.ShowWindow(wintypes.HWND(hwnd), 7)  # SW_SHOWMINNOACTIVE
        assert screenrec.silent_cause(hwnd) == "minimised"
    finally:
        u.DestroyWindow(wintypes.HWND(hwnd))
    assert screenrec.silent_cause(hwnd) == "gone"
    assert screenrec.silent_cause(None) is None  # a state from before hwnd was kept


def test_stop_without_a_written_file_says_why_and_leaves_nothing(env):
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    write_state(sp, runner_pid=800, ffmpeg_pid=801, ended=True)  # the runner killed an ffmpeg stuck on a silent capture
    for suffix in (".stop", ".progress"):
        sp.with_suffix(suffix).write_text("")
    screenrec.pointer("p").write_text(str(d))
    with pytest.raises(SystemExit, match="no recording written .*no frame was encoded.*not redrawing"):
        screenrec.stop(argparse.Namespace(profile="p"))
    assert sorted(p.name for p in d.iterdir()) == [] and not screenrec.pointer("p").exists()


def test_two_profiles_in_one_out_name_their_recordings_apart(env):
    d = env.tmp / "a"
    seen = []

    def popen(cmd, **kw):
        seen.append(Path(json.loads(Path(cmd[-1]).read_text())["mkv"]).name)
        return SimpleNamespace(pid=1, poll=lambda: 1)  # the runner "exits", so start gives up at once

    stub_start(env, popen)
    for prof in ("one", "two"):
        with pytest.raises(SystemExit):
            screenrec.start(start_args(d, prof))
    assert seen[0].startswith("rec_one_") and seen[1].startswith("rec_two_")


# Stand-ins for the two ffmpegs. The capture writes a frame, then waits for `q` (or, stuck, ignores it).
CAPTURE_Q = "import sys; print('frame', flush=True); sys.stdin.readline(); print('last', flush=True)"
CAPTURE_STUCK = "import sys, time; print('frame', flush=True); time.sleep(600)"
# The encoder copies its stdin to a file and writes `end` at EOF, as ffmpeg finishes a file when its input ends.
ENCODER = "import sys; o = open(sys.argv[1], 'w'); o.write(sys.stdin.read()); o.write('end'); o.close()"


@pytest.mark.parametrize("capture, written", [(CAPTURE_Q, "frame\nlast\nend"), (CAPTURE_STUCK, "frame\nend")])
def test_runner_ends_the_capture_and_lets_the_encoder_finish(tmp_path, monkeypatch, capture, written):
    import threading
    sp = screenrec.state_file(tmp_path, "p")
    out = tmp_path / "enc.txt"
    write_state(sp, capture=[sys.executable, "-c", capture], encode=[sys.executable, "-c", ENCODER, str(out)],
                runner_pid=4321)
    monkeypatch.setattr(screenrec, "Q_WAIT_S", 2)
    threading.Timer(1.0, lambda: sp.with_suffix(".stop").write_text("stop")).start()
    t = time.monotonic()
    screenrec.run(argparse.Namespace(state=str(sp)))
    st = screenrec.load(sp)
    assert st["runner_pid"] == 4321 and st["ffmpeg_pid"] > 0 and st["capture_pid"] > 0 and st["ended"] and st["rc"] == 0
    assert st["last_frame"]  # when the frame count last grew, for `stop` to say where the clip ends
    assert out.read_text() == written  # a stuck capture is killed; the encoder still ends its file cleanly
    assert time.monotonic() - t < 15


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_a_killed_capture_still_leaves_a_whole_file(tmp_path):
    mkv = tmp_path / "x.mkv"
    cap, enc = screenrec.pipeline("testsrc2=s=64x64:r=30", mkv, tmp_path / "x.progress", ["-c:v", "libx264"])
    cap.insert(cap.index("-f"), "-re")  # real time, like a capture
    p1 = subprocess.Popen(cap, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(enc, stdin=p1.stdout)
    p1.stdout.close()
    time.sleep(2)
    p1.kill()  # what the runner does to a capture stuck on a window that sends nothing
    p1.wait()
    assert p2.wait(timeout=30) == 0
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mkv), "-f", "null", "-"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stderr == ""  # no "File ended prematurely": the MKV has its end


def test_pipeline_pipes_raw_frames_and_keeps_wall_clock_timestamps(tmp_path):
    cap, enc = screenrec.pipeline("CHAIN", tmp_path / "x.mkv", tmp_path / "x.progress", ["-c:v", "libx264"])
    assert cap[cap.index("-i") + 1] == "CHAIN" and cap[-3:] == ["-f", "nut", "pipe:1"] and "rawvideo" in cap
    assert enc[enc.index("-i") + 1] == "pipe:0" and "-nostdin" in enc
    # the capture stamps frames with their wall-clock offset; -copyts on both keeps it (ffmpeg otherwise shifts the
    # first frame to 0), so fps pads back to the start
    assert "-copyts" in cap and "-copyts" in enc and enc[enc.index("-vf") + 1] == f"fps={screenrec.FPS}:start_time=0"
    assert enc[-1] == str(tmp_path / "x.mkv")
    # progress counts frames as they leave the capture: the encoder holds seconds of frames until more arrive
    assert cap[cap.index("-progress") + 1] == str(tmp_path / "x.progress") and "-progress" not in enc


def test_track_stall_opens_after_stall_s_without_a_new_frame_and_closes_on_the_next():
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    at = lambda s: t0 + timedelta(seconds=s)
    watch = {"frames": 0, "at": t0, "stalls": []}
    assert screenrec.track_stall(watch, 30, at(1)) is None and watch["at"] == at(1)
    assert screenrec.track_stall(watch, 600, at(20)) is None
    assert screenrec.track_stall(watch, 600, at(20 + screenrec.STALL_S)) is None and watch["stalls"] == []
    line = screenrec.track_stall(watch, 600, at(20 + screenrec.STALL_S + 1))
    assert line.endswith("no new frame since 10:00:20.0") and watch["stalls"] == [["2026-01-01T10:00:20.000", None, None]]
    assert screenrec.track_stall(watch, 600, at(50)) is None  # still the same stall
    line = screenrec.track_stall(watch, 601, at(59))
    assert "frames again" in line and watch["stalls"] == [["2026-01-01T10:00:20.000", "2026-01-01T10:00:59.000", None]]
    # none before the first frame: the stall runs from the start
    watch = {"frames": 0, "at": t0, "stalls": []}
    assert "since 10:00:00.0" in screenrec.track_stall(watch, 0, at(screenrec.STALL_S + 1))


def test_stall_lines_name_each_stretch_and_a_clip_that_ends_early():
    stalls = [["2026-01-01T10:00:20.000", "2026-01-01T10:00:59.000"], ["2026-01-01T10:01:30.000", None]]
    lines = screenrec.stall_lines(stalls, datetime(2026, 1, 1, 10, 2, 0))
    assert lines[0].startswith("warning: no new frame 10:00:20.0-10:00:59.0 (39 s)")
    assert lines[1].startswith("warning: no new frame 10:01:30.0-10:02:00.0 (30 s)") and "the clip ends at 10:01:30.0" in lines[1]
    assert all("not redrawing" in x for x in lines)


def test_stop_reports_the_stalls_the_runner_saw(env, capsys):
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    mkv = d / "rec_p_20260101_100000.mkv"
    mkv.write_bytes(b"x")
    write_state(sp, mkv=str(mkv), runner_pid=800, ffmpeg_pid=801, ended=True,
                stalls=[["2026-01-01T10:00:20.000", None]])
    screenrec.pointer("p").write_text(str(d))

    def fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"m")
        return SimpleNamespace(returncode=0)

    env.mp.setattr(screenrec.subprocess, "run", fake_run)
    screenrec.stop(argparse.Namespace(profile="p"))
    out = capsys.readouterr().out
    assert "saved" in out and "warning: no new frame 10:00:20.0-" in out and "the clip ends at 10:00:20.0" in out


@pytest.mark.parametrize("gap, stalls, warned", [(8, [], True), (0.5, [], False), (30, [[None, None]], False)])
def test_stop_says_where_a_clip_ends_early_even_without_a_stall(env, capsys, gap, stalls, warned):
    # Review of #44: frames stopped 8 s before `stop`, under STALL_S, so no stall opened and the short clip went unsaid.
    # An open stall already says it; a clip that runs up to the stop says nothing.
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    mkv = d / "rec_p_20260101_100000.mkv"
    mkv.write_bytes(b"x")
    last = datetime.now() - timedelta(seconds=gap)
    stalls = [[last.isoformat(timespec="milliseconds"), None] for _ in stalls]
    write_state(sp, mkv=str(mkv), runner_pid=800, ffmpeg_pid=801, ended=True, stalls=stalls,
                last_frame=last.isoformat(timespec="milliseconds"))
    screenrec.pointer("p").write_text(str(d))

    def fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"m")
        return SimpleNamespace(returncode=0)

    env.mp.setattr(screenrec.subprocess, "run", fake_run)
    screenrec.stop(argparse.Namespace(profile="p"))
    out = capsys.readouterr().out
    assert ("before the stop" in out) == warned and (f"the clip ends at {screenrec.clock(last)}" in out) == (warned or bool(stalls))


def test_progress_reads_only_the_tail_of_a_long_file(tmp_path):
    # Review of #44: the runner reads the file five times a second and it grows by a block every half second, so a
    # whole read cost most of a core after hours. The head here is not UTF-8: a whole read fails on it, a tail read
    # never sees it; the tail starts mid-line and still ends with the last block.
    sp = screenrec.state_file(tmp_path, "p")
    blocks = "".join(f"frame={n}\nout_time_us={n * 33333}\nprogress=continue\n" for n in range(1, 20001))
    sp.with_suffix(".progress").write_bytes(b"\xff\xfe" * 8 + blocks.encode())
    assert screenrec.progress(sp) == 20000


def test_status_lists_earlier_stalls(env, capsys):
    d = env.tmp / "a"
    d.mkdir()
    sp = screenrec.state_file(d, "p")
    started = (datetime.now() - timedelta(seconds=60)).isoformat(timespec="milliseconds")
    write_state(sp, started=started, runner_pid=800, ffmpeg_pid=801, stalls=[["2026-01-01T10:00:20.000", "2026-01-01T10:00:59.000"]])
    env.procs.update({800: "python.exe", 801: "ffmpeg.exe"})
    sp.with_suffix(".progress").write_text("frame=1770\nout_time_us=59000000\n", encoding="utf-8")
    screenrec.pointer("p").write_text(str(d))
    screenrec.status(argparse.Namespace(profile="p"))
    assert "warning: no new frame 10:00:20.0-10:00:59.0 (39 s)" in capsys.readouterr().out


def test_a_second_start_appends_to_the_log(env):
    d = env.tmp / "a"
    d.mkdir()
    log = d / "rec_p.log"
    log.write_text("first recording's lines\n", encoding="utf-8")

    def popen(cmd, **kw):
        kw["stdout"].write("runner line\n")
        return SimpleNamespace(pid=1, poll=lambda: 1)  # the runner "exits", so start gives up at once

    stub_start(env, popen)
    with pytest.raises(SystemExit):
        screenrec.start(start_args(d))
    text = log.read_text(encoding="utf-8")
    assert text.startswith("first recording's lines\n") and "start rec_p_" in text and "runner line" in text


def test_runner_without_a_recorded_pid_does_not_start_ffmpeg(tmp_path, monkeypatch):
    sp = screenrec.state_file(tmp_path, "p")
    write_state(sp, cmd=[sys.executable, "-c", "raise SystemExit(7)"])
    monkeypatch.setattr(screenrec.time, "sleep", lambda s: None)
    monkeypatch.setattr(screenrec.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(SystemExit):
        screenrec.run(argparse.Namespace(state=str(sp)))


@pytest.mark.skipif(sys.platform != "win32", reason="window lookup is Windows only")
def test_window_lookup_goes_per_monitor_dpi_aware_before_reading_sizes(monkeypatch):
    order = []

    class Fn:
        argtypes = None

        def __call__(self, ctx):
            order.append("dpi")

    user32 = SimpleNamespace(SetProcessDpiAwarenessContext=Fn(), EnumWindows=lambda cb, p: order.append("enum"))
    monkeypatch.setattr(screenrec.ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    assert screenrec.find_windows("x") == [] and order == ["dpi", "enum"]


if __name__ == "__main__":
    sys.exit(pytest.main(["-q", __file__]))
