---
name: verify-change
description: Use when the user or a brief asks to verify, test, or check a change on one or more device surfaces, such as Android, iOS, web or a project's own.
---

Args: `<surfaces> [--issue <n>] <checks and rules>`, where `<surfaces>` is comma-separated, e.g. `android` or `android,acme:verify-kiosk`.

1. Resolve each surface to a skill: a name containing `:` is used as is, and any other `<name>` is `github-sdlc:verify-<name>`.
2. Run each in order with the Skill tool, passing `[--issue <n>] --scripts <base>/../../scripts <checks and rules>`, where `<base>` is this skill's base directory. Surfaces follow [references/contract.md](references/contract.md). Keep the last line of its reply that starts with `VERIFY `; if the skill is missing or gives no such line, use `VERIFY <surface> FAIL: <why>`. Run every surface even after a FAIL.
3. Reply with the VERIFY lines in order, then `VERIFY all <result>: <p> passed, <f> failed, <s> skipped`, where `<result>` is FAIL if any failed, else SKIPPED if any skipped, else PASS.
