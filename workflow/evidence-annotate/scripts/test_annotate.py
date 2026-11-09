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
import common
import pointer
import text

SPACE = (1280, 720)
# geometry tests draw no CJK text, so any font will do where no CJK font is installed
FONT = next((f for f in [*a.FONTS, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] if Path(f).exists()), None)


def ev(t, kind, x=None, y=None, **kw):
    return {"t": t, "kind": kind, **({"x": x, "y": y} if x is not None else {}), **kw}


def test_tap_is_a_short_tap():
    (g,) = pointer.gestures([ev("14:30:14.710", "tap", 1108, 494)])
    assert g["kind"] == "tap" and g["pts"] == [(common.hms("14:30:14.710"), 1108, 494)]
    assert g["t1"] - g["t0"] == pytest.approx(0.05)


def test_swipe_runs_start_to_end_over_ms_and_is_a_drag():
    (g,) = pointer.gestures([ev("14:30:50.340", "swipe", 444, 330, x2=444, y2=650, ms=600)])
    assert g["kind"] == "drag"
    assert [p[1:] for p in g["pts"]] == [(444, 330), (444, 650)]
    assert g["t1"] - g["t0"] == pytest.approx(0.6)


def test_down_up_without_movement_is_tap_then_hold_by_duration():
    short = pointer.gestures([ev("10:00:00.000", "down", 300, 300), ev("10:00:00.200", "up")])
    long = pointer.gestures([ev("10:00:00.000", "down", 300, 300), ev("10:00:01.500", "up")])
    assert short[0]["kind"] == "tap" and long[0]["kind"] == "hold"


def test_up_with_a_point_makes_a_drag_ending_there():
    (g,) = pointer.gestures([ev("10:00:00.000", "down", 852, 391), ev("10:00:00.900", "up", 600, 400)])
    assert g["kind"] == "drag" and g["pts"][-1][1:] == (600, 400)
    assert g["t1"] == pytest.approx(common.hms("10:00:00.900"))


def test_events_are_sorted_and_offset_shifts_every_time():
    gs = pointer.shift(pointer.gestures([ev("10:00:02.0", "tap", 1, 1), ev("10:00:01.0", "tap", 2, 2)]), 0.5)
    assert [g["pts"][0][1] for g in gs] == [2, 1]
    assert gs[0]["t0"] == pytest.approx(common.hms("10:00:01.5")) and gs[0]["pts"][0][0] == gs[0]["t0"]


def test_unknown_kind_is_an_error():
    with pytest.raises(ValueError):
        pointer.gestures([ev("10:00:00", "wiggle", 1, 1)])


def test_stray_up_and_two_finger_sequence_do_not_raise():
    assert pointer.gestures([ev("10:00:00.0", "up")]) == []
    gs = pointer.gestures([ev("10:00:00.0", "down", 10, 10), ev("10:00:00.1", "down", 50, 50),
                     ev("10:00:00.2", "up"), ev("10:00:00.3", "up")])  # last `up` has nothing held
    assert len(gs) == 2 and gs[0]["t1"] == pytest.approx(common.hms("10:00:00.1"))


def test_events_missing_coordinates_name_the_gap():
    with pytest.raises(ValueError, match="x2"):
        pointer.gestures([ev("10:00:00", "swipe", 1, 1, y2=5)])
    with pytest.raises(ValueError, match="tap"):
        pointer.gestures([{"t": "10:00:00", "kind": "tap"}])
    with pytest.raises(ValueError, match="move .* lacks y"):
        pointer.gestures([{"t": "10:00:00", "kind": "move", "x": 1}])


def test_a_move_while_pressed_is_a_point_of_the_drag():
    (g,) = pointer.gestures([ev("10:00:01.0", "down", 100, 100), ev("10:00:01.2", "move", 300, 120), ev("10:00:01.5", "up")])
    assert g["kind"] == "drag" and g["pts"][-1][1:] == (300, 120)


def test_fmt_rounds_without_printing_sixty_seconds():
    assert common.fmt(common.hms("14:30:59.97")) == "14:31:00.0"
    assert common.fmt(common.hms("14:30:41.2")) == "14:30:41.2"
    assert common.fmt(common.hms("14:30:59.9996"), 3) == "14:31:00.000"
    assert common.fmt(86399.99) == "00:00:00.0"


def test_frame_indices_pick_nearest_frame_and_warn_outside_the_cut(capsys):
    start, ss = common.hms("10:00:00"), 2.0  # clip starts 2 s in, 300 frames at 30 fps
    assert a.frame_indices(["10:00:03.0", "10:00:02.0"], start, ss, 30, 300) == {30, 0}
    assert a.frame_indices(["10:00:01.0", "10:00:12.0"], start, ss, 30, 300) == set()  # before the cut, and past its end
    assert capsys.readouterr().err.count("outside the cut") == 2


