# Ticket lifecycle

Your prompt gives the issue `<n>`, `Base`, `Coordinator`, `State`, the brief and the rules.

- `state <cmd>` means `python3 -I <Base>/../../scripts/sdlc_state.py <cmd> --state <State>`.
- `<default>` is `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`.
- To message the coordinator, load SendMessage with ToolSearch `select:SendMessage`, then send to `<Coordinator>`.
- The brief and rules override defaults. Ask the coordinator only for decisions they leave open, and only if you cannot proceed.
- Never merge.

1. Run `/github-sdlc:execute-issue <n> <brief>`, adding to its args: "Before pushing, run the rules' pre-push checks and fix any failures, then `git fetch origin && git rebase origin/<default>` and rerun the checks if the rebase changed anything."
2. `state set <n> status=pr_open pr=<PR URL>`.
3. SendMessage the coordinator once: `#<n> PR ready: <PR URL>`, one line on the change, and the checks run with their results.
