#!/usr/bin/env bash
# Reinstall named skills from one GitHub source the way the dotfiles sync-skills script does:
# sparse-clone only their folders, then `skills add <local clone>` for Claude Code and Codex.
#   resync.sh <owner/repo> <path-in-repo>...
set -euo pipefail
repo=$1; shift
src=$(mktemp -d)
trap 'rm -rf "$src"' EXIT
GIT_TERMINAL_PROMPT=0 git clone -q --depth 1 --filter=blob:none --sparse "https://github.com/$repo" "$src"
git -C "$src" sparse-checkout set "$@"
names=()
for p in "$@"; do names+=("$(basename "$p")"); done
npx -y skills add "$src" -g -a claude-code codex -y -s "${names[@]}" 2>&1 | tail -3