def test_zoom_region_must_have_area(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps([{"from": "10:00:00", "to": "10:00:05", "title": "t", "zoom": [0, 0, 100, 0]}]))
    with pytest.raises(SystemExit):
        text.load_steps(tmp_path / "s.json")


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
    assert text.step_at(steps, 9.9) is None
    i, _, alpha = text.step_at(steps, 10.0)
    assert i == 0 and alpha == 0
    assert text.step_at(steps, 15.0)[2] == 1
    assert text.step_at(steps, 20.0)[0] == 1
    assert text.step_at(steps, 19.9)[2] == pytest.approx(0.1 / text.FADE_S)


def test_ease_is_clamped_smoothstep():
    assert (common.ease(-1), common.ease(0), common.ease(0.5), common.ease(1), common.ease(2)) == (0, 0, 0.5, 1, 1)


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
    start = common.hms("14:30:00")
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
    return pointer.Track(gs, a.load_style({"style": style}), lambda x, y: (x, y))


def test_track_rests_then_glides_to_arrive_on_the_next_press():
    gs = pointer.gestures([ev("10:00:01.0", "tap", 100, 100), ev("10:00:05.0", "tap", 500, 300)])
    tr = track(gs, cursor="cua")
    start, _, traj, _ = tr.glides[0]
    t1 = gs[1]["t0"]
    assert start == pytest.approx(t1 - traj.arrival)  # the move ends as the press starts
    assert tr.at(gs[0]["t0"] - 1)[:2] == (100, 100)  # before the first gesture: waits on it
    assert tr.at(start - 0.1)[:3] == (100, 100, pointer.cm.REST_HEADING)  # rests until the glide starts
    x, y, h, *_ = tr.at(start + traj.arrival / 2)
    assert 100 < x < 500 and h != pointer.cm.REST_HEADING  # leans into the move
    assert tr.at(t1)[:2] == pytest.approx((500, 300), abs=1)
    assert tr.at(t1 + 9)[:3] == (500, 300, pointer.cm.REST_HEADING)


def test_a_move_is_a_point_the_pointer_glides_to_without_pressing():
    items = pointer.gestures([ev("10:00:01.0", "tap", 100, 100), ev("10:00:03.0", "move", 600, 300), ev("10:00:06.0", "tap", 900, 500)])
    assert [g["kind"] for g in items] == ["tap", "move", "tap"] and len(pointer.presses(items)) == 2
    tr = track(items)
    t = common.hms("10:00:03.0")
    start, _, traj, _ = tr.glides[0]
    assert start == pytest.approx(t - traj.arrival)  # arrives as the move happens
    assert tr.at(t + 2)[:2] == pytest.approx((600, 300), abs=1)  # and rests there until the next glide
    assert pointer.press_k(pointer.presses(items), t) == 1  # a move does not press


def test_moves_alone_draw_the_pointer():
    from PIL import Image
    items = pointer.gestures([ev("10:00:01.0", "move", 640, 360)])
    p = a.Painter(1280, 720, SPACE, FONT)
    ov = Image.new("RGBA", (1280, 720))
    p.cursor(ov, p.track(items), pointer.presses(items), common.hms("10:00:02.0"))
    assert ov.getpixel((642, 364))[3] > 200  # the arrow rests with its tip on the point


def test_track_squeezes_a_glide_into_a_short_gap_and_skips_none():
    gs = pointer.gestures([ev("10:00:01.0", "tap", 100, 100), ev("10:00:01.3", "tap", 900, 600)])
    start, g, traj, _ = track(gs).glides[0]
    assert traj.arrival == pytest.approx(gs[1]["t0"] - gs[0]["t1"]) and start == pytest.approx(gs[0]["t1"])


def test_press_scale_shrinks_before_the_press_and_recovers_after_the_release():
    g = pointer.gestures([ev("10:00:01.0", "tap", 1, 1)])
    t0, t1 = g[0]["t0"], g[0]["t1"]
    assert pointer.press_k(g, t0 - pointer.PRESS_S - 0.01) == 1
    assert pointer.press_k(g, t0) == pytest.approx(pointer.PRESS_K)
    assert pointer.press_k(g, t1 + pointer.RELEASE_S * 0.6) > 1  # springs a little past full size
    assert pointer.press_k(g, t1 + pointer.RELEASE_S + 0.01) == 1
    quick = pointer.gestures([ev("10:00:01.0", "tap", 1, 1), ev("10:00:01.1", "tap", 1, 1)])
    assert min(pointer.press_k(quick, quick[0]["t0"] + k / 300) for k in range(300)) >= pointer.PRESS_K - 1e-9  # a rebound and a press never stack


def test_ring_shows_only_after_the_press():
    p = a.Painter(1280, 720, SPACE, FONT)
    from PIL import Image
    for age, drawn in ((-0.05, False), (0.1, True), (pointer.RING_S + 0.05, False)):
        ov = Image.new("RGBA", (1280, 720))
        p.ring(ov, 640, 360, age)
        assert (ov.getbbox() is not None) == drawn, age


