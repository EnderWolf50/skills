---
name: figma-design-to-code.patch
description: "Patch for figma-design-to-code: a design drawn as several state frames; spec notes are requirements; copy changes asked first; every state compared by screenshot."
disable-model-invocation: true
user-invocable: false
---

When running `figma-design-to-code` on a design drawn as several frames, one per state (filled, verifying, failed, success, confirm dialog):

- **Pick the frames first.** `get_structure` on the link's node (`node-id=41240-234783` is `41240:234783`) or the selection, `options.depth: 1` for a whole section. A canvas often holds several generations of one screen: the current ones sit beside the spec notes (`Note`, `規格說明`), and state frames are named by state (`f1 填寫`, `f3 驗證失效`). `get_screenshot` each and name what each state shows that the others do not. Done: one frame id per state.
- **Spec notes are requirements.** Read every note beside the frames with `get_code`. A state a note describes (loading, confirm dialog, hover) is evidenced: build it, overriding "implement only evidenced states".
- **Read only the content.** Skip the app chrome every frame repeats (menu, nav bar, sidebar, footer, background); `get_code` the content container (often `Card` or `Content`). List every literal colour that carries no variable.
- **Copy changes are asked.** When a frame's text differs from the current UI, list old and new text and ask before editing translations.
- **Compare every state.** Every state must be reachable for the user to check, not only the first frame. Screenshot each state in the running app at the frame's width, Read it beside the frame's `get_screenshot`, and list what differs; fix the clear mismatches once, and give each difference left its reason (a container narrower than the frame, a shared component left alone). The user judges the result by eye. Done: one screenshot per state, and the list of differences left with reasons.
