---
name: writing-for-agents.patch
description: "Patch for writing-for-agents: extend someone else's skill with a <skill>.patch instead of editing it."
disable-model-invocation: true
user-invocable: false
---

When running `writing-for-agents` to create or change a skill, first find its **owner**: the `source` of its entry in `~/.agents/.skill-lock.json`, or in the repo's `skills-lock.json` for a project skill.

- **Own skill** (source `EnderWolf50/skills`, or no lock entry): edit the skill itself, in its source repo.
- **Upstream skill** (any other source): leave its files untouched; reinstalls overwrite them. Put the change in a **patch** per the `skill-patches:writing-patches` skill. It lives in `patches/<skill>.patch/` in EnderWolf50/skills, plus the name in the EnderWolf50/skills list of chezmoi `.chezmoidata/skills.toml` so it installs.

Done: the change sits in the owner's skill or in its patch, and upstream files are unchanged.
