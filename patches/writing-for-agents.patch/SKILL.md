---
name: writing-for-agents.patch
description: "Patch for writing-for-agents: extend someone else's skill with a <skill>.patch instead of editing it."
disable-model-invocation: true
user-invocable: false
---

When running `writing-for-agents` to create or change a skill, first find its **owner**: the `source` of its entry in `~/.agents/.skill-lock.json`, or in the repo's `skills-lock.json` for a project skill.

- **Own skill** (source `EnderWolf50/skills`, or no lock entry): edit the skill itself, in its source repo.
- **Upstream skill** (any other source): leave its files untouched; reinstalls overwrite them. Put the change in a **patch**, a hidden skill named `<skill>.patch`. Look for an existing `<skill>.patch` first (below) and extend it; write a new one only when none exists.

A patch's `SKILL.md`:

```markdown
---
name: <skill>.patch
description: "Patch for <skill>: <one line>"
disable-model-invocation: true
user-invocable: false
---

When running `<skill>`: <additions or overrides, as steps, each with its completion criterion>
```

It lives in `patches/<skill>.patch/` in EnderWolf50/skills, plus the name in the EnderWolf50/skills list of chezmoi `.chezmoidata/skills.toml` so it installs; a project repo holds none. A rule that holds only in some repos is written as a condition the agent checks ("in a public repo", "when the repo's AGENTS.md says ..."), and the project keeps its specifics in its AGENTS.md.

The `skill-patches` plugin loads it: when `<skill>` runs, through the Skill tool (PostToolUse) or a typed `/<skill>` (UserPromptExpansion), the patch is injected after the skill and wins over it. Done: the change sits in the owner's skill or in its patch, and upstream files are unchanged.
