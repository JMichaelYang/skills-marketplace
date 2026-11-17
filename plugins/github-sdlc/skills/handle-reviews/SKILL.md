---
name: handle-reviews
description: Use when the user asks to watch, shepherd, or babysit an issue's PR until it merges, handling reviews, CI failures and conflicts.
---

Args: `<n> [--interval <seconds>] [rules]`, where `<n>` is the issue and rules may name pre-push checks and a version-bump convention.

1. Set up:
   - `me=$(gh api user --jq .login)` and `dir=$(git rev-parse --path-format=absolute --git-common-dir)/github-sdlc`.
   - Find the PR: `gh pr list --state all --json number,headRefName,body --jq '[.[] | select((.headRefName | startswith("<n>-")) or ((.body // "") | test("#<n>\\b")))][0]'`. Stop if there is none.
   - Work in the worktree for its `headRefName` (`git worktree list`), creating one if needed.
   - The first launch only records existing activity, so if unresolved threads end with a comment not by `$me`, handle them now as in step 3.
2. Launch with Bash `run_in_background: true`: `python3 -I <base>/../../scripts/watch_pr.py <n> "$dir" [--interval <seconds>]`. Run one watcher per issue.
3. When it exits with `merged` or `closed` among its lines, go to step 4. Otherwise handle every line, ignoring those by `$me` or a `[bot]`, then relaunch step 2:
   - `review … by <login>` or `comment by <login>`: run `/github-sdlc:address-reviews <pr>`, passing the rules' checks to run before pushing. Handle a body outside any thread the same way, replying with `gh pr comment <pr> --body "<reply>"`. A bare `APPROVED` needs nothing.
   - `ci_failed <check>`: find the cause with `gh pr checks <pr>` and `gh run view <run-id> --log-failed`, then fix it.
   - `conflicting`: `git fetch origin && git rebase origin/<default>`, resolving per the rules' version-bump convention.
   - After any change, run the rules' checks and push (`--force-with-lease` after a rebase).
   - Report anything needing the user's decision to the caller, one line each with its link, instead of guessing.
4. On `merged` or `closed`, push nothing and return that line. If the watcher exits non-zero, return its stderr.
