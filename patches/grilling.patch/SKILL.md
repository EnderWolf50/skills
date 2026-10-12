---
name: grilling.patch
description: "Patch for grilling: research-backed options with pros and cons; undecided choices stay out of docs."
disable-model-invocation: true
user-invocable: false
---

When running `grilling` (also through `grill-me` and `grill-with-docs`):

- **Research first.** Before putting a question with choices to the user, research how comparable products or libraries handle it (a subagent, per the fact-finding rule). Each option then carries one line of pros and cons and one line on which comparable products take it.
- **Only chosen decisions get written down.** A decision lands in docs, ADRs, the glossary or code only after the user explicitly chose it in their own answer; a recommendation the user has not answered stays out. List every such decision under **Open decisions** at the end of each round and in the final summary. Done: every decision written anywhere traces to an answer from the user.
