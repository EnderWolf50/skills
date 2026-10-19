# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "numpy", "opencv-python-headless", "pytest"]
# ///
"""Checks for annotate.py at its seams: events -> gestures, steps timing, zoom easing, masks.

uv run test_annotate.py        (or: uv run --with pytest pytest -q test_annotate.py)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

import annotate as a

SPACE = (1280, 720)
# geometry tests draw no CJK text, so any font will do where no CJK font is installed
FONT = next((f for f in [*a.FONTS, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] if Path(f).exists()), None)


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
    p = a.Painter(2560, 720, SPACE, FONT)  # x doubled, y unchanged
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


def test_space_is_cast_to_two_ints_and_rejects_anything_else():
    assert a.parse_space({"space": [1280.0, "720"]}, "x") == (1280, 720)
    for bad in ({}, {"space": [1280]}, {"space": ["a;b", 720]}, {"space": [0, 720]}, {"space": [1280, -1]}, {"space": 5}):
        with pytest.raises(SystemExit):
            a.parse_space(bad, "x")


def test_load_masks_rejects_empty_boxes_and_a_text_space(tmp_path):
    import cv2
    cv2.imwrite(str(tmp_path / "t.png"), np.zeros((4, 4), np.uint8))

    def masks(space, box):
        (tmp_path / "m.json").write_text(json.dumps({"space": space, "masks": [{"template": "t.png", "boxes": [box]}]}))
        return a.load_masks(tmp_path / "m.json")

    for box in ([0, 0, 0, 5], [0, 0, 5, -1], [0, 0, 5]):
        with pytest.raises(SystemExit, match="above 0|x,y,w,h"):
            masks([10, 10], box)
    with pytest.raises(SystemExit):
        masks(["1280,scale=1:1;", 720], [0, 0, 1, 1])
    assert masks([10, 10], [-5, -5, 20, 20])[1] == (10, 10)  # out-of-frame boxes stay legal: they are clamped


def test_clip_bounds_refuses_a_cut_before_start():
    start = a.hms("14:30:00")
    assert a.clip_bounds(start, None, None, 60.0) == (0.0, 60.0)
    ss, dur = a.clip_bounds(start, "14:30:10", "14:30:25", 60.0)
    assert (ss, dur) == (pytest.approx(10), pytest.approx(15))
    assert a.clip_bounds(start, "14:30:10", None, 60.0)[1] == pytest.approx(50)
    with pytest.raises(SystemExit, match="before --start"):
        a.clip_bounds(start, "14:29:50", "14:30:25", 60.0)  # would shift every annotation by 10 s
    with pytest.raises(SystemExit, match="empty"):
        a.clip_bounds(start, "14:30:20", "14:30:10", 60.0)


if __name__ == "__main__":
    sys.exit(pytest.main(["-q", __file__]))


def track(gs, **style):
    return a.Track(gs, a.load_style({"style": style}), lambda x, y: (x, y))


def test_track_rests_then_glides_to_arrive_on_the_next_press():
    gs = a.gestures([ev("10:00:01.0", "tap", 100, 100), ev("10:00:05.0", "tap", 500, 300)])
    tr = track(gs)
    start, _, traj, _ = tr.glides[0]
    t1 = gs[1]["t0"]
    assert start == pytest.approx(t1 - traj.arrival)  # the move ends as the press starts
    assert tr.at(gs[0]["t0"] - 1)[:2] == (100, 100)  # before the first gesture: waits on it
    assert tr.at(start - 0.1)[:3] == (100, 100, a.cm.REST_HEADING)  # rests until the glide starts
    x, y, h, *_ = tr.at(start + traj.arrival / 2)
    assert 100 < x < 500 and h != a.cm.REST_HEADING  # leans into the move
    assert tr.at(t1)[:2] == pytest.approx((500, 300), abs=1)
    assert tr.at(t1 + 9)[:3] == (500, 300, a.cm.REST_HEADING)


def test_track_squeezes_a_glide_into_a_short_gap_and_skips_none():
    gs = a.gestures([ev("10:00:01.0", "tap", 100, 100), ev("10:00:01.3", "tap", 900, 600)])
    start, g, traj, _ = track(gs).glides[0]
    assert traj.arrival == pytest.approx(gs[1]["t0"] - gs[0]["t1"]) and start == pytest.approx(gs[0]["t1"])


def test_press_scale_shrinks_before_the_press_and_recovers_after_the_release():
    g = a.gestures([ev("10:00:01.0", "tap", 1, 1)])
    t0, t1 = g[0]["t0"], g[0]["t1"]
    assert a.press_k(g, t0 - a.PRESS_S - 0.01) == 1
    assert a.press_k(g, t0) == pytest.approx(a.PRESS_K)
    assert a.press_k(g, t1 + a.PRESS_S + 0.01) == 1


def test_ring_shows_only_after_the_press():
    p = a.Painter(1280, 720, SPACE, FONT)
    from PIL import Image
    for age, drawn in ((-0.05, False), (0.1, True), (a.RING_S + 0.05, False)):
        ov = Image.new("RGBA", (1280, 720))
        p.ring(ov, 640, 360, age)
        assert (ov.getbbox() is not None) == drawn, age


def test_mouse_pointer_sprite_is_drawn_tip_first_and_clipped_at_the_edge():
    p = a.Painter(1280, 720, SPACE, FONT)
    from PIL import Image
    gs = a.gestures([ev("10:00:01.0", "tap", 1270, 710)])
    ov = Image.new("RGBA", (1280, 720))
    p.cursor(ov, p.track(gs), gs, gs[0]["t0"])  # near the corner: must not raise
    assert ov.getpixel((1271, 713))[3] > 200  # the tip sits on the press
    x0, y0, _, _ = ov.getbbox()
    assert x0 >= 1256 and y0 >= 698  # only the shadow's blur reaches past the tip


def test_glide_bows_unless_arc_is_zero_and_leans_unless_tilt_is_zero():
    gs = a.gestures([ev("10:00:01.0", "tap", 100, 300), ev("10:00:05.0", "tap", 900, 300)])
    def mid(**style):
        tr = track(gs, **style)
        start, _, traj, _ = tr.glides[0]
        return tr.at(start + traj.arrival / 2)
    assert abs(mid()[1] - 300) > 30
    assert mid(arc=0)[1] == pytest.approx(300)
    assert mid(tilt=0)[2] == a.cm.REST_HEADING


def test_style_fills_defaults_and_rejects_bad_values():
    st = a.load_style({"style": {"cursor": "figma", "color": "#8b5cf6"}})
    assert st["color"] == (0x8B, 0x5C, 0xF6) and st["trail"] is True
    assert a.load_style({"style": {"cursor": "cua"}})["color"] == (0x5E, 0xC0, 0xE8)  # Cua blue by default
    for bad in ({"cursor": "windows"}, {"color": "blue"}, {"colour": "#000000"}, {"motion": "magnetic"}, {"tilt": 2}):
        with pytest.raises(SystemExit):
            a.load_style({"style": bad})


@pytest.mark.parametrize("cursor", a.CURSORS)
def test_every_cursor_draws_its_tip_on_the_point_with_a_label(cursor):
    from PIL import Image
    p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"cursor": cursor, "label": "Claude"}}))
    gs = a.gestures([ev("10:00:01.0", "tap", 640, 360)])
    ov = Image.new("RGBA", (1280, 720))
    p.cursor(ov, p.track(gs), gs, gs[0]["t0"])
    assert ov.getpixel((643, 366) if cursor != "cua" else (646, 364))[3] > 200  # the pointer covers the press point
    assert ov.getpixel((640 + 29 + 10, 360 + 38 + 17))[3] > 200  # the tag sits below right of the tip


def test_key_items_make_caps_and_join_close_typing():
    items = a.key_items([ev("10:00:01.0", "type", text="AB", ms=100), ev("10:00:01.5", "type", text="C"),
                         ev("10:00:05.0", "key", keys="Ctrl + S"), ev("10:00:09.0", "type", text="Z"),
                         ev("10:00:00.5", "tap", 1, 1)])
    assert len(items) == 3  # AB and C joined; the key; Z after a gap
    assert "".join(ch for _, ch in items[0]["chars"]) == "ABC" and items[0]["chars"][1][0] == pytest.approx(a.hms("10:00:01.05"))
    assert items[1]["caps"] == ["Ctrl", "S"]
    item, alpha = a.key_at(items, a.hms("10:00:05.5"))
    assert item is items[1] and alpha == 1
    assert a.key_at(items, a.hms("10:00:07.0")) is None
    with pytest.raises(ValueError):
        a.key_items([ev("10:00:01.0", "key")])


def test_gestures_skip_key_events():
    assert len(a.gestures([ev("10:00:01.0", "key", keys="Enter"), ev("10:00:02.0", "tap", 1, 1)])) == 1


def test_camera_zooms_in_before_a_burst_pans_away_and_out_after():
    gs = a.gestures([ev("10:00:02.0", "tap", 200, 200), ev("10:00:03.0", "tap", 220, 210),  # close: no pan
                     ev("10:00:04.0", "tap", 1100, 600), ev("10:00:20.0", "tap", 640, 360)])
    cam = a.Camera(gs, [], SPACE, 2.0)
    assert len(cam.bursts) == 2 and len(cam.bursts[0][2]) == 2  # the 220,210 press stayed in view
    t = lambda s: a.hms(s)
    assert cam.region(t("10:00:00.5")) is None
    x, y, w, h = cam.region(t("10:00:02.0"))
    assert (w, h) == (640, 360) and x <= 200 <= x + w and y <= 200 <= y + h
    x, y, w, h = cam.region(t("10:00:04.0"))
    assert x + w == 1280 and y + h == 720  # panned to the far corner, clamped inside the frame
    assert cam.region(t("10:00:10.0")) is None  # out between bursts


def test_camera_fits_a_long_drag():
    gs = a.gestures([ev("10:00:02.0", "swipe", 100, 360, x2=1100, y2=360, ms=500)])
    _, _, w, _ = a.Camera(gs, [], SPACE, 2.5).region(a.hms("10:00:02.3"))
    assert w >= 1000 * 1.4 - 1 or w == 1280


def test_rest_counts_from_the_last_move_to_the_next():
    gs = a.gestures([ev("10:00:01.0", "tap", 100, 100), ev("10:00:09.0", "tap", 900, 600)])
    tr = track(gs)
    start = tr.glides[0][0]
    since, until = tr.rest(a.hms("10:00:03.0"))
    assert since == pytest.approx(a.hms("10:00:03.0") - gs[0]["t1"]) and until == pytest.approx(start - a.hms("10:00:03.0"))
    assert tr.rest(gs[1]["t0"]) == (0, 0)


def test_idle_fade_hides_a_resting_pointer_and_brings_it_back_before_it_moves():
    from PIL import Image
    gs = a.gestures([ev("10:00:01.0", "tap", 300, 300), ev("10:00:09.0", "tap", 900, 600)])
    p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"idle_fade": 1.5}}))
    tr = p.track(gs)
    def drawn(t):
        ov = Image.new("RGBA", (1280, 720))
        p.cursor(ov, tr, gs, t)
        return ov.getbbox() is not None
    assert drawn(a.hms("10:00:01.5")) and not drawn(a.hms("10:00:05.0")) and drawn(tr.glides[0][0])


def test_idle_spans_cover_only_long_quiet_gaps_inside_their_edges():
    gs = a.gestures([ev("10:00:01.0", "tap", 1, 1), ev("10:00:03.0", "tap", 1, 1), ev("10:00:20.0", "tap", 1, 1)])
    keys = a.key_items([ev("10:00:10.0", "key", keys="Enter")])
    spans = a.idle_spans(gs, keys, [], 2.0)
    end3 = gs[1]["t1"] + 1.0
    assert spans == [pytest.approx((end3 + 0.3, a.hms("10:00:10.0") - 0.3 - 0.3)),
                     pytest.approx((a.hms("10:00:11.0") + 0.3, a.hms("10:00:20.0") - 0.8 - 0.3))]


def test_framer_pads_keeps_the_frame_and_rounds_its_corners():
    f = a.Framer(1280, 720, [(109, 93, 252), (242, 123, 155)])
    out = f(np.full((720, 1280, 3), 200, np.uint8))
    assert out.shape == (f.h, f.w, 3) and f.w % 2 == 0 and f.h % 2 == 0
    assert (out[f.py + 360, f.px + 640] == 200).all()  # content untouched
    assert not (out[f.py, f.px] == 200).all()  # the corner is cut round
    assert tuple(a.load_style({"style": {"frame": ["#6d5dfc", "#f27b9b"]}})["frame"][0]) == (0x6D, 0x5D, 0xFC)
    with pytest.raises(SystemExit):
        a.load_style({"style": {"frame": "pink"}})
