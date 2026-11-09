# Blocks: `--blocks blocks.json`

Text a project lays out itself, drawn in the skill's fonts and look: a header over the recording, a status panel, a list of facts, its own captions, a cover over stale on-screen text. The project says what each block holds and where it goes; the skill sizes, places, fades and times it.

```json
{"canvas": {"top": 40, "bottom": 40, "color": "#15181e"},
 "blocks": [
  {"at": "top-left", "size": 17, "margin": 8, "bg": null,
   "lines": [[{"text": "T12", "bold": true, "color": "#d97757"}, "  依狀態查詢：只列出進行中的案件"]]},
  {"from": "10:00:24", "to": "10:00:31", "at": "top-right", "margin": 0, "radius": 0, "bg": "#262b33",
   "lines": [[{"text": "tester-1", "color": "#aeb4bc"}],
             [{"text": "結果 ", "bold": true}, {"text": "PASS", "bold": true, "color": "#5bd07a"}, {"text": "  {speed}", "color": "#ffc040"}]]},
  {"from": "10:00:24", "to": "10:00:31", "at": "top-right", "radius": 0, "bg": "#262b33", "bullets": true,
   "lines": [[{"text": "排序：", "color": "#aeb4bc"}, "重要性 降冪"], [{"text": "前三筆：", "color": "#aeb4bc"}, "案件A > 案件B > 案件C"]]},
  {"from": "10:00:24", "to": "10:00:31", "at": "bottom-left", "beside": true, "lines": ["依「重要性」降冪排序"]},
  {"from": "10:00:20", "to": "10:00:31", "rect": [0, 690, 1280, 30], "bg": "#15181e", "read": false}
 ]}
```

Colours are `#rrggbb` or `#rrggbbaa`. Sizes and distances are px at 1280 wide and scale with the recording's width.

- `canvas`: bands added round the recording, `top`, `bottom`, `left`, `right` (default 0), in `color` (default `#111318`). The output grows by them; the recording keeps its size, the events their space, and the zoom and masks touch only the recording.
- `space`: the grid a `rect` is written in (default the events' `space`).
- A block:
  - `from`, `to`: the wall times it shows between (default the whole clip), fading in and out. With a `from` it counts as a caption for `--idle-speed`, held while it is read, unless `read` is `false`.
  - `area`: `frame` (default) anchors the block to the whole output, bands included; `video` to the recording inside the bands, so a `top-right` block sits on the picture's corner rather than in a band.
  - `at`: where in that area: `top-left`, `top`, `top-right`, `left`, `center`, `right`, `bottom-left` (default), `bottom`, `bottom-right`. Blocks showing at one anchor stack away from its edge in list order, 4 px apart, the anchor's first block `margin` (default 6) off the edges; `beside: true` puts a block beside the one before it instead. Blocks in one row of anchors (top, middle or bottom) make way rather than overlap: a left block narrows for a centre or right one, a centre block for a right one. The corner block ([`STYLE.md`](STYLE.md) `corner`) comes first at its anchor, a pill or chapter step caption next.
  - `lines`: each a string, or a list of parts. A part is a string, `{"text", "color"?, "bold"?, "size"?}`, `{"dot": colour}` or `{"rule": true}` (a hairline); parts sit `gap` px apart, with `sep` between them. `{clock}`, `{step}` (the step's `tag`, else 步驟 n/N) and `{speed}` (快轉 N× while an idle stretch plays fast) are filled in each frame; a part its tokens leave empty is dropped with its `sep`.
  - Look: `size` (13), `weight` (500; a `bold` part 700), `color` (`#e6e6e6`), `bullets`, `bg` (`#0000008c`; `null` for none), `radius` (a pill for one line, else 6), `pad` (`[x, y]`), `min_w` (a block at least this wide, such as a panel that should keep its edges from one text to the next), `max_w` (default the frame's width, less what the block makes way for).
  - `max_lines` (default 1): how many rows a line too wide for the block may wrap to; past them it ends in …. It breaks between characters, at a space rather than inside a word, and never before closing punctuation; a bulleted line's later rows hang under its text. A block that wraps grows, so in a band keep it to what the band holds: two rows of 13 px fill 40 px when the anchor's first block has `margin: 0` (at bottom-left that is the corner: `style.corner` `{"margin": 0}`).
  - `rect`: `[x, y, w, h]` in `space`. The block becomes a box over the recording there, under every other mark and through the zoom, its lines inside: a cover for on-screen text the video should not show, such as captions a test page drew. Private data goes in `masks.json`, which scans for it.
