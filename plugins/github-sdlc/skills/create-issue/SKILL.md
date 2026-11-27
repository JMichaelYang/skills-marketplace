---
name: create-issue
description: Use when the user wants to file new work, a bug, or an idea as a GitHub issue in the current repo.
---

1. Read the code the work touches: find the files it changes and the existing code it builds on.
2. Draft a short imperative title and a body following [references/template.md](references/template.md) exactly; respect its length limits. Keep Why and What brief and readable to a person, and put paths and implementation in Agent context, citing only files and code you read in step 1.
3. Create it: `gh issue create --title "<title>" --body-file <file>`.
4. Reply with the issue URL.
