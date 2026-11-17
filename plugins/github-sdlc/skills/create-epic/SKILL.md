---
name: create-epic
description: Use when the user wants to file several related or dependent GitHub issues at once in the current repo.
---

1. Draft each ticket as a short imperative title and a body following [../create-issue/references/template.md](../create-issue/references/template.md) exactly; respect its length limits. When a ticket depends on others, end its Why with a `Blocked by` line listing only refs, e.g. `Blocked by {T1}, #7.`: `{T<k>}` for the k-th earlier ticket in the plan, which the script files as `#N`, or `#N` for an existing issue. No other text belongs on that line.
2. Write them in filing order to `<dir>/epic.json` as `[{"title": "…", "body": "…", "labels": ["…"]}]`, where `labels` is optional and must already exist, and `<dir>` is `$CLAUDE_JOB_DIR/tmp` if set, else a new `mktemp -d`.
3. File them: `python3 -I <base>/../../scripts/create_epic.py <dir>/epic.json`, where `<base>` is this skill's base directory (`--dry-run` previews bodies without filing). It files in order 3s apart, turns each `{T<k>}` into `#N`, and records `{index: number}` in `<dir>/epic.filed.json`; a rerun skips filed tickets, so after a failure fix the cause and rerun the same command. Auto mode may block bulk creation; if so, ask the user to approve it.
4. Reply with the table and dependency chart it prints.
