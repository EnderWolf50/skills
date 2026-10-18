---
name: screen-record
description: Windows only. Record one window to MP4 with ffmpeg, for live-test evidence. Use to record a window or a test run, start or stop a recording, or check one is running; the clip then goes to evidence-annotate.
---

`scripts/screenrec.py` records one window with ffmpeg's `gfxcapture` source (Windows Graphics Capture: sees GPU-rendered and covered windows, no cursor), scaled to 720 px high at 30 fps, encoded with `h264_nvenc` when a probe encode works, else `libx264`. It writes `.mkv` (survives a hard kill); `stop` ends ffmpeg cleanly and remuxes to `.mp4` with `-c copy`. Needs ffmpeg 8+ on PATH (`ffmpeg -h filter=gfxcapture` prints the filter). `uv run` needs no packages.

`<skill>` is this skill's folder; run the commands from anywhere.

```
uv run <skill>/scripts/screenrec.py start --window <title substring> --out <dir> [--profile <name>] [--crop-top N] [--keep-gb 20] [--min-free-gb 30] [--encoder auto|nvenc|x264]
uv run <skill>/scripts/screenrec.py status [--profile <name>]
uv run <skill>/scripts/screenrec.py stop   [--profile <name>]
```

- `--window`: a case-insensitive title substring; several matches pick the largest. `--crop-top N` cuts N physical pixels off the top of the window (a title bar), correct at any display scaling.
- `--profile` (letters, digits, `_`, `-`; default `default`) only names the state file, so two recordings can run at once; pass the same name to `status` and `stop`. A profile that is still recording refuses `start`, whatever its `--out`.
- `--encoder` defaults to `auto` (NVENC if a one-frame probe encode works, else x264). `--keep-gb` deletes the oldest `rec_<profile>_<date>_<time>.mp4` in `--out` beyond that size, never other files; `--min-free-gb` refuses to start on a fuller disk.

1. **Start.** The target window must stay visible and un-minimised for the whole recording. Run `start`. It exits non-zero with the reason on a minimised or missing window, a black first frame, no frame within 10 s (the window is not redrawing, or the capture cannot see it), a profile already recording, or low disk. Done: it prints `recording since HH:MM:SS.mmm -> <file>.mkv`; after a refusal, fix the cause and rerun.
2. **Run the thing being recorded**, and note the wall-clock time of each event you want annotated. Done: `status` prints `active True`.
3. **Stop.** Run `stop`. Done: it prints `saved <file>.mp4` and `started <time>`. The printed start is `--start` for `evidence-annotate`, good to about half a second (ffmpeg's start-up); fix a constant drift there with its `--offset`.

`gfxcapture` delivers a frame only when the window repaints: a static window yields few or no frames and a clip shorter than the wall time, and a desktop whose display is asleep yields none at all. Record windows that animate (an emulator, a game, a running app), not an idle editor.

**Recovering.** `stop` handles a recorder that died: if the runner process is gone but ffmpeg still records, it kills ffmpeg and remuxes the `.mkv`; if nothing was written it removes the stale state and says so. A `start` that says "recorder did not start" killed what it launched and leaves nothing blocking; fix the cause (see `rec_<profile>.log` in `--out`) and rerun. If `stop` still fails, remux by hand with `ffmpeg -i <file>.mkv -c copy <file>.mp4`, then delete `rec_<profile>.state.json` in `--out` and the `screenrec-<profile>.out` file in the system temp folder.
