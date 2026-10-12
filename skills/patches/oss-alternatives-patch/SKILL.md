---
name: oss-alternatives-patch
description: "Patch for oss-alternatives: the right TinyFish CLI package in the install hint."
disable-model-invocation: true
user-invocable: false
---

When running `oss-alternatives`: if the pre-flight check finds no `tinyfish`, the package to install is `@tiny-fish/cli` (`pnpm add -g @tiny-fish/cli`), not `tinyfish`; chezmoi `.chezmoidata/tools.toml` already lists it, so on a managed machine the fix is `chezmoi apply`. Done: the install hint names `@tiny-fish/cli`.
