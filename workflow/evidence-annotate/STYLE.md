# Look: `--preset` and `style`

`--preset` sets a whole look; the `style` object in `events.json` then overrides it key by key. Every key is optional; an unknown key or value is an error.

## Presets

| `--preset` | Use | Adds to the defaults |
|---|---|---|
| `evidence` (default) | bug reports, test proof | nothing |
| `tutorial` | steps someone will follow | `zoom`, the caption's `dot` |
| `demo` | a showcase to share | `figma` cursor, `zoom`, `float`, `dot`, a lilac-to-blue `frame` |
| `agent` | an AI agent at work | `cua` cursor, `zoom`, `float`, `chapter` captions, a midnight-blue `frame` |

## Pointer

- `cursor`: `mac` (default, black arrow), `cua` (Cua Driver's own cursor, with its glow) or `figma` (Figma's coloured dart). A cursor brings its own `arc`, `tilt`, `glow` and `click`, each overridable:

  | `cursor` | `arc` | `tilt` | `glow` | `click` |
  |---|---|---|---|---|
  | `mac` | `0.1` | `0` | `false` | `shrink` |
  | `figma` | `0.1` | `"aim"` | `false` | `shrink` |
  | `cua` | `0.25` | `1` | `true` | `sparks` |

- `color` `#rrggbb`: rings, effects, and the `cua`/`figma` pointer and name tag (default `#5ec0e8` for `cua`, else `#4785ff`). One colour per actor reads well.
- `size`: scales the pointer with its name tag, glow, comet trail and float, and the touch dot, click ring and drag trail (default `0.6`: an arrow about 38 px tall and a 22 px touch dot at 1280 wide; `0.3` to `2`).
- `click`, how a mouse pointer marks a press: `ring` (a click ring, the pointer shrinking to 0.8), `shrink` (Figma's: no ring, snapping down to 0.75 in 80 ms and springing back over 0.3 s), `sparks` (Cua's: three short strokes off the tip). `pointer` `touch` and `none` always ring.
- `trail`: the drag trail (default on for `touch` and `none`, off for a drawn mouse pointer, as macOS, Figma and Cua draw none).

## Name tag

- `label`: a name tag behind the pointer, styled as each cursor's own (Figma's squarer solid tag at the arrow's corner, Cua's rounder glowing one beside it). It turns round the tip with the arrow and falls back a little while it glides. Best on `cua` or `figma`: on the plain `mac` arrow it reads as nobody's cursor.
- `label_color`, `label_text` `#rrggbb`: the tag and its text (default the pointer's colour; white text, Cua's dark).

## Motion

- `motion`, how a mouse pointer glides between presses (Cua Driver's styles, ported in `scripts/cursor_motion.py`): `signature_arc` (default: one arc with a small follow-through, a speed glow), `spring_settle` (lands with a soft bounce, a speed glow), `comet_swoop` (a wider arc with a comet trail). A glide ends as the next press starts; a gap shorter than the move plays it faster.
- `arc`: scales the arc (`0.25` = the style's own, `0` straight).
- `tilt`: how far the tip turns toward the motion at full speed (`1` = as Cua, `0` upright; upright below 300 px/s of a 1280-wide frame, the full turn at 1500), or `"aim"`: upright while gliding, swinging 64° about its tip on a spring with a little overshoot when the next target lies more than 60 px to its right, and back when it lies as far to the left, as Figma animates its cursor.
- `glow`: the speed glow.

## At rest

- `float` (default `false`): Cua's slow resting drift, at half its size.
- `idle_fade` (seconds, default `0` = off): fades a resting pointer out after that long, back in a quarter second before it moves.

Both leave the press point itself exact.

## Camera

`zoom` (default `0`, off; `true` = 1.5, Cap's default) turns on the auto camera, a spring with Cap's constants (settles in about 0.55 s). Presses group while they fit one view at that magnification (a drag fits its whole path, wider if needed). A group of two or more presses, a drag, or a press alone in its run of activity (gaps under 2.5 s) zooms in 0.6 s before its first press and pans to the next group; a lone press amid scattered ones keeps the full frame, so busy, spread-out work stays wide. Typing keeps the view; the camera eases out where it is a second after a group. A step's own `zoom` wins.

## Captions

`caption` picks the step caption, the same capsule ("n/total │ title") wherever it sits:

- `pill` (default): bottom centre, 20 px off the edge at 1280 wide.
- `chapter`: top left, 20 px off the edges.
- `callout`: beside the step's first press, else its first box, on the side away from the pointer and its name tag, else the side that fits best, kept inside the frame; `pill` without an anchor.

`dot: true` adds an amber dot in front.

## Frame

`frame` (default none) puts the video on a background, `"#rrggbb"` or a diagonal gradient `["#e0c3fc","#8ec5fc"]`, with padding, rounded corners and a shadow. The output grows by the padding, so the recording keeps its full size.
