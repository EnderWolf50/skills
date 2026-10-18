# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "numpy", "opencv-python-headless", "pytest"]
# ///
"""Checks for annotate.py at its seams: events -> gestures, steps timing, zoom easing, masks.

uv run test_annotate.py        (or: uv run --with pytest pytest -q test_annotate.py)
"""
import json
import sys

import numpy as np
import pytest

import annotate as a

SPACE = (1280, 720)


def ev(t, kind, x=None, y=None, **kw):
    return {"t": t, "kind": kind, **({"x": x, "y": y} if x is not None else {}), **kw}


def test_tap_is_a_short_tap():
    (g,) = a.gestures([ev("14:30:14.710", "tap", 1108, 494)])
    assert g["kind"] == "tap" and g["pts"] == [(a.hms("14:30:14.710"), 1108, 494)]
    assert g["t1"] - g["t0"] == pytest.approx(0.05)


def test_swipe_runs_start_to_end_over_ms_and_is_a_drag():
    (g,) = a.gestures([ev("14:30:50.340", "swipe", 444, 330, x2=444, y2=650, ms=600)])
    assert g["kind"] == "drag"
    assert [p[1:] for p in g["pts"]] == [(444, 330), (444, 650)]
    assert g["t1"] - g["t0"] == pytest.approx(0.6)


def test_down_up_without_movement_is_tap_then_hold_by_duration():
    short = a.gestures([ev("10:00:00.000", "down", 300, 300), ev("10:00:00.200", "up")])
    long = a.gestures([ev("10:00:00.000", "down", 300, 300), ev("10:00:01.500", "up")])
    assert short[0]["kind"] == "tap" and long[0]["kind"] == "hold"


def test_up_with_a_point_makes_a_drag_ending_there():
    (g,) = a.gestures([ev("10:00:00.000", "down", 852, 391), ev("10:00:00.900", "up", 600, 400)])
    assert g["kind"] == "drag" and g["pts"][-1][1:] == (600, 400)
    assert g["t1"] == pytest.approx(a.hms("10:00:00.900"))


def test_events_are_sorted_and_offset_shifts_every_time():
    gs = a.shift(a.gestures([ev("10:00:02.0", "tap", 1, 1), ev("10:00:01.0", "tap", 2, 2)]), 0.5)
    assert [g["pts"][0][1] for g in gs] == [2, 1]
    assert gs[0]["t0"] == pytest.approx(a.hms("10:00:01.5")) and gs[0]["pts"][0][0] == gs[0]["t0"]


def test_unknown_kind_is_an_error():
    with pytest.raises(ValueError):
        a.gestures([ev("10:00:00", "wiggle", 1, 1)])


def test_stray_up_and_two_finger_sequence_do_not_raise():
    assert a.gestures([ev("10:00:00.0", "up")]) == []
    gs = a.gestures([ev("10:00:00.0", "down", 10, 10), ev("10:00:00.1", "down", 50, 50),
                     ev("10:00:00.2", "up"), ev("10:00:00.3", "up")])  # last `up` has nothing held
    assert len(gs) == 2 and gs[0]["t1"] == pytest.approx(a.hms("10:00:00.1"))


def test_events_missing_coordinates_name_the_gap():
    with pytest.raises(ValueError, match="x2"):
        a.gestures([ev("10:00:00", "swipe", 1, 1, y2=5)])
    with pytest.raises(ValueError, match="tap"):
        a.gestures([{"t": "10:00:00", "kind": "tap"}])


def test_fmt_rounds_without_printing_sixty_seconds():
    assert a.fmt(a.hms("14:30:59.97")) == "14:31:00.0"
    assert a.fmt(a.hms("14:30:41.2")) == "14:30:41.2"
    assert a.fmt(a.hms("14:30:59.9996"), 3) == "14:31:00.000"
    assert a.fmt(86399.99) == "00:00:00.0"


def test_frame_indices_pick_nearest_frame_and_warn_outside_the_cut(capsys):
    start, ss = a.hms("10:00:00"), 2.0  # clip starts 2 s in, 300 frames at 30 fps
    assert a.frame_indices(["10:00:03.0", "10:00:02.0"], start, ss, 30, 300) == {30, 0}
    assert a.frame_indices(["10:00:01.0", "10:00:12.0"], start, ss, 30, 300) == set()  # before the cut, and past its end
    assert capsys.readouterr().err.count("outside the cut") == 2


def test_zoom_region_must_have_area(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps([{"from": "10:00:00", "to": "10:00:05", "title": "t", "zoom": [0, 0, 100, 0]}]))
    with pytest.raises(SystemExit):
        a.load_steps(tmp_path / "s.json")


def test_zoom_frame_crops_scales_back_and_clamps_at_the_edges():
    frame = np.zeros((72, 128, 3), np.uint8)
    frame[:, 64:] = 255  # right half white
    assert a.zoom_frame(frame, (640, 0, 640, 720), SPACE).min() == 255  # right half
    assert a.zoom_frame(frame, (0, 0, 640, 720), SPACE).max() == 0  # left half
    for region in ((-100, -100, 300, 300), (1200, 700, 500, 500), (1279, 719, 1, 1)):  # off-frame, partly off, tiny
        assert a.zoom_frame(frame, region, SPACE).shape == (72, 128, 3)