def test_ring_starts_at_half_size_and_stays_clear_until_near_its_end():
    from PIL import Image
    p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"size": pointer.MARK_SIZE}}))
    def drawn(age):
        ov = Image.new("RGBA", (1280, 720))
        p.ring(ov, 640, 360, age)
        x0, _, x1, _ = ov.getbbox()
        return x1 - x0, int(np.asarray(ov)[:, :, 3].max())
    width, _ = drawn(0.01)
    assert width == pytest.approx(pointer.RING_R, rel=0.15)  # half of its full radius: a diameter of RING_R
    _, alpha = drawn(0.7 * pointer.RING_S)
    assert alpha > 140  # still a clear ring late in its run


def test_mouse_pointer_sprite_is_drawn_tip_first_and_clipped_at_the_edge():
    p = a.Painter(1280, 720, SPACE, FONT)
    from PIL import Image
    gs = pointer.gestures([ev("10:00:01.0", "tap", 1270, 710)])
    ov = Image.new("RGBA", (1280, 720))
    p.cursor(ov, p.track(gs), gs, gs[0]["t0"])  # near the corner: must not raise
    assert ov.getpixel((1271, 713))[3] > 200  # the tip sits on the press
    x0, y0, _, _ = ov.getbbox()
    assert x0 >= 1256 and y0 >= 698  # only the shadow's blur reaches past the tip


def test_glide_bows_unless_arc_is_zero_and_leans_unless_tilt_is_zero():
    gs = pointer.gestures([ev("10:00:01.0", "tap", 100, 300), ev("10:00:05.0", "tap", 900, 300)])
    def mid(**style):
        tr = track(gs, **{"cursor": "cua", **style})
        start, _, traj, _ = tr.glides[0]
        return tr.at(start + traj.arrival / 2)
    assert abs(mid()[1] - 300) > 30
    assert mid(cursor="mac")[2] == pointer.cm.REST_HEADING  # the mac arrow stays upright by default
    assert abs(mid(cursor="mac")[1] - 300) < abs(mid()[1] - 300)  # and bows less
    assert mid(arc=0)[1] == pytest.approx(300)
    assert mid(tilt=0)[2] == pointer.cm.REST_HEADING


def test_aim_mirrors_the_arrow_toward_a_target_on_its_right_and_back():
    gs = pointer.gestures([ev("10:00:01.0", "tap", 100, 300), ev("10:00:04.0", "tap", 900, 300), ev("10:00:07.0", "tap", 300, 300)])
    tr = track(gs, tilt="aim")
    mirror = pointer.AIM_TURN
    t = lambda s: common.hms(s)
    assert tr.aim(t("10:00:02.0")) == 0  # target to the left of nothing yet: the usual arrow
    peak = max(tr.aim(t("10:00:03.0") + k / 60) for k in range(120))
    assert tr.aim(t("10:00:06.0")) == pytest.approx(mirror, abs=0.01) and peak > mirror * 1.1  # overshoots, settles
    assert tr.aim(t("10:00:09.5")) == pytest.approx(0, abs=0.01)  # the next target lies left: back
    assert tr.at(t("10:00:03.5"))[2] == pointer.cm.REST_HEADING  # the glide itself does not lean


def test_aim_reversing_mid_swing_starts_from_where_the_arrow_is():
    gs = pointer.gestures([ev("10:00:01.0", "tap", 100, 300), ev("10:00:01.4", "tap", 900, 300), ev("10:00:01.8", "tap", 300, 300)])
    tr = track(gs, tilt="aim")
    ts = [common.hms("10:00:01.0") + k / 240 for k in range(600)]
    assert max(abs(tr.aim(u) - tr.aim(v)) for u, v in zip(ts, ts[1:])) < 0.05  # no jump between frames


def test_lean_grows_with_speed():
    gs = pointer.gestures([ev("10:00:01.0", "tap", 100, 300), ev("10:00:05.0", "tap", 1100, 300)])
    tr = track(gs, cursor="cua")
    start, _, traj, _ = tr.glides[0]
    turns = [abs(pointer.lean(traj, u, traj.sample_at(u)[3])) for u in (0.02, traj.arrival / 2)]
    assert turns[0] < 0.1 * turns[1] and turns[1] > 0.3  # barely turned while starting, leaning at full speed
    assert pointer.lean(None, 0, pointer.cm.REST_HEADING) == 0


def test_float_waits_for_the_first_move():
    from PIL import Image
    gs = pointer.gestures([ev("10:00:02.0", "tap", 100, 100), ev("10:00:04.0", "tap", 500, 300)])
    p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"float": True}}))
    p.cursor(Image.new("RGBA", (1280, 720)), track(gs, float=True), gs, common.hms("10:00:00.5"))  # raised on NaN before


