# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""cursor_motion.py against Cua Driver's golden trajectories (golden_cua.json: one case per style and timing
of the ported styles, cut from cua-cursor-motion/fixtures/golden.json).

uv run test_cursor_motion.py
"""
import json
import sys
from pathlib import Path

import pytest

import cursor_motion as cm

GOLDEN = json.loads((Path(__file__).with_name("golden_cua.json")).read_text(encoding="utf-8"))
TOL = 1e-6


def plan(c):
    p, r = c["params"], c["request"]
    return cm.plan(r["from"], r["to"], p["style"], p["timing"], r.get("target"), p["arc_size"], p["arc_flow"],
                   p["start_handle"], p["end_handle"], p["glide_duration_ms"],
                   r.get("from_heading", cm.REST_HEADING), r.get("end_heading", cm.REST_HEADING),
                   effects={k: v for k, v in p["effects"].items() if v is not None})


@pytest.mark.parametrize("c", GOLDEN["cases"], ids=lambda c: c["name"])
def test_plan_matches_the_rust_crate(c):
    traj, out = plan(c), c["out"]
    assert len(traj.samples) == out["samples"]
    assert traj.duration() == pytest.approx(out["duration"], abs=TOL)
    assert traj.arrival == pytest.approx(out["arrival_t"], abs=TOL)
    assert traj.effects == {k for k, on in out["effects"].items() if on and k in ("glow", "trail")}
    d = traj.duration()
    for i, want in enumerate(out["grid"]):
        assert traj.sample_at(d * i / GOLDEN["grid"]) == pytest.approx(want, abs=TOL), i
    for k, f in zip((0.2, 0.5, 0.8, 1.0), out.get("frames", [])):
        s = traj.sample_at(d * k)
        g = cm.glow(traj, d * k, cm.anchor(*s[1:]))
        assert (g is None) == (f["frame"]["glow"] is None) or "glow" not in traj.effects
        if g and f["frame"]["glow"]:
            assert g == pytest.approx(f["frame"]["glow"], abs=TOL)
        if "trail" in traj.effects:
            got = [v for a, b, w, al in cm.trail(traj, d * k) for v in (*a, *b, w, al)]
            assert got == pytest.approx([v for seg in f["frame"]["trail"] for v in seg], abs=TOL)


def test_tilt_zero_keeps_the_rest_pose():
    traj = cm.plan((100, 100), (700, 400), tilt=0)
    assert all(h == pytest.approx(cm.REST_HEADING) for *_, h in traj.samples)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
