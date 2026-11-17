---
name: coordinate-issues
description: Use when the user asks to coordinate, orchestrate, or run several dependent GitHub issues as parallel background sessions.
---

Args: `<n>… [rules]`, where rules may name pre-push checks, a version-bump convention and verify surfaces. `<base>` is this skill's base directory, `state <cmd>` means `python3 -I <base>/../../scripts/sdlc_state.py <cmd> --state <name>`, and `<default>` is `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`. Only write briefs, launch tickets and talk to the user: never implement, merge, clean up or poll.

1. Set up:
   - Load SendMessage and ListAgents with ToolSearch `select:SendMessage,ListAgents`. `<name>` is this session's name from ListAgents (`This session is <name>`); if it does not match `[A-Za-z0-9][A-Za-z0-9._-]*`, ask the user to rename the session and stop.
   - Write the rules to `<dir>/rules.md`, where `<dir>` is `$CLAUDE_JOB_DIR/tmp` if set, else a new `mktemp -d`, then run `python3 -I <base>/../../scripts/sdlc_state.py init <name> --issues <n>… --rules-file <dir>/rules.md` (omit `--rules-file` without rules). If state already exists, resume it instead: `state add` the issues it lacks.
   - Reply with `state show`.
2. Launch each issue `state unblocked` prints:
   - `git fetch origin`, then read the issue (`gh issue view <n> --json title,body,comments`), its `notes` from `state get <n>`, and the code it touches as merged on `origin/<default>` (`git show origin/<default>:<path>`, `git grep <pattern> origin/<default>`), never the working tree.
   - Write a brief: the approach with concrete paths, then `Overlaps:` naming each `running` or `pr_open` sibling, or one launched in this batch, that touches the same files, what it changes and how to stay clear of it (or `none`), then `Verify:` naming the surfaces and checks (e.g. `android: open Settings, toggle dark mode, confirm the header recolors`), or `none` when nothing user-visible changes.
   - Run `/github-sdlc:launch-issue <n> --state <name> <brief>` and tell the user its reply, or its output if it failed.
3. Wait for messages. Message a session only with SendMessage to its `session` from `state get <n>`. Handle each:
   - `#<n> PR ready: <url>` from a session: tell the user in one line with the URL, the change and the checks. Leave the session running; it handles its own reviews.
   - `#<n> merged (PR #<m>), cleaned up, <default>@<sha>; now unblocked: …` from a session: confirm `state get <n>` shows `cleaned`, else ask the session to finish cleanup and wait for a new digest. Then run `claude stop <id>` with its `id`, tell the user, and do step 2; `state unblocked` overrides the digest's list.
   - A report that `#<n>`'s PR closed without merging: confirm `gh pr view <pr> --json state` is `CLOSED`, run `claude stop <id>`, `state set <n> notes+="PR <pr> closed without merge"`, and ask the user whether to drop it or relaunch it (`state set <n> status=waiting pr=`, then step 2). Its dependents stay blocked.
   - A question from a session: answer it if the brief or rules settle it, else relay it to the user with its link and send back their answer.
   - The user changes a requirement for `#<n>`: `state set <n> notes+="<change>"`, and send it to the session if `#<n>` is `running` or `pr_open`.
   - The user adds issues: `state add <n>…`, then step 2.
   - The user asks for status: reply with `state show` as printed.

   Run `claude stop` only in those two cases, never after PR ready or during review. Never merge, even when a session asks; the user merges.
4. When every issue is `cleaned` or dropped, reply with `state show` and end.