def test_style_fills_defaults_and_rejects_bad_values():
    st = a.load_style({"style": {"cursor": "figma", "color": "#8b5cf6"}})
    assert st["color"] == (0x8B, 0x5C, 0xF6) and st["trail"] is None  # resolved by pointer: a mouse cursor draws no drag trail
    assert a.load_style({"style": {"cursor": "cua"}})["color"] == (0x5E, 0xC0, 0xE8)  # Cua blue by default
    for bad in ({"cursor": "windows"}, {"color": "blue"}, {"colour": "#000000"}, {"motion": "magnetic"}, {"tilt": 2}, {"dot": "yes"}, {"glow": 1}, {"size": 5}, {"click": "pop"}, {"label_text": "white"}, {"float": "false"}, {"trail": "no"}, {"label": 5}):
        with pytest.raises(SystemExit):
            a.load_style({"style": bad})



def test_preset_sets_the_look_and_style_overrides_it():
    for name in a.PRESETS:
        a.load_style({}, name)  # every preset passes validation
    st = a.load_style({"style": {"cursor": "cua", "zoom": 0}}, "demo")
    assert st["frame"] is not None and st["zoom"] == 0 and st["tilt"] == 1.0  # the overriding cursor brings its own tilt
    assert a.load_style({}, "demo")["tilt"] == "aim"
    with pytest.raises(SystemExit):
        a.load_style({}, "fancy")

@pytest.mark.parametrize("cursor", pointer.CURSORS)
def test_every_cursor_draws_its_tip_on_the_point_with_a_label(cursor):
    from PIL import Image
    p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"cursor": cursor, "label": "Claude"}}))
    gs = pointer.gestures([ev("10:00:01.0", "tap", 640, 360)])
    ov = Image.new("RGBA", (1280, 720))
    p.cursor(ov, p.track(gs), gs, gs[0]["t0"])
    assert ov.getpixel((643, 366) if cursor != "cua" else (646, 364))[3] > 200  # the pointer covers the press point
    (tx, ty), k = pointer.TAG[cursor]["at"], a.STYLE["size"]
    assert ov.getpixel((round(640 + tx * k + 8), round(360 + ty * k + 8)))[3] > 200  # the tag sits below right of the tip


def test_key_items_make_caps_and_join_close_typing():
    items = text.key_items([ev("10:00:01.0", "type", text="AB", ms=100), ev("10:00:01.5", "type", text="C"),
                         ev("10:00:05.0", "key", keys="Ctrl + S"), ev("10:00:09.0", "type", text="Z"),
                         ev("10:00:00.5", "tap", 1, 1)])
    assert len(items) == 3  # AB and C joined; the key; Z after a gap
    assert "".join(ch for _, ch in items[0]["chars"]) == "ABC" and items[0]["chars"][1][0] == pytest.approx(common.hms("10:00:01.05"))
    assert items[1]["caps"] == ["Ctrl", "S"]
    item, alpha = text.key_at(items, common.hms("10:00:05.5"))
    assert item is items[1] and alpha == 1
    assert text.key_at(items, common.hms("10:00:07.0")) is None
    with pytest.raises(ValueError):
        text.key_items([ev("10:00:01.0", "key")])


def test_gestures_skip_key_events():
    assert len(pointer.gestures([ev("10:00:01.0", "key", keys="Enter"), ev("10:00:02.0", "tap", 1, 1)])) == 1


def test_camera_holds_one_zoom_over_nearby_presses_and_stays_wide_for_spread_ones():
    t = lambda s: common.hms(s)
    gs = pointer.gestures([ev("10:00:02.0", "tap", 200, 200), ev("10:00:03.0", "tap", 300, 260),
                     ev("10:00:04.0", "tap", 260, 300), ev("10:00:20.0", "tap", 100, 100), ev("10:00:21.0", "tap", 1180, 620)])
    cam = a.Camera(gs, [], SPACE, 1.5)
    assert cam.region(t("10:00:00.5")) is None
    for s in ("10:00:02.0", "10:00:03.0", "10:00:04.0"):  # zoomed in on the cluster the whole time, no pumping
        x, y, w, h = cam.region(t(s))
        assert w == pytest.approx(1280 / 1.5, abs=8) and x <= 200 and 300 <= x + w
    assert cam.region(t("10:00:10.0")) is None  # out between the groups
    assert all(cam.region(t(s)) is None for s in ("10:00:20.0", "10:00:20.5", "10:00:21.0"))  # too far apart to frame


def test_camera_stays_wide_for_scattered_presses_in_a_busy_run():
    t = lambda s: common.hms(s)
    gs = pointer.gestures([ev("10:00:02.0", "tap", 100, 100), ev("10:00:04.2", "tap", 1180, 620),
                     ev("10:00:06.4", "tap", 100, 620), ev("10:00:08.6", "tap", 1180, 100)])
    cam = a.Camera(gs, [], SPACE, 1.5)
    assert all(cam.region(t(f"10:00:{s:04.1f}")) is None for s in (1.5, 2.0, 3.0, 4.2, 6.4, 8.6, 9.5))


