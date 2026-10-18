#!/usr/bin/env bash
# Reinstall named skills from one GitHub source the way the dotfiles sync-skills script does:
# sparse-clone only their folders, then `skills add <local clone>` for Claude Code and Codex.
#   resync.sh <owner/repo> <path-in-repo>...
set -euo pipefail
[ $# -ge 2 ] || { echo 'usage: resync.sh <owner/repo> <path-in-repo>...' >&2; exit 2; }
# A non-interactive Linux shell lacks Homebrew and mise on PATH, so npx would be missing
# (same fix as the dotfiles' .chezmoitemplates/tool-path.sh).
if ! command -v npx >/dev/null; then
  [ -x /home/linuxbrew/.linuxbrew/bin/brew ] && eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
  command -v mise >/dev/null && eval "$(mise activate bash --shims)"
fi
export GIT_TERMINAL_PROMPT=0   # the sparse checkout fetches blobs too
repo=$1; shift
src=$(mktemp -d)
trap 'rm -rf "$src"' EXIT
git clone -q --depth 1 --filter=blob:none --sparse "https://github.com/$repo" "$src"
git -C "$src" sparse-checkout set -- "$@"
names=()
for p in "$@"; do names+=("$(basename "$p")"); done
# Full output: `skills add -s` exits 0 when at least one name matched, so read its "Selected N skills" line.
npx -y skills add "$src" -g -a claude-code codex -y -s "${names[@]}"
