#!/usr/bin/env bash
# watch-pr.sh <number> [interval-seconds]: run from inside the repo. Watches a pull request: a GitHub PR
# through gh when origin is on github.com, otherwise a GitLab merge request through glab.
# Prints one line per change of "<state> pipeline=<status> merge=<status>" and exits when it is
# merged or closed, its pipeline passed, failed, was canceled or skipped, or it conflicts with its target branch.
# Meant to run under Monitor: every line is an event.
set -u
n="${1:?usage: watch-pr.sh <number> [interval-seconds]}"
interval="${2:-30}"
case "$(git remote get-url origin 2>/dev/null)" in
  *github.com*) forge=github ;;
  *) forge=gitlab ;;
esac

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

last=""
while :; do
  now="$(status | tr -d '\r')"
  [ -n "$now" ] || now="unreachable (VPN or token?)"
  if [ "$now" != "$last" ]; then echo "$now"; last="$now"; fi
  case "$now" in
    merged*|closed*|*pipeline=success*|*pipeline=skipped*|*pipeline=failed*|*pipeline=canceled*|*merge=conflict*) exit 0 ;;
  esac
  sleep "$interval"
done