def test_camera_fits_a_long_drag_and_restarts_when_time_goes_back():
    gs = pointer.gestures([ev("10:00:02.0", "swipe", 300, 360, x2=900, y2=360, ms=500)])
    cam = a.Camera(gs, [], SPACE, 2.5)
    _, _, w, _ = cam.region(common.hms("10:00:02.3"))
    assert w == pytest.approx(600 * a.CAM_PAD, rel=0.02)
    assert cam.region(common.hms("10:00:00.0")) is None


def test_rest_counts_from_the_last_move_to_the_next():
    gs = pointer.gestures([ev("10:00:01.0", "tap", 100, 100), ev("10:00:09.0", "tap", 900, 600)])
    tr = track(gs)
    start = tr.glides[0][0]
    since, until = tr.rest(common.hms("10:00:03.0"))
    assert since == pytest.approx(common.hms("10:00:03.0") - gs[0]["t1"]) and until == pytest.approx(start - common.hms("10:00:03.0"))
    assert tr.rest(gs[1]["t0"]) == (0, 0)


def test_idle_fade_hides_a_resting_pointer_and_brings_it_back_before_it_moves():
    from PIL import Image
    gs = pointer.gestures([ev("10:00:01.0", "tap", 300, 300), ev("10:00:09.0", "tap", 900, 600)])
    p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"idle_fade": 1.5}}))
    tr = p.track(gs)
    def drawn(t):
        ov = Image.new("RGBA", (1280, 720))
        p.cursor(ov, tr, gs, t)
        return ov.getbbox() is not None
    assert drawn(common.hms("10:00:01.5")) and not drawn(common.hms("10:00:05.0")) and drawn(tr.glides[0][0])


def test_idle_spans_cover_only_long_quiet_gaps_inside_their_edges():
    gs = pointer.gestures([ev("10:00:01.0", "tap", 1, 1), ev("10:00:03.0", "tap", 1, 1), ev("10:00:20.0", "tap", 1, 1)])
    keys = text.key_items([ev("10:00:10.0", "key", keys="Enter")])
    spans = a.idle_spans(gs, keys, [], 2.0)
    end3 = gs[1]["t1"] + 1.0
    assert spans == [pytest.approx((end3 + 0.3, common.hms("10:00:10.0") - 0.3 - 0.3)),
                     pytest.approx((common.hms("10:00:11.0") + 0.3, common.hms("10:00:20.0") - 0.8 - 0.3))]


def test_idle_spans_hold_a_step_caption_while_it_is_read():
    keys = text.key_items([ev("10:00:30.0", "key", keys="Enter")])
    def quiet_from(title, to="10:00:29.0"):
        steps = [{"from": common.hms("10:00:01.0"), "to": common.hms(to), "title": title}]
        return a.idle_spans([], keys, steps, 2.0)[0][0]
    t = common.hms("10:00:01.0") + a.IDLE_EDGE_S
    assert quiet_from("Save") == pytest.approx(t + 2.5)  # a short title: the 2.5 s floor
    assert quiet_from("x" * 30) == pytest.approx(t + 6.5)  # 1.5 s plus a second per 6 characters
    assert quiet_from("x" * 120) == pytest.approx(t + 9)  # a long one stops at 9 s
    assert quiet_from("x" * 120, "10:00:05.0") == pytest.approx(common.hms("10:00:05.0") + a.IDLE_EDGE_S)  # never past the step


def test_framer_pads_keeps_the_frame_and_rounds_its_corners():
    f = a.Framer(1280, 720, [(109, 93, 252), (242, 123, 155)])
    out = f(np.full((720, 1280, 3), 200, np.uint8))
    assert out.shape == (f.h, f.w, 3) and f.w % 2 == 0 and f.h % 2 == 0
    assert (out[f.py + 360, f.px + 640] == 200).all()  # content untouched
    assert not (out[f.py, f.px] == 200).all()  # the corner is cut round
    assert tuple(a.load_style({"style": {"frame": ["#6d5dfc", "#f27b9b"]}})["frame"][0]) == (0x6D, 0x5D, 0xFC)
    with pytest.raises(SystemExit):
        a.load_style({"style": {"frame": "pink"}})


def test_step_anchor_is_the_first_press_inside_else_the_first_box():
    gs = pointer.gestures([ev("10:00:01.0", "tap", 10, 20), ev("10:00:03.0", "tap", 300, 400)])
    st = {"from": common.hms("10:00:02.0"), "to": common.hms("10:00:05.0"), "boxes": [[0, 0, 100, 50]]}
    assert a.step_anchor(st, gs) == (300, 400)
    assert a.step_anchor({**st, "from": common.hms("10:00:04.0")}, gs) == (50, 25)
    assert a.step_anchor({"from": 0, "to": 1}, gs) is None


