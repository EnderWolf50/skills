---
name: grilling.patch
description: "Patch for grilling: researched options with pros and cons, only chosen decisions written down, a spec draft at the end."
disable-model-invocation: true
user-invocable: false
---

When running `grilling` (also through `grill-me` and `grill-with-docs`):

- **Research first.** Before a round with choice questions, a sub-agent finds how comparable products or libraries handle each of them; one sub-agent may cover the whole round. When one product already has the full feature, it is option A; a simpler recommendation says why it beats matching that product.
- **Concrete options.** Each option carries one line of pros and cons, the comparable products that take it ("none found" when the research found none), and one example from the product itself with real names and numbers. Each question closes with "if you pick nothing: …". Say what the user sees before naming a mechanism (preset slots, a cache).
- **Screen facts from the screen.** A question that depends on what a screen or output shows waits for a capture of it; a number from a wiki or another tool is marked "unverified".
- **Only chosen decisions get written down.** A decision lands in docs, ADRs, the glossary, an issue or code only after the user chose it in their own answer. List every unanswered recommendation under **Open decisions** at the end of each round and after the spec draft.
- **End with a spec draft.** When the frontier is empty, before asking whether the understanding is shared, write the chosen decisions as one spec in the user's language, following this outline. Title and headings may be reworded; drop a section that does not apply, keep the order:

  ```
  ## Spec settled (confirm before implementation)
  **Entry point**: where the reader or caller meets it (API routes, screen, command)
  **Input**: an example with the real field names, then the rules for each field
  **Behaviour**: validation, limits, how it processes (all at once or item by item, sync or async)
  **Output**: a response or result example, then the error codes and what each means
  **Also**: logging, permissions, exposure, effects on related records
  **Out of scope**: what was left out and where it went (issue link)
  ```

  It holds only chosen decisions and no personal data, and it is shown in full for approval before it is posted anywhere.

Done for each round: every option has its three parts, every question its "if you pick nothing", a screen-dependent question cites its capture, and every decision written anywhere traces to an answer from the user. Done for the session: the spec draft is shown in full and the user has answered whether the understanding is shared.
