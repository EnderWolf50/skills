---
name: screen-record
description: Record one window to MP4 with OBS on its own profile, without disturbing the user's OBS. Use to record a window or a live test run as evidence, start or stop a recording, or check one is running; the clip then goes to evidence-annotate.
---

`scripts/obsrec.py` drives OBS through obs-websocket: it writes a profile and scene collection named by you (window capture, NVENC H.264, 1280x720 at 30 fps, hybrid MP4 split at 2 GB), launches OBS on them, records, and on `stop` puts the user's own OBS profile back. Windows only. Needs OBS 28+ with its websocket server enabled once (OBS > Tools > WebSocket Server Settings); `uv run` installs the Python side.

Run it from the skill folder (`<skill>` below):

```
uv run <skill>/scripts/obsrec.py start --window <title substring> --profile <name> [--crop-top N] --out <dir>
uv run <skill>/scripts/obsrec.py status
uv run <skill>/scripts/obsrec.py stop
```

- `--window`: a case-insensitive title substring; several matches pick the largest. `--profile` names both the profile and the scene collection it creates (reused on later runs, so the project picks one stable name). `--crop-top N` cuts N pixels off the top of the window (a title bar). `--out` is the recording folder.
- `--keep-gb` (default 20) prunes the oldest `*.mp4` in `--out`; `--min-free-gb` (default 30) refuses to start on a fuller disk; `--obs-exe` overrides the OBS path.

1. **Check the target.** The window must be visible and un-minimised for the whole recording. Done: `start` prints `window '<title>' WxH, canvas ... -> 1280x720`.
2. **Start.** Run `start`; it exits non-zero, with the reason, on a minimised window, on OBS already running under another profile (never touch that one), on a black 1-second test frame (the capture does not see the window), on low disk. Done: it prints `recording True`; on a refusal, fix the cause and rerun, and leave the running OBS alone.
3. **Run the thing being recorded**, then note its wall-clock start and the events you want annotated.
4. **Stop.** Run `stop`. Done: it prints `saved <path>`, no `obs64.exe` is left running, and the user's `user.ini` is back. The file is named `YYYY-MM-DD_HH-MM-SS.mp4` after its first frame: that time is `--start` for `evidence-annotate`.

OBS may be set to run as administrator; `obsrec.py` then starts and closes it through a `runas` prompt (silent with UAC at its lowest). The `user.ini` copy is kept in `--out` as `user.ini.saved`: delete a stale one when the user's own profile changed since.