@pytest.mark.parametrize("kind", ["pill", "chapter", "callout"])
def test_every_caption_draws_where_its_kind_puts_it(kind):
    from PIL import Image
    p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"caption": kind}}))
    ov = Image.new("RGBA", (1280, 720))
    step = {"from": 1.0, "to": 5.0, "title": "Save", "note": "closes the form"}
    edge = text.CAP_EDGE * 18 / text.CAPTION_DESIGN
    if kind == "callout":
        p.callout(ov, step, 2, 3, 1.0, (900, 400))
        x0, y0, x1, y1 = ov.getbbox()
        assert x1 < 900 and y0 < 400 < y1  # left of the press, level with it
        return
    blk = p.caption_block(step, 2, 3)
    x, y, w, h = p.blocks(ov, [blk], 3.0, {})[id(blk)]
    if kind == "pill":
        assert x + w / 2 == pytest.approx(640, abs=1) and y + h == pytest.approx(720 - edge, abs=1)
    else:
        assert (x, y) == (pytest.approx(edge, abs=1), pytest.approx(edge, abs=1))
    assert a.load_style({"style": {"caption": "none"}})["caption"] == "none"


def test_a_step_tag_takes_the_place_of_its_number():
    p = a.Painter(1280, 720, SPACE, FONT)
    step = {"from": 1.0, "to": 5.0, "title": "Save", "tag": "結果"}
    parts = p.caption_block(step, 2, 3)["lines"][0]
    assert [q.get("text") for q in parts if "text" in q] == ["結果", "Save"]
    assert text.step_label([step], (0, step, 1.0)) == "結果"
    assert text.step_label([{}, {}], (0, {}, 1.0)) == "步驟 1/2" and text.step_label([], None) == ""


def test_blocks_stack_at_their_anchor_and_sit_beside_when_asked():
    from PIL import Image
    p = a.Painter(1280, 720, SPACE, FONT)
    b = lambda **k: text.check_block({"lines": ["x"], **k}, "test")
    top1, top2 = b(at="top-right"), b(at="top-right", lines=["one", "two"])
    low1, low2 = b(at="bottom-left"), b(at="bottom-left", beside=True)
    ov = Image.new("RGBA", (1280, 720))
    at = p.blocks(ov, [top1, top2, low1, low2], 0, {})
    (x1, y1, w1, h1), (_, y2, _, h2) = at[id(top1)], at[id(top2)]
    assert x1 + w1 == pytest.approx(1270, abs=1) and y1 == pytest.approx(10, abs=1)  # 10 px off the corner
    assert y2 == pytest.approx(y1 + h1 + text.ROW_GAP, abs=1) and h2 > h1  # the next one under it, two lines tall
    (lx, ly, lw, lh), (bx, by, _, bh) = at[id(low1)], at[id(low2)]
    assert by + bh == pytest.approx(ly + lh, abs=1) and bx == pytest.approx(lx + lw + text.SIDE_GAP, abs=1)  # beside


def test_block_lines_take_tokens_parts_bullets_and_end_in_an_ellipsis_when_long():
    p = a.Painter(1280, 720, SPACE, FONT)
    b = text.check_block({"lines": [["{clock}", "{step}", "{speed}"]], "sep": " · "}, "test")
    narrow = p.block_image(b, {"clock": "10:00:00.0", "step": "", "speed": ""}).width
    wide = p.block_image(b, {"clock": "10:00:00.0", "step": "步驟 1/2", "speed": ""}).width
    assert wide > narrow  # an empty token drops its part and its separator
    assert p.block_image(text.check_block({"lines": ["{speed}"]}, "t"), {"speed": ""}) is None  # nothing to show
    long = text.check_block({"lines": ["x" * 400], "max_w": 200}, "test")
    assert p.block_image(long, {}).width <= 200 + 1
    fact = text.check_block({"lines": [[{"text": "排序：", "color": "#aeb4bc"}, {"text": "true", "color": "#5bd07a", "bold": True}]],
                             "bullets": True}, "test")
    assert p.block_image(fact, {}) is not None
    for bad in ({"at": "middle"}, {"colour": "#fff"}, {"bar": "#d97757"}, {"bg": "black"}, {"rect": [0, 0, 0, 5]}, {"lines": [[{"txt": "x"}]]}):
        with pytest.raises(SystemExit):
            text.check_block(bad, "test")


