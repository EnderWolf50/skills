---
name: evidence-annotate
description: Burn touches, step captions, boxes, zoom and privacy masks into a screen recording or a still. Use to annotate a clip, make an annotated still, show what a test or bot did on screen, or mask private information (account names, numbers, e-mails) before a recording or screenshot is shared.
---

`scripts/annotate.py` re-encodes a recording with a virtual finger (tap ripples, drag trails), numbered step captions with a note, labelled boxes, an eased zoom into a region, and blacked-out private regions. The project supplies what is specific to it: the events, the steps, the masks. Needs `ffmpeg` and `ffprobe` on PATH; `uv run` installs the Python side. Recordings come from `screen-record`.

```
uv run <skill>/scripts/annotate.py VIDEO -o OUT --start HH:MM:SS[.fff] --events events.json \
    [--steps steps.json] [--masks masks.json] [--from T --to T] [--frames T,T,...] [--offset S] [--font FILE] [--no-video]
```

All times are wall-clock times of the same clock. `--start` is the wall time of the video's first frame (the OBS file name carries it); `--from`/`--to` cut a clip; `--frames` also saves those annotated frames as PNG beside `OUT`. `--no-video` writes only those stills (a still = `--frames T --no-video`, cut with `--from/--to` so the scan stays short). `--offset S` is the calibration knob: seconds added to every event time. `--font` takes a CJK font file; without it the first of the usual Windows and Linux ones is used. The encoder is NVENC when ffmpeg has it, else libx264. Examples of all three files: `examples/`.

- `events.json`: `{"space":[w,h],"events":[{"t":"HH:MM:SS.fff","kind":"tap|swipe|down|up","x":..,"y":..,"x2":..,"y2":..,"ms":..}]}`. Coordinates are in `space` (the app's own pixel grid) and map to the frame by its size, so a 1920x1080 log works on a 1280x720 clip. `swipe` runs `x,y` to `x2,y2` over `ms`; `down`/`up` bracket a press (`up` may carry the release point `x,y`); a press without movement past 0.3 s shows as a hold. One finger at a time.
- `steps.json`: `[{"from","to","title","note"?,"boxes"?:[[x,y,w,h,"label"]],"zoom"?:[x,y,w,h]}]` in the events' space. Steps are numbered in list order; `zoom` eases into that region for the step and back out.
- `masks.json`: `{"space":[w,h],"masks":[{"template":"<png>","threshold":0.8,"boxes":[[x,y,w,h]]}]}`. A box is blacked out while its template (cropped from a frame, at `space` scale) matches anywhere in the frame: scanned at 2 fps, each hit covers ±1 s. Template paths are relative to the masks file.

1. **Collect the events** from whatever the project logs (input log, test harness, tool trace) into `events.json`, in the log's own coordinate space; a script converting the log is the project's, not this skill's. Done: every gesture to show is an entry, and `space` is the grid the log used.
2. **Write the steps** for the moments the viewer must follow, one caption each, boxes around what to look at. Done: each step's `from`/`to` lies inside the clip.
3. **Write the masks before anything is shared.** Crop one template per private screen (a stable element that appears only with the private data) and box the data. Done: a `--frames` still taken on each such screen shows the boxes black; a screen the templates do not cover is a leak, so add a template.
4. **Render a short cut first** (`--from/--to` around two or three steps, `--frames` inside them) and open the stills. Done: taps land on what was tapped; a consistent early or late drift is fixed with `--offset`, not by editing events.
5. **Render the full clip**, or the stills only. Done: `OUT` plays and its length equals the cut.

Boxes drawn on a recording are annotation: a recording that carries private data stays unshared until step 3 passes on its stills.
