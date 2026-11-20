---
name: plan-epic
description: Use when the user asks to plan, scope, or break down a multi-part change into GitHub issues before running them.
---

Args: `<the work to plan>`.

1. Load EnterPlanMode and ExitPlanMode with ToolSearch `select:EnterPlanMode,ExitPlanMode`, and enter plan mode unless already in it.
2. Explore: read the repo's architecture docs and the code each part touches.
3. Ask: put every unknown that changes the plan, such as names, values, visuals or scope, to the user with AskUserQuestion, using `preview` for visual choices. Ask again after each answer until none remain; never guess.
4. Design: write the plan file plan mode names with `## Problem`, `## Solution` (the approach, the code it touches with paths, and the user's answers) and `## System diagram` (an ASCII diagram of the components involved and how the change flows through them). Present it in a reply and wait; on feedback, revise and present it again until the user confirms it.
5. Break down: add to the plan:
   - `## Dependency graph`: tickets `T<k>` as an ASCII chart, then which are ready immediately and which share files.
   - `## Tickets`: one per small, single-purpose PR, each with concrete paths, the change and its tests.
   - `## Verification`: the checks every ticket runs, then the end-to-end checks and verify surfaces after the last one.

   Show it with ExitPlanMode. On feedback, revise and show it again; when the user asks for smaller tickets, split them until each does one thing.
6. Once the user approves in auto mode, run `/github-sdlc:create-epic` with the plan path and the ticket list, then `/github-sdlc:coordinate-issues <numbers> <rules>`, with rules naming the pre-push checks and verify surfaces from Verification. If the user approves outside auto mode, ask them to switch to it first.
