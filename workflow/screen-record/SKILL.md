---
name: screen-record
description: Record one window to MP4 with ffmpeg, for live-test evidence. Use to record a window or a test run, start or stop a recording, or check one is running; the clip then goes to evidence-annotate.
---

`scripts/screenrec.py` records one window with ffmpeg's `gfxcapture` source (Windows Graphics Capture: sees GPU-rendered and covered windows, no cursor), scaled to 720 px high at 30 fps, encoded with `h264_nvenc` when a probe encode works, else `libx264`. It writes `.mkv` (survives a hard kill); `stop` ends ffmpeg cleanly and remuxes to `.mp4` with `-c copy`. Windows only; needs ffmpeg 8+ on PATH (`ffmpeg -h filter=gfxcapture` prints the filter). `uv run` needs no packages.

`<skill>` is this skill's folder; run the commands from anywhere.

```
uv run <skill>/scripts/screenrec.py start --window <title substring> --out <dir> [--profile <name>] [--crop-top N] [--keep-gb 20] [--min-free-gb 30] [--encoder auto|nvenc|x264]
uv run <skill>/scripts/screenrec.py status [--profile <name>]
uv run <skill>/scripts/screenrec.py stop   [--profile <name>]
```

- `--window`: a case-insensitive title substring; several matches pick the largest. `--crop-top N` cuts N pixels off the top of the window (a title bar). `--out` is the recording folder.
- `--profile` only names the state file in `--out` (default `default`); use two names to run two recordings at once, and pass the same name to `status` and `stop`.
- `--encoder` defaults to `auto` (NVENC if a one-frame probe encode works, else x264). `--keep-gb` deletes the oldest `rec_*.mp4` in `--out` beyond that size, never other files; `--min-free-gb` refuses to start on a fuller disk.

1. **Check the target.** The window must be visible and un-minimised for the whole recording. Done: `start` does not exit with "minimised" or "no visible window".
2. **Start.** Run `start`. It exits non-zero with the reason on a minimised window, a black first frame, or no frame within 10 s (the capture does not see the window, or the window is not redrawing), a window already recording under that profile, or low disk. Done: it prints `recording since HH:MM:SS.mmm -> <file>.mkv`; after a refusal, fix the cause and rerun.
3. **Run the thing being recorded**, and note the wall-clock time of each event you want annotated. Done: `status` prints `active True`.
4. **Stop.** Run `stop`. Done: it prints `saved <file>.mp4` and `started <time>`, and `ffprobe` on the file shows a duration close to the elapsed time. The printed start is `--start` for `evidence-annotate`, good to about half a second (ffmpeg's start-up); fix a constant drift there with its `--offset`.

`gfxcapture` delivers a frame only when the window repaints: a static window yields few or no frames and a clip shorter than the wall time, and a desktop with no active display yields none at all. Record windows that animate (an emulator, a game, a running app), not an idle editor.

A stop that prints "recorder did not finish" leaves the `.mkv` in `--out`; remux it by hand with `ffmpeg -i <file>.mkv -c copy <file>.mp4`.
