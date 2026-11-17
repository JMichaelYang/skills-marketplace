# Ticket lifecycle

Your prompt gives the issue `<n>`, `Base`, `Coordinator`, `State`, the brief and the rules.

- `state <cmd>` means `python3 -I <Base>/../../scripts/sdlc_state.py <cmd> --state <State>`.
- `<default>` is `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`.
- To message the coordinator, load SendMessage with ToolSearch `select:SendMessage`, then send to `<Coordinator>`.
- The brief and rules override defaults. Ask the coordinator only for decisions they leave open, and only if you cannot proceed.
- Never merge.

1. Run `/github-sdlc:execute-issue <n> <brief>`, adding to its args: "Before pushing, run the rules' pre-push checks and fix any failures, then `git fetch origin && git rebase origin/<default>` and rerun the checks if the rebase changed anything."
2. `state set <n> status=pr_open pr=<PR URL>`.
3. If the brief has a `Verify:` section that is not `none`, run `/github-sdlc:verify-change <surfaces> --issue <n> <checks> Rules: <rules>`, where `<surfaces>` is the comma-separated surfaces it names and `<checks>` is the section. While its `VERIFY all` line is FAIL, fix the failures, run the rules' pre-push checks, push, and run it again; stop retrying when a failure is not caused by the change, such as a missing device or a broken build tool. Then `state set <n> "verify=<result>: <p> passed, <f> failed, <s> skipped"` from that line.
4. SendMessage the coordinator once, with `#<n> PR ready: <PR URL>` as the first line, then one line on the change, the checks run with their results, and step 3's VERIFY lines if it ran.
5. Run `/github-sdlc:handle-reviews <n> [--interval <seconds>] <rules>`, passing `--interval` only when the rules name a watch interval, and the rules unless they are "none". If step 3 ran, add to the rules, with step 3's commands written out in full: "After any push that changes what the Verify section checks, run `/github-sdlc:verify-change …` and fix failures before continuing, then `state set … verify=…` from its `VERIFY all` line." When it reports a thread needing the user's decision, SendMessage the coordinator `#<n> needs a decision: <link>` with the question, then keep watching. It returns the `merged` or `closed` line.
6. Act on that line, then end your turn. The coordinator removes this session, so never stop it yourself.
   - `merged`: stop all work and push nothing. Note the PR's `number` and `headRefName` from `gh pr view <PR URL> --json number,headRefName`, then run `/github-sdlc:cleanup-issue <n>`, exiting the worktree first as it says. Then, from the main checkout:
     1. If `git ls-remote --heads origin <headRefName>` still lists the branch, `git push origin --delete <headRefName>`.
     2. `state set <n> status=cleaned`, then `state unblocked`.
     3. SendMessage the coordinator exactly `#<n> merged (PR #<number>), cleaned up, <default>@<sha>; now unblocked: #X #Y`, where `<sha>` is `git rev-parse --short <default>` and the list is the issues `state unblocked` printed, or `none`.
   - `closed`: SendMessage the coordinator `#<n> PR closed without merge: <PR URL>`.
