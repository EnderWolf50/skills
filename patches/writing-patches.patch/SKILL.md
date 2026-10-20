---
name: writing-patches.patch
description: "Patch for writing-patches: which skills are the user's own, and where the user's patches live."
disable-model-invocation: true
user-invocable: false
---

When running `writing-patches`:

- **Own skill**: its lock source comes from EnderWolf50/skills (the source path names `EnderWolf50-skills`), or it has no lock entry. Edit it in its source repo.
- **Where a patch lives**: `patches/<skill>.patch/` in EnderWolf50/skills, plus the name in the EnderWolf50/skills list of chezmoi `.chezmoidata/skills.toml` (a dotfiles PR) so it installs into `~/.agents/skills`; that repo's AGENTS.md covers the resync after merge. Done: the patch is in a PR to EnderWolf50/skills and its name in a dotfiles PR.