def test_wrap_breaks_between_characters_keeps_words_and_punctuation_and_cuts_past_max_lines():
    m = lambda f, t: 10 * len(t)  # every character 10 px
    item = lambda t: [{"text": t}, None, 10 * len(t)]
    rows_of = lambda rows: [[q["text"] for q, _, _ in r] for _, r in rows]
    assert rows_of(text.wrap([item("一二三四五六七八")], 50, 2, 0, m)) == [["一二三四五"], ["六七八"]]
    assert rows_of(text.wrap([item("一二三四，五六")], 40, 3, 0, m)) == [["一二三"], ["四，五六"]]  # no row starts with ，
    assert rows_of(text.wrap([item("open the door now")], 120, 3, 0, m)) == [["open the"], ["door now"]]  # door kept whole
    one = rows_of(text.wrap([item("一二三四五六七八九十")], 50, 1, 0, m))
    assert one == [["一二三四…"]]  # one row: cut to fit, with an ellipsis
    two = rows_of(text.wrap([item("一二三四五六七八九十一二三四五")], 50, 2, 0, m))
    assert two == [["一二三四五"], ["六七八九…"]]
    hang = text.wrap([item("• "), item("一二三四五六")], 50, 2, 0, m, indent=20)
    assert rows_of(hang) == [["• ", "一二三"], ["四五六"]] and hang[1][0] == 20  # the next row hangs under the text


def test_blocks_in_one_row_make_way_left_for_centre_and_right():
    from PIL import Image
    p = a.Painter(1280, 720, SPACE, FONT)
    b = lambda **k: text.check_block(k, "test")
    long, mid, right = b(at="top-left", lines=["x" * 300]), b(at="top", lines=["centre"]), b(at="top-right", lines=["right"])
    at = p.blocks(Image.new("RGBA", (1280, 720)), [long, mid, right], 0, {})
    (lx, _, lw, _), (mx, _, mw, _), (rx, _, _, _) = at[id(long)], at[id(mid)], at[id(right)]
    assert lx + lw <= mx - text.SIDE_GAP + 1 and mx + mw <= rx  # the long one stops short of the centre one
    wide, r2 = b(at="top", lines=["y" * 200]), b(at="top-right", lines=["right side"])
    at = p.blocks(Image.new("RGBA", (1280, 720)), [wide, r2], 0, {})
    assert at[id(wide)][0] + at[id(wide)][2] <= at[id(r2)][0]  # a centre block makes way for a right one
    cut, wrapped = b(at="bottom-left", lines=["x" * 300]), b(at="bottom-left", lines=["x" * 300], max_lines=3)
    h_cut = p.blocks(Image.new("RGBA", (1280, 720)), [cut, b(at="bottom", lines=["c"])], 0, {})[id(cut)][3]
    h_wrap = p.blocks(Image.new("RGBA", (1280, 720)), [wrapped, b(at="bottom", lines=["c"])], 0, {})[id(wrapped)][3]
    assert h_wrap > 2 * h_cut  # with max_lines it wraps into rows instead of one cut row
    with pytest.raises(SystemExit):
        text.check_block({"max_lines": 0}, "test")


def test_a_cover_fills_its_rect_on_the_recording_through_the_zoom():
    from PIL import Image
    p = a.Painter(1280, 720, SPACE, FONT)
    cov = text.check_block({"rect": [100, 600, 200, 50], "bg": "#15181e", "lines": ["new"]}, "test")
    ov = Image.new("RGBA", (1280, 720))
    p.cover(ov, cov, 0, {}, SPACE)
    assert ov.getbbox() == (100, 600, 300, 650) and ov.getpixel((110, 640)) == (0x15, 0x18, 0x1E, 255)
    p.view = (0, 360, 2, 2)  # zoomed 2x into the lower left
    ov = Image.new("RGBA", (1280, 720))
    p.cover(ov, cov, 0, {}, SPACE)
    assert ov.getbbox()[:2] == (200, 480)


def test_load_blocks_reads_the_canvas_and_the_blocks(tmp_path):
    f = tmp_path / "blocks.json"
    f.write_text(json.dumps({"canvas": {"top": 40, "bottom": 40}, "blocks": [{"from": "10:00:01", "to": "10:00:03", "lines": ["hi"]}]}))
    canvas, blocks, space = text.load_blocks(f)
    assert canvas == {"top": 40, "bottom": 40, "left": 0, "right": 0, "color": (0x11, 0x13, 0x18)} and space is None
    assert blocks[0]["from"] == common.hms("10:00:01") and blocks[0]["lines"] == [[{"text": "hi"}]]
    f.write_text(json.dumps({"canvas": {"top": -1}}))
    with pytest.raises(SystemExit):
        text.load_blocks(f)


def test_idle_spans_hold_a_block_while_it_is_read():
    keys = text.key_items([ev("10:00:30.0", "key", keys="Enter")])
    blk = text.check_block({"from": "10:00:01.0", "lines": ["x" * 30]}, "test")
    quiet = a.idle_spans([], keys, [], 2.0, [blk])[0][0]
    assert quiet == pytest.approx(common.hms("10:00:01.0") + 6.5 + a.IDLE_EDGE_S)
    assert a.idle_spans([], keys, [], 2.0, [{**blk, "read": False}]) == []


