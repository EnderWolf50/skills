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
import sys
import time
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


def test_out_size_scales_to_720_with_even_width_after_crop():
    assert screenrec.out_size(WIN, 60) == (1920 * 720 // 1080, 720)  # 1920x1080 left -> 1280x720
    assert screenrec.out_size({**WIN, "w": 1001, "h": 720}, 0)[0] % 2 == 0
    with pytest.raises(SystemExit):
        screenrec.out_size(WIN, 1140)


def test_capture_chain_targets_the_hwnd_without_cursor_and_downloads_frames():
    c = screenrec.capture_chain(4242, 30)
    assert "hwnd=4242" in c and "capture_cursor=false" in c and "crop_top=30" in c
    assert c.endswith("hwdownload,format=bgra")


def test_is_black_uses_mean_brightness():
    assert screenrec.is_black(bytes(100))
    assert not screenrec.is_black(bytes([200]) * 100)
    assert not screenrec.is_black(bytes([0] * 90 + [255] * 10))  # mean 25.5


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
    screenrec.save(path, {"cmd": ["ffmpeg"], "mkv": str(path.with_suffix(".mkv")), "started": "2026-01-01T10:00:00.000",
                          "runner_image": "python.exe", **kv})


def start_args(out, profile="p"):
    return argparse.Namespace(window="app", out=str(out), profile=profile, crop_top=0, keep_gb=20, min_free_gb=0, encoder="x264")


def stub_start(env, popen):
    m = env.mp
    m.setattr(screenrec.sys, "platform", "win32")
    m.setattr(screenrec, "find_windows", lambda s: [WIN])
    m.setattr(screenrec, "test_frame_black", lambda h, c: False)
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
    assert not screenrec.running({"cmd": []})  # a state with no pids at all (pid 0) is not "recording"


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
    write_state(sp, mkv=str(mkv), runner_pid=800, ffmpeg_pid=801)  # runner gone, ffmpeg still recording
    env.procs[801] = "ffmpeg.exe"
    screenrec.pointer("p").write_text(str(d))

    def fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"mp4")
        return SimpleNamespace(returncode=0)

    env.mp.setattr(screenrec.subprocess, "run", fake_run)
    screenrec.stop(argparse.Namespace(profile="p"))
    assert env.killed == [801]
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


def test_runner_records_its_ffmpeg_pid_keeps_the_runner_pid_and_ends_on_q(tmp_path):
    import threading
    sp = screenrec.state_file(tmp_path, "p")
    waiter = [sys.executable, "-c", "import sys; sys.stdin.readline()"]  # stands in for ffmpeg: exits when it reads `q`
    write_state(sp, cmd=waiter, runner_pid=4321)
    threading.Timer(1.0, lambda: sp.with_suffix(".stop").write_text("stop")).start()
    screenrec.run(argparse.Namespace(state=str(sp)))
    st = screenrec.load(sp)
    assert st["runner_pid"] == 4321 and st["ffmpeg_pid"] > 0 and st["ended"] and st["rc"] == 0


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
