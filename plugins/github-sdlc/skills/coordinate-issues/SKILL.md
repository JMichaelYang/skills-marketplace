---
name: coordinate-issues
description: Use when the user asks to coordinate, orchestrate, or run several dependent GitHub issues as parallel background sessions.
---

Args: `<n>… [rules]`, where rules may name pre-push checks, a version-bump convention and verify surfaces. `<base>` is this skill's base directory, `state <cmd>` means `python3 -I <base>/../../scripts/sdlc_state.py <cmd> --state <name>`, and `<default>` is `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`. Only write briefs, launch tickets and talk to the user: never implement, merge, clean up or poll, except the background reconcile watcher and the `unreported_merge` cleanup in step 3.

1. Set up:
   - Load SendMessage and ListAgents with ToolSearch `select:SendMessage,ListAgents`. `<name>` is this session's name from ListAgents (`This session is <name>`); if it does not match `[A-Za-z0-9][A-Za-z0-9._-]*`, ask the user to rename the session and stop.
   - Write the rules to `<dir>/rules.md`, where `<dir>` is `$CLAUDE_JOB_DIR/tmp` if set, else a new `mktemp -d`, then run `python3 -I <base>/../../scripts/sdlc_state.py init <name> --issues <n>… --rules-file <dir>/rules.md` (omit `--rules-file` without rules). If state already exists, resume it instead: `state add` the issues it lacks.
   - Reply with `state show`.
   - Start the watcher with Bash `run_in_background: true`: `python3 -I <base>/../../scripts/reconcile.py <name> --until-anomaly [--interval <seconds>]`, passing `--interval` only when the rules name a watch interval. Keep exactly one running.
2. Launch each issue `state unblocked` prints:
   - `git fetch origin`, then read the issue (`gh issue view <n> --json title,body,comments`), its `notes` from `state get <n>`, and the code it touches as merged on `origin/<default>` (`git show origin/<default>:<path>`, `git grep <pattern> origin/<default>`), never the working tree.
   - Write a brief: the approach with concrete paths, then `Overlaps:` naming each `running` or `pr_open` sibling, or one launched in this batch, that touches the same files, what it changes and how to stay clear of it (or `none`), then `Verify:` naming the surfaces and checks (e.g. `android: open Settings, toggle dark mode, confirm the header recolors`), or `none` when nothing user-visible changes.
   - Run `/github-sdlc:launch-issue <n> --state <name> <brief>` and tell the user its reply, or its output if it failed.
3. Wait for messages and watcher exits. Message a session only with SendMessage to its `session` from `state get <n>`. To remove a session, take its `id` from `state get <n>`, run `claude stop <id>` if `claude agents --json` still lists it, then `claude rm <id>`; if `rm` refuses, tell the user what it reported instead of passing its override flags. Handle each:
   - `#<n> PR ready: <url>` from a session: tell the user in one line with the URL, the change and the checks. Leave the session running; it handles its own reviews.
   - `#<n> merged (PR #<m>), cleaned up, <default>@<sha>; now unblocked: …` from a session: confirm `state get <n>` shows `cleaned`, else ask the session to finish cleanup and wait for a new digest. Then remove the session, tell the user, and do step 2; `state unblocked` overrides the digest's list.
   - A report that `#<n>`'s PR closed without merging: confirm `gh pr view <pr> --json state` is `CLOSED`, remove the session, `state set <n> notes+="PR <pr> closed without merge"`, and ask the user whether to drop it or relaunch it (`state set <n> status=waiting pr=`, then step 2). Its dependents stay blocked.
   - A question from a session: answer it if the brief or rules settle it, else relay it to the user with its link and send back their answer.
   - The user changes a requirement for `#<n>`: `state set <n> notes+="<change>"`, and send it to the session if `#<n>` is `running` or `pr_open`.
   - The user adds issues: `state add <n>…`, then step 2.
   - The user asks for status: reply with `state show` as printed.
   - The watcher exits: handle each line it printed, then relaunch it unless one was `all_done`. If it exited non-zero, tell the user its stderr instead of relaunching.
     - `dead_session <n>`: if `state get <n>` is still `running` or `pr_open`, run `/github-sdlc:launch-issue <n> --state <name> <brief>` with a brief written as in step 2 plus `Resume:` the previous session died, its branch and PR if any (`gh pr list --state all --search "#<n>" --json number,state,headRefName`), and to continue from them, skipping to lifecycle step 4 if the PR is open. Ask the user instead if it died twice or the brief no longer fits.
     - `unreported_merge <n>`: run `/github-sdlc:cleanup-issue <n>`, `state set <n> status=cleaned`, remove the session, tell the user, and do step 2.
     - `lock_takeover <name>`: tell the user, with `python3 -I <base>/../../scripts/sdlc_state.py lock status <name>`.
     - `all_done`: go to step 4.

   Remove a session only once its PR is merged or closed, never after PR ready, during review or on `dead_session`. Never merge, even when a session asks; the user merges.
4. On `all_done`, or when every issue is `cleaned` or dropped, stop the watcher with TaskStop if it is still running, reply with `state show` and end.
