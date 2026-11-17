# Surface contract

A surface is a skill that verifies a change on one kind of device, e.g. `github-sdlc:verify-android`. verify-change runs surfaces, and a user may run one directly. Every surface follows this contract.

- Args: `[--issue <n>] [--scripts <dir>] <checks and rules>`. The rules may name the device, the build command and the app; never ask for what they answer. Run only the checks meant for this surface.
- `<surface>` is the short name for a github-sdlc surface (`android` for `github-sdlc:verify-android`), else the full skill name.
- `lock <cmd>` means `python3 -I <scripts>/sdlc_state.py lock <cmd>`, where `<scripts>` is `--scripts`, else `<base>/../../scripts` with `<base>` the surface's base directory. Run it from inside the repo: `locks.json` is shared by all its worktrees.
- `<session>` is `$CLAUDE_CODE_SESSION_ID`, which `claude agents --json` lists. Under any other name a waiter takes the lock over at once.
- `<evidence>` is `<dir>/verify-<surface>`, where `<dir>` is `$CLAUDE_JOB_DIR/tmp` if set, else a new `mktemp -d`.
- Once the lock is held, a failing step skips to step 5, then ends FAIL.

1. Pick the device: the one the rules name, else the only one running. If none fits, or several do and the rules name none, end SKIPPED saying which.
2. Lock it. The name is per device instance, e.g. `android-emulator-5554` or `ios-sim-<udid>`. Run `lock acquire <name> --session <session> [--issue <n>] --wait` with Bash `run_in_background: true`, then end your turn; you are woken when it exits, so the wait costs no turns. Exit 0 prints `acquired <name>`, and `note: <note>` with the previous holder's note, which says what it left installed. Otherwise end FAIL with its stderr. To give up while queued, stop the task, which leaves the queue. Waiters take over a lock held past 30 minutes, so finish within that.
3. Build and install per the rules, from this worktree, onto this device only. Confirm the build running is the one you just installed, e.g. by the install time or version the device reports and a process started after the install.
4. Run the checks and save evidence (screenshots, logs, UI dumps) under `<evidence>`, named by check.
5. Undo app data the checks changed, such as accounts, files and in-app settings. Never change device-wide state: do not start, stop, reboot or wipe the device, uninstall apps, or change system settings or other apps. Then `lock release <name> --session <session> --note "<note>"`, where the note is one line with the result and what is now installed, e.g. `#42 PASS; left 42-fade-page-transitions build installed`.
6. End your reply with exactly one line: `VERIFY <surface> PASS|FAIL|SKIPPED: <line>`, adding ` [evidence: <paths>]` with comma-separated absolute paths when evidence was saved. `<line>` says what was checked and why it failed or was skipped. PASS needs every check to pass on the confirmed build; SKIPPED is only for a missing device or no checks for this surface.