def test_the_corner_is_a_block_that_style_can_change_or_drop():
    assert a.load_style({})["corner"]["at"] == "bottom-left"
    assert a.load_style({"style": {"corner": {"at": "top-right"}}})["corner"]["at"] == "top-right"
    assert a.load_style({"style": {"corner": False}})["corner"] is False
    with pytest.raises(SystemExit):
        a.load_style({"style": {"corner": "yes"}})


def test_caption_size_scales_the_capsule_and_the_key_pill():
    from PIL import Image
    def heights(size):
        p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"caption_size": size}}))
        ov = Image.new("RGBA", (1280, 720))
        p.keys(ov, {"caps": ["Ctrl", "S"]}, 0, 1.0, 700)
        _, y0, _, y1 = ov.getbbox()
        return p.capsule(1, 2, "Save").height, y1 - y0
    small, big = heights(18), heights(36)
    assert big[0] == pytest.approx(2 * small[0], abs=2) and big[1] == pytest.approx(2 * small[1], abs=2)
    assert a.load_style({})["caption_size"] == 18
    with pytest.raises(SystemExit):
        a.load_style({"style": {"caption_size": 4}})


def test_dot_adds_an_amber_dot_before_the_step_number():
    def amber(dot):
        p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"dot": dot}}))
        r, g, b, al = np.asarray(p.capsule(2, 5, "Save")).astype(int).transpose(2, 0, 1)
        return int(((al > 200) & (r > 230) & (g > 170) & (g < 220) & (b < 100)).sum())
    assert amber(False) == 0 < amber(True)


def test_zoom_true_is_the_default_magnification():
    assert a.load_style({"style": {"zoom": True}})["zoom"] == a.ZOOM_DEFAULT
    assert a.load_style({"style": {"zoom": False}})["zoom"] == 0


def test_name_tag_trails_the_arrow():
    w, h, s = 120, 35, 1.0
    assert pointer.tag_at(w, h, 0, s) == (58, 60)  # at rest: at the arrow's corner, below right of the tip
    x, y = pointer.tag_at(w, h, np.pi, s)  # turned half round: above left, clear of the tip
    assert x + w < 0 and y + h < 0
    x, y = pointer.tag_at(w, h, np.pi / 2 - np.arctan2(60, 58), s)  # body straight below (aimed): below, its right edge a third of the gap past the tip
    assert y > 0 and abs(x + w - np.hypot(58, 60) / 3) <= 1



def test_cua_click_sparks_off_the_tip_without_a_ring():
    from PIL import Image, ImageDraw
    p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"cursor": "cua"}}))
    g = pointer.gestures([ev("10:00:01.0", "tap", 640, 360)])[0]
    ov = Image.new("RGBA", (1280, 720))
    p.gesture(ov, ImageDraw.Draw(ov), g, g["t0"] + 0.05, "mouse")
    assert ov.getbbox() is not None and ov.getbbox()[2] < 640 + 5  # strokes up and left of the tip, no ring round it


def test_label_colours_override_the_pointer_colour():
    p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"cursor": "figma", "label": "Kerati", "label_color": "#ffffff", "label_text": "#000000"}}))
    im, m = p.tag()
    assert im.getpixel((m + 2, m + im.height // 4))[:3] == (255, 255, 255)  # the tag's fill, not the pointer's blue


def test_bad_style_shapes_are_errors_not_tracebacks():
    with pytest.raises(SystemExit):
        a.load_style({"style": "demo"})


def test_a_step_zoom_eases_from_the_camera_view_not_the_full_frame():
    step = {"from": 1.0, "to": 5.0, "zoom": [100, 100, 400, 225]}
    view = (200, 60, 640, 360)
    assert a.zoom_region(step, 1.0, SPACE, view) == pytest.approx(view)  # no jump when the step starts or ends
    assert a.zoom_region(step, 5.0, SPACE, view) == pytest.approx(view)


def test_the_touch_dot_and_ring_follow_size():
    from PIL import Image, ImageDraw
    g = pointer.gestures([ev("10:00:01.0", "down", 640, 360), ev("10:00:02.0", "up")])[0]  # a hold: the dot alone between its rings
    def width(size, t):
        p = a.Painter(1280, 720, SPACE, FONT, a.load_style({"style": {"size": size}}))
        ov = Image.new("RGBA", (1280, 720))
        p.gesture(ov, ImageDraw.Draw(ov), g, g["t0"] + t, "touch")
        x0, _, x1, _ = ov.getbbox()
        return x1 - x0
    assert 36 <= width(0.6, 0.6) <= 46  # a dot of 22 px radius (28 drew 50) at MARK_SIZE
    assert width(1.2, 0.6) == pytest.approx(2 * width(0.6, 0.6), abs=4)
    assert width(1.2, 0.3) == pytest.approx(2 * width(0.6, 0.3), abs=6)  # the ring grows with it
    assert width(0.6, 0.3) == pytest.approx(2 * pointer.RING_R, rel=0.1)  # nearly grown: RING_R at MARK_SIZE
