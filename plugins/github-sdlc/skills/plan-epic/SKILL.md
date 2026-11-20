---
name: plan-epic
description: Use when the user asks to plan, scope, or break down a multi-part change into GitHub issues before running them.
---

Args: `<the work to plan>`.

1. Load EnterPlanMode and ExitPlanMode with ToolSearch `select:EnterPlanMode,ExitPlanMode`, and enter plan mode unless already in it.
2. Explore: read the repo's architecture docs, the code each part touches, and `git log` for how similar features were split into PRs. Before calling a step manual, check which tools and CLIs can reach systems outside the repo.
3. Ask: put every unknown that changes the plan, such as names, values, visuals or scope, to the user with AskUserQuestion, using `preview` for visual choices. Ask again after each answer until none remain; never guess.
4. Write the plan file plan mode names:
   - `## Context`: each part, the code it touches with paths, and the user's answers.
   - `## Dependency graph`: tickets `T<k>` as an ASCII chart, then which are ready immediately and which share files.
   - `## Tickets`: one per small, single-purpose PR, split along layers such as design system, model, platform and wiring, each with concrete paths, the change and its tests. Work outside the repo gets its own tickets.
   - `## Verification`: the checks every ticket runs, then the end-to-end checks and verify surfaces after the last one.
5. Show it with ExitPlanMode. On feedback, revise and show it again; when the user asks for smaller tickets, split by layer or concern until each does one thing.
6. Once the user approves in auto mode, run `/github-sdlc:create-epic` with the plan path and the ticket list, then `/github-sdlc:coordinate-issues <numbers> <rules>`, with rules naming the pre-push checks and verify surfaces from Verification. If the user approves outside auto mode, ask them to switch to it first.
