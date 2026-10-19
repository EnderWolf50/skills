---
name: grilling.patch
description: "Patch for grilling: research-backed options with pros and cons; undecided choices stay out of docs."
disable-model-invocation: true
user-invocable: false
---

When running `grilling` (also through `grill-me` and `grill-with-docs`):

- **Research first.** Before a question with choices, a sub-agent finds how comparable products or libraries handle it (finding facts is your job). When one already has the full feature, it is option A; a simpler recommendation says why it beats matching that product.
- **Concrete options.** Each option carries one line of pros and cons, the comparable products that take it, one example from the product itself with real names and numbers, and "if you pick nothing: …". Say what the user sees before naming a mechanism (preset slots, a cache).
- **Screen facts from the screen.** A question that depends on what a screen or output shows waits for a capture of it; a number from a wiki or another tool is marked "unverified".
- **Only chosen decisions get written down.** A decision lands in docs, ADRs, the glossary or code only after the user chose it in their own answer. List every unanswered recommendation under **Open decisions** at the end of each round and in the final summary.

Done for each round: every option has all four parts, a screen-dependent question cites its capture, and every decision written anywhere traces to an answer from the user.
