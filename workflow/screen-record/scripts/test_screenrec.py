# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Checks for screenrec.py's pure parts: window pick, output size, capture chain, black-frame test, pruning.

uv run test_screenrec.py
"""
import os
import sys
import time

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
    mine = [tmp_path / f"rec_{i}.mp4" for i in range(3)]
    other = tmp_path / "notes.mp4"
    for i, p in enumerate(mine + [other]):
        p.write_bytes(b"x" * 1024)
        os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    screenrec.prune(tmp_path, 2048 / 2**30)  # room for two files
    assert [p.exists() for p in mine] == [False, True, True] and other.exists()


if __name__ == "__main__":
    sys.exit(pytest.main(["-q", __file__]))
