# Skills repo

Skills install from this repo with the `skills` CLI; the list lives in the dotfiles repo's `.chezmoidata/skills.toml` (`EnderWolf50/skills` entry).

- Adding, renaming or removing a skill changes that list too, in a dotfiles pull request.
- After a pull request here merges, run `bash scripts/resync.sh EnderWolf50/skills <path>...` with the changed skill folders (e.g. `patches/retro.patch workflow/retro-all`) on each OS (on Windows + WSL, both sides), then check that `~/.agents/skills/<name>/` holds the merged version: the installed copy is what sessions run. `npx skills update` cannot do it: the dotfiles sync installs skills from local sparse clones, and it reruns only on the first `chezmoi apply` of a day.
