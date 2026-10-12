---
name: writing-for-agents.patch
description: "Patch for writing-for-agents: extend someone else's skill with a <skill>.patch instead of editing it."
disable-model-invocation: true
user-invocable: false
---

When running `writing-for-agents` to create or change a skill, first find its **owner**: the `source` of its entry in `~/.agents/.skill-lock.json`, or in the repo's `skills-lock.json` for a project skill.

- **Own skill** (source `EnderWolf50/skills`, or no lock entry): edit the skill itself, in its source repo.
- **Upstream skill** (any other source): leave its files untouched; reinstalls overwrite them. Put the change in a **patch**, a hidden skill named `<skill>.patch`. Look for an existing `<skill>.patch` first (paths below) and extend it; write a new one only when none exists.

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

Where it lives:

- **Global**: `patches/<skill>.patch/` in EnderWolf50/skills, plus the name in the EnderWolf50/skills list of chezmoi `.chezmoidata/skills.toml` so it installs.
- **Project**: `.claude/skills/<skill>.patch/` or `.agents/skills/<skill>.patch/` in that repo.

The `skill-patches` plugin loads it: when `<skill>` runs, through the Skill tool (PostToolUse) or a typed `/<skill>` (UserPromptExpansion), every patch found is injected after the skill, global first and project last, so the project patch wins on conflict and any patch wins over the skill. Done: the change sits in the owner's skill or in its patch, and upstream files are unchanged.
