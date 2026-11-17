---
name: verify-android
description: Use when the user or verify-change asks to verify, test, or check a change on an Android emulator or device.
---

Args: `[--issue <n>] [--scripts <dir>] <checks and rules>`, where rules may name the serial, build command, APK and package. Follow [../verify-change/references/contract.md](../verify-change/references/contract.md) with `<surface>` `android`; it defines `lock`, `<session>` and `<evidence>`.

- `<sdk>` is `$ANDROID_HOME` if set, else `~/Library/Android/sdk`. `adb` is `<sdk>/platform-tools/adb` if it exists, else `adb` on PATH; always run it as `adb -s <serial>`. `shell`, `exec-out` and `exec-in` rejoin their args into one device shell command, so quote spaces and `$` a second time, as below.
- Never start an emulator or run `emu`, `reboot`, `root`, `remount`, `uninstall`, `pm clear`, `settings put`, or `install` without `-r`. If install needs any of them (e.g. `INSTALL_FAILED_UPDATE_INCOMPATIBLE` or a downgrade), fail with its output.
- `<pkg>` is the rules' package, else `aapt2 dump packagename <apk>` with `aapt2` from the newest `<sdk>/build-tools/*`.

1. If no checks are for Android, end SKIPPED. `<serial>` is the one the rules name, else the only `emulator-*` that `adb devices` lists as `device`. End SKIPPED if it is not listed as `device` or `adb -s <serial> shell getprop sys.boot_completed` is not `1`.
2. Lock `android-<serial>` as the contract says, with Bash `run_in_background: true`, then end your turn.
3. Build and install:
   - `mkdir -p <evidence> && touch <evidence>/.build-start`, then run the rules' build command (else `./gradlew assembleDebug`) from the worktree root. `<apk>` is the rules' APK, else the one `.apk` under a `build/outputs/apk/` newer than `.build-start`; fail unless there is exactly one.
   - Note `pidof <pkg>`, the `lastUpdateTime` line of `dumpsys package <pkg>`, and `"date '+%Y-%m-%d %H:%M:%S'"`, all via `adb -s <serial> shell`.
   - `adb -s <serial> install -r <apk>` must print `Success`.
   - Confirm `lastUpdateTime` changed and is not before the noted date.
   - Snapshot data: `shell am force-stop <pkg>`, then `adb -s <serial> exec-out 'run-as <pkg> sh -c "tar -cf - \$(ls -A | grep -vx lib)"' > <evidence>/.data.tar`. If `run-as` fails, note that data must be undone by hand.
   - Launch with `shell monkey -p <pkg> -c android.intent.category.LAUNCHER 1`; `shell pidof <pkg>` must print a pid other than the noted one.
4. Run each check:
   - Find elements in `exec-out uiautomator dump /dev/tty` and tap the center of their `bounds` with `shell input tap <x> <y>`; also `input text`, `swipe` and `keyevent`. Re-dump until the expected node appears instead of sleeping.
   - Save `exec-out screencap -p > <evidence>/<check>.png` and the dump as `<evidence>/<check>.xml`.
   - The check fails if `pidof <pkg>` goes empty or `logcat -d -b crash` shows `<pkg>`; save `logcat -d --pid=<pid> > <evidence>/<check>.log` on failure.
5. Undo, then release:
   - `shell am force-stop <pkg>`. With a snapshot, `adb -s <serial> shell 'run-as <pkg> sh -c "find . -mindepth 1 -maxdepth 1 ! -name lib -exec rm -rf {} +"'`, then `adb -s <serial> exec-in run-as <pkg> tar -xf - < <evidence>/.data.tar`.
   - Also undo by hand what the checks changed outside the app's data, such as accounts or files on `/sdcard`.
   - `lock release android-<serial> --session <session> --note "<note>"`, naming the build and `<pkg>` left installed.
6. End with the contract's single line, `VERIFY android PASS|FAIL|SKIPPED: <line> [evidence: <paths>]`, listing the `.png`, `.xml` and `.log` files.
