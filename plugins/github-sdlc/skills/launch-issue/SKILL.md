---
name: launch-issue
description: Use when a coordinator asks to launch, start, or kick off a background session for one tracked GitHub issue.
---

Args: `<n> [--state <coordinator name or path>] <brief>`. `<base>` is this skill's base directory, and `state <cmd>` means `python3 -I <base>/../../scripts/sdlc_state.py <cmd> [--state <s>]`.

1. Read `state get`. Note its `coordinator` and `rules`, and the issue's `title` and `status`; stop if the issue is untracked or its status is `merged` or `cleaned`. Its state path is `--state` if that is a path, else `$(git rev-parse --path-format=absolute --git-common-dir)/github-sdlc/<coordinator>.json`.
2. Name the session `issue-<n>-<two-to-three-word-slug>` from the title (e.g. `issue-42-fade-page-transitions`).
3. Write the prompt to `<dir>/launch-<n>.txt`, where `<dir>` is `$CLAUDE_JOB_DIR/tmp` if set, else a new `mktemp -d`:
   ```
   Follow <base>/references/lifecycle.md for issue #<n>.
   Base: <base>
   Coordinator: <coordinator>
   State: <state path>

   Brief:
   <brief>

   Rules:
   <rules, or "none">
   ```
4. From the main checkout (`cd "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"`), run `claude --bg -n <name> --permission-mode auto "$(cat <dir>/launch-<n>.txt)"`. It prints `backgrounded · <id> · <name>`, possibly with color codes; if not, stop and return its output.
5. Record it: `state set <n> session=<name> id=<id> status=running`.
6. Reply with `#<n> launched as <name> (<id>)`.
