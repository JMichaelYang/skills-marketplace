# Skills Marketplace

A Claude Code plugin marketplace.

## Plugins

### github-sdlc

Skills for a GitHub issue → PR workflow, usable one at a time or coordinated across parallel background sessions.

Base skills:

- `create-issue`: file new work, a bug or an idea as a GitHub issue.
- `execute-issue`: implement an issue on its own branch and open a PR that closes it.
- `address-reviews`: fix clear review comments on a PR and reply to each thread.
- `cleanup-issue`: after an issue's PR merges, close the issue and remove its worktree and branch.

Coordinated skills:

- `create-epic`: file a batch of related or dependent issues in order, with `Blocked by` links.
- `coordinate-issues`: run dependent issues as parallel background sessions, launching each once its blockers merge.
- `launch-issue`: start a background session that takes one tracked issue from implementation through merge and cleanup.
- `verify-change`: verify a change on one or more device surfaces and report a `VERIFY` line per surface.
- `verify-android`: the Android emulator surface for `verify-change`.
- `handle-reviews`: watch an issue's PR until it merges, handling reviews, CI failures and conflicts.
- `issue-status`: show the dependency chart and status of coordinated issues.

## Coordinated flow

```
create-epic                  files the issues
coordinate-issues            launches each unblocked issue
 └─► launch-issue            one background session per issue
      ├─► execute-issue      opens the PR
      ├─► verify-change      runs verify-<surface> skills, then reports the PR ready
      ├─► handle-reviews     calls address-reviews until the PR merges
      └─► cleanup-issue      after the merge; the coordinator then launches newly unblocked issues
issue-status                 the chart, from any session
```

Verify surfaces are swappable: any skill that follows `verify-change`'s [contract](plugins/github-sdlc/skills/verify-change/references/contract.md) can be named as a surface.

## Install

```sh
claude plugin marketplace add JMichaelYang/skills-marketplace
claude plugin install github-sdlc@skills-marketplace
```

`claude plugin update` only picks up changes when the `version` in `plugins/github-sdlc/.claude-plugin/plugin.json` is bumped.
