# /// script
# requires-python = ">=3.10"
# dependencies = ["obsws-python", "pillow", "pytest"]
# ///
"""Checks for obsrec.py's pure parts: window pick, canvas size, generated OBS config, black-frame test.

uv run test_obsrec.py
"""
import io
import json
import sys

import pytest
from PIL import Image

import obsrec

WIN = {"title": "Some App", "cls": "Qt5QWindowIcon", "exe": "app.exe", "w": 1920, "h": 1140, "iconic": False}


def test_pick_window_takes_the_largest_match():
    small = {**WIN, "w": 100, "h": 100}
    assert obsrec.pick_window([small, WIN], "app") is WIN


def test_pick_window_refuses_none_and_minimised():
    with pytest.raises(SystemExit):
        obsrec.pick_window([], "app")
    with pytest.raises(SystemExit):
        obsrec.pick_window([{**WIN, "iconic": True}], "app")
    with pytest.raises(SystemExit):
        obsrec.pick_window([{**WIN, "w": 0, "h": 0}], "app")  # minimised windows report an empty client area


def test_video_size_crops_then_scales_to_720_with_even_width():
    assert obsrec.video_size(WIN, 60) == (1920, 1080, 1280, 720)
    assert obsrec.video_size({**WIN, "w": 1001, "h": 700}, 0)[2] % 2 == 0
    with pytest.raises(SystemExit):
        obsrec.video_size(WIN, 1140)


def test_profile_ini_holds_out_dir_and_sizes():
    ini = obsrec.profile_ini("p", r"C:\rec dir", (1920, 1080, 1280, 720))
    assert "Name=p" in ini and r"RecFilePath=C:\\rec dir" in ini
    assert "BaseCX=1920" in ini and "OutputCY=720" in ini and "obs_nvenc_h264_tex" in ini


def test_scene_collection_captures_the_window_with_crop():
    doc = obsrec.scene_collection("p", WIN, 60, (1920, 1080, 1280, 720))
    json.dumps(doc)
    src = next(s for s in doc["sources"] if s["id"] == "window_capture")
    assert src["settings"]["window"] == "Some App:Qt5QWindowIcon:app.exe"
    scene = next(s for s in doc["sources"] if s["id"] == "scene")
    item = scene["settings"]["items"][0]
    assert item["crop_top"] == 60 and item["source_uuid"] == src["uuid"] and item["bounds"] == {"x": 1920.0, "y": 1080.0}
    assert doc["current_scene"] == "p"


def png(value):
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (value,) * 3).save(buf, "PNG")
    return buf.getvalue()


def test_black_frame_is_detected():
    assert obsrec.is_black(png(0)) and obsrec.is_black(png(3))
    assert not obsrec.is_black(png(40))


def test_write_config_only_creates_its_own_profile_and_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(obsrec, "APPDATA", tmp_path)
    (tmp_path / "basic/profiles/mine").mkdir(parents=True)
    (tmp_path / "basic/profiles/mine/basic.ini").write_text("keep")
    obsrec.write_config("rec", tmp_path / "out", WIN, 60)
    assert (tmp_path / "basic/profiles/rec/basic.ini").exists() and (tmp_path / "basic/scenes/rec.json").exists()
    assert (tmp_path / "basic/profiles/mine/basic.ini").read_text() == "keep"


if __name__ == "__main__":
    sys.exit(pytest.main(["-q", __file__]))
