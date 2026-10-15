---
name: herdr.patch
description: "Patch for herdr: configuring Herdr (settings, keybindings, theme) from the chezmoi source."
disable-model-invocation: true
user-invocable: false
---

When running `herdr` to read or change Herdr's **configuration** (a setting, a keybinding, the theme), the `HERDR_ENV` check does not apply: configuration is files, not session control.

1. **Source.** The live file is `~/.config/herdr/config.toml` (Windows points `HERDR_CONFIG_PATH` at it; Herdr's own default there is `%APPDATA%\herdr`). chezmoi renders it from `dot_config/herdr/config.toml.tmpl` in `chezmoi source-path`, with colors from `.chezmoidata/themes.toml`; edit the template, never the target.
2. **Keys and options.** Read the version's reference instead of browsing the site: `herdr --version`, then `https://raw.githubusercontent.com/herdrdev/herdr/v<version>/docs/next/website/src/data/config-reference.json` (every option and default) and `.../src/content/docs/keyboard.mdx` (keybinding syntax). The template's current `[keys]` table is the user's map; propose a change against it, so the user sees old and new side by side.
3. **Apply.** `chezmoi apply ~/.config/herdr/config.toml`, `herdr config check`, then `herdr server reload-config`. Done: `config check` is clean and the reload succeeded.
