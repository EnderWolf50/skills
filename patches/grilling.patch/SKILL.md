---
name: grilling.patch
description: "Patch for grilling: research-backed options with pros and cons; undecided choices stay out of docs."
disable-model-invocation: true
user-invocable: false
---

When running `grilling` (also through `grill-me` and `grill-with-docs`):

- **Research first.** Before putting a question with choices to the user, research how comparable products or libraries handle it (a subagent, per the fact-finding rule). Each option then carries one line of pros and cons and one line on which comparable products take it.
- **Reference first.** When a comparable product already has the full feature, it is option A, with its cost; a simpler recommendation says why it beats matching that product.
- **Concrete options.** Each option carries one example from the product itself, with real names and numbers, and the line "if you pick nothing: …". Say what the user sees before naming a mechanism (preset slots, a cache).
- **Screen facts from the screen.** A choice that depends on what a screen or an output shows waits while you take a capture of it (only that question waits); a number taken from a wiki or another tool says "unverified" in the question.
  Done for each question: every option has an example, a cost and an "if you pick nothing" line, and a screen-dependent question cites its capture.
- **Only chosen decisions get written down.** A decision lands in docs, ADRs, the glossary or code only after the user explicitly chose it in their own answer; a recommendation the user has not answered stays out. List every such decision under **Open decisions** at the end of each round and in the final summary. Done: every decision written anywhere traces to an answer from the user.
