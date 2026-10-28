---
name: research.patch
description: "Patch for research: run the background agent as the `Researcher` agent."
disable-model-invocation: true
user-invocable: false
---

When running `research`, spawn the background agent with `subagent_type: Researcher`, falling back to `general-purpose` when that type is not listed. The brief names the question and the notes file path, so the agent writes only that file. Done: the research ran in `Researcher`, or the report says the fallback was used.
