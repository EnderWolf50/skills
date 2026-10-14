# Skills repo

Skills install from this repo with the `skills` CLI; the list lives in the dotfiles repo's `.chezmoidata/skills.toml` (`EnderWolf50/skills` entry).

- Adding, renaming or removing a skill changes that list too, in a dotfiles pull request.
- After a pull request here merges, run `npx -y skills update -g -y` and check that `~/.agents/skills/<name>/` holds the merged version: the installed copy is what sessions run.