def test_coordinates_map_by_frame_size_per_axis():
    p = a.Painter(2560, 720, SPACE, a.pick_font(None))  # x doubled, y unchanged
    assert p.xy(640, 360) == (1280, 360)
    assert p.s == pytest.approx(2.0)


def test_step_at_covers_from_inclusive_to_exclusive_with_fade():
    steps = [{"from": 10.0, "to": 20.0}, {"from": 20.0, "to": 30.0}]
    assert a.step_at(steps, 9.9) is None
    i, _, alpha = a.step_at(steps, 10.0)
    assert i == 0 and alpha == 0
    assert a.step_at(steps, 15.0)[2] == 1
    assert a.step_at(steps, 20.0)[0] == 1
    assert a.step_at(steps, 19.9)[2] == pytest.approx(0.1 / a.FADE_S)


def test_ease_is_clamped_smoothstep():
    assert (a.ease(-1), a.ease(0), a.ease(0.5), a.ease(1), a.ease(2)) == (0, 0, 0.5, 1, 1)


def test_fit_region_matches_aspect_keeps_centre_and_stays_inside():
    x, y, w, h = a.fit_region([100, 100, 200, 50], SPACE)
    assert w / h == pytest.approx(16 / 9)
    assert (x + w / 2, y + h / 2) == pytest.approx((200, 125))  # centre kept
    x, y, w, h = a.fit_region([1200, 650, 80, 70], SPACE)
    assert x + w <= 1280 + 1e-9 and y + h <= 720 + 1e-9 and x >= 0 and y >= 0


def test_zoom_eases_in_holds_and_eases_out():
    step = {"from": 10.0, "to": 20.0, "zoom": [320, 180, 640, 360]}
    assert a.zoom_region({"from": 0, "to": 1}, 0.5, SPACE) is None
    assert a.zoom_region(step, 10.0, SPACE) == (0, 0, 1280, 720)
    assert a.zoom_region(step, 15.0, SPACE) == pytest.approx((320, 180, 640, 360))
    assert a.zoom_region(step, 20.0 - 1e-9, SPACE) == pytest.approx((0, 0, 1280, 720), abs=1)
    mid = a.zoom_region(step, 10.0 + a.ZOOM_S / 2, SPACE)
    assert 0 < mid[0] < 320 and 640 < mid[2] < 1280


def test_merge_spans_pads_and_joins_touching_hits():
    assert a.merge_spans([5.0, 5.5, 6.0, 20.0]) == [[4.0, 7.0], [19.0, 21.0]]
    assert a.merge_spans([0.5]) == [[0.0, 1.5]]
    assert a.merge_spans([]) == []


def test_template_matches_only_where_it_is():
    rng = np.random.default_rng(1)
    gray = rng.integers(0, 255, (72, 128), dtype=np.uint8)
    tpl = gray[20:40, 30:60].copy()
    assert a.matches(gray, tpl, 0.8)
    assert not a.matches(rng.integers(0, 255, (72, 128), dtype=np.uint8), tpl, 0.8)
    assert not a.matches(gray[:10], tpl, 0.8)  # template taller than the frame


def test_apply_masks_blacks_boxes_in_span_only_and_scales_to_frame():
    frame = np.full((72, 128, 3), 200, np.uint8)  # 1/10 of SPACE
    masks = [(None, 0.8, [[100, 200, 300, 100]])]
    spans = [[[1.0, 3.0]]]
    a.apply_masks(frame, 0.5, masks, spans, SPACE)
    assert frame.min() == 200
    a.apply_masks(frame, 2.0, masks, spans, SPACE)
    assert frame[20:30, 10:40].max() == 0 and frame[19, 10].min() == 200 and frame[20, 41].min() == 200


def test_apply_masks_clamps_boxes_that_start_outside_the_frame():
    masks, spans = [(None, 0.8, [[-300, -200, 500, 400], [1200, 650, 500, 500]])], [[[0.0, 1.0]]]
    frame = np.full((72, 128, 3), 200, np.uint8)
    a.apply_masks(frame, 0.5, masks, spans, SPACE)
    assert frame[0:20, 0:20].max() == 0 and frame[20:, 20:120].min() == 200  # top-left corner blacked, middle kept
    assert frame[65:, 120:].max() == 0  # bottom-right corner blacked
    frame = np.full((72, 128, 3), 200, np.uint8)
    a.apply_masks(frame, 0.5, [(None, 0.8, [[-900, 0, 100, 100]])], spans, SPACE)  # wholly outside: nothing, no wraparound
    assert frame.min() == 200


def test_load_masks_resolves_templates_next_to_the_masks_file(tmp_path):
    import cv2
    cv2.imwrite(str(tmp_path / "t.png"), np.zeros((4, 4), np.uint8))
    (tmp_path / "m.json").write_text(json.dumps({"space": [10, 10], "masks": [{"template": "t.png", "boxes": [[0, 0, 1, 1]]}]}))
    masks, space = a.load_masks(tmp_path / "m.json")
    assert space == (10, 10) and masks[0][1] == 0.8 and masks[0][0].shape == (4, 4)


if __name__ == "__main__":
    sys.exit(pytest.main(["-q", __file__]))
