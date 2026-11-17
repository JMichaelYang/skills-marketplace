---
name: issue-status
description: Use when the user asks for the status, progress, or dependency chart of coordinated GitHub issues, or what a coordinator's sessions are doing.
---

Args: `[--state <coordinator name or path>]`. `<base>` is this skill's base directory.

1. Run `python3 -I <base>/../../scripts/sdlc_state.py show [--state <s>]`.
2. If it fails with `several state files, pass --state: <names>`, list those coordinators newest first: `ls -lt "$(git rev-parse --path-format=absolute --git-common-dir)/github-sdlc/"{<name>,<name>,…}.json`. Rerun step 1 with `--state` set to the one the user's request points to, else the newest; if it hints at one you cannot match, ask which.
3. Reply with its output as printed, prefixed by the list from step 2 if any. On any other failure, return its stderr.
