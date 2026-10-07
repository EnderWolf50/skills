#!/usr/bin/env bash
# watch-pr.sh <number> [interval-seconds]: run from inside the repo. Watches a pull request: a GitHub PR
# through gh when origin is on github.com, otherwise a GitLab merge request through glab.
# Prints "<state> pipeline=<status> merge=<status>" when the state or pipeline changes, or a conflict
# appears (merge alone flips between checking and ci_still_running while a pipeline runs), and exits
# when it is merged or closed, its pipeline passed, failed, was canceled or skipped, it conflicts
# with its target branch, or it has no pipeline: at once in a repo without CI config, after 2 minutes
# in one with it (rules that start no job).
# On a failed pipeline it also prints "target=<branch> pipeline=<status>" for the target branch's latest
# finished pipeline: failed there too means the failure is inherited, not the pull request's own.
# Meant to run under Monitor: every line is an event.
set -u
n="${1:?usage: watch-pr.sh <number> [interval-seconds]}"
interval="${2:-30}"
case "$(git remote get-url origin 2>/dev/null)" in
  *github.com*) forge=github ;;
  *) forge=gitlab ;;
esac
# With CI config, a pipeline can take a moment to appear after a push; without it, none ever will.
grace=0
[ -n "$(git ls-tree --name-only HEAD .github/workflows .gitlab-ci.yml 2>/dev/null)" ] && grace=120

status() {
  if [ "$forge" = github ]; then
    # Checks are reduced to one pipeline status; mergeStateStatus DIRTY is a conflict.
    gh pr view "$n" --json state,mergeStateStatus,statusCheckRollup 2>/dev/null | jq -r '
      [.statusCheckRollup[]? | (.conclusion // .state // .status // "" | ascii_downcase)] as $c
      | (if ($c | length) == 0 then "none"
         elif any($c[]; . == "failure" or . == "error" or . == "timed_out" or . == "action_required") then "failed"
         elif any($c[]; . == "cancelled") then "canceled"
         elif any($c[]; . == "" or . == "pending" or . == "queued" or . == "in_progress" or . == "expected") then "running"
         else "success" end) as $p
      | (.mergeStateStatus | ascii_downcase | if . == "dirty" then "conflict" else . end) as $m
      | "\(.state | ascii_downcase) pipeline=\($p) merge=\($m)"'
  else
    glab api "projects/:id/merge_requests/$n" 2>/dev/null | jq -r \
      '"\(.state) pipeline=\(.head_pipeline.status // "none") merge=\(.detailed_merge_status // "unknown")"'
  fi
}

target_status() {
  if [ "$forge" = github ]; then
    b="$(gh pr view "$n" --json baseRefName -q .baseRefName 2>/dev/null)"
    st="$(gh run list --branch "$b" --limit 20 --json status,conclusion,databaseId 2>/dev/null | jq -r \
      '[.[] | select(.status == "completed" and .conclusion != "skipped")][0] | "\(.conclusion) (\(.databaseId))"')"
  else
    b="$(glab api "projects/:id/merge_requests/$n" 2>/dev/null | jq -r .target_branch | tr -d '\r')"
    # Path-rule pipelines are skipped; the last finished one tells whether the branch itself is red.
    st="$(glab api "projects/:id/pipelines?ref=$b&per_page=20" 2>/dev/null | jq -r \
      '[.[] | select(.status == "success" or .status == "failed" or .status == "canceled")][0] | "\(.status) (\(.id))"')"
  fi
  echo "target=$b pipeline=$(printf '%s' "$st" | tr -d '\r')"
}

last=""
while :; do
  now="$(status | tr -d '\r')"
  [ -n "$now" ] || now="unreachable (VPN or token?)"
  key="${now%% merge=*}"
  case "$now" in *merge=conflict*) key="$now" ;; esac
  if [ "$key" != "$last" ]; then echo "$now"; last="$key"; fi
  case "$now" in
    *pipeline=failed*) target_status; exit 0 ;;
    merged*|closed*|*pipeline=success*|*pipeline=skipped*|*pipeline=failed*|*pipeline=canceled*|*merge=conflict*) exit 0 ;;
  esac
  case "$now" in *pipeline=none*) [ "$SECONDS" -ge "$grace" ] && { echo "no pipeline after ${SECONDS}s"; exit 0; } ;; esac
  sleep "$interval"
done
