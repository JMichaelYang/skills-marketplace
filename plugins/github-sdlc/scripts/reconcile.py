import argparse
import datetime
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sdlc_state

ACTIVE = ("running", "pr_open")
PR_FIELDS = "number,state,headRefName,body,mergedAt"
MAX_BACKOFF = 1800
TAKEOVER = re.compile(r"\b(?:take[- ]?over|took over|taken over)\b", re.I)
LOCK_NAME = (
    re.compile(r"\block\s+([A-Za-z0-9][\w.-]*)", re.I),
    re.compile(r"\b(?:take[- ]?over|took over|taken over)\s+(?:of\s+)?([A-Za-z0-9][\w.-]*)", re.I),
)


class Transient(Exception):
    pass


def query(cmd):
    try:
        return json.loads(sdlc_state.run(cmd) or "null") or []
    except sdlc_state.Fail as e:
        raise Transient(str(e))
    except ValueError as e:
        raise Transient(f"{' '.join(cmd[:3])} returned invalid JSON: {e}")


def parse_time(text):
    return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))


def pr_number(value):
    match = re.search(r"(\d+)\s*$", str(value or ""))
    return int(match.group(1)) if match else None


def merged_at(n, issue, prs):
    want = pr_number(issue.get("pr"))
    closes = re.compile(rf"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s+#{n}\b", re.I)
    times = [
        pr["mergedAt"] for pr in prs
        if pr.get("state") == "MERGED" and pr.get("mergedAt") and (
            pr.get("number") == want
            or (pr.get("headRefName") or "").startswith(f"{n}-")
            or closes.search(pr.get("body") or "")
        )
    ]
    return max(times, key=parse_time) if times else None


def alive(issue, agents):
    sid = issue.get("id")
    if sid:
        return any(a.get("id") == sid or str(a.get("sessionId") or "").startswith(sid) for a in agents)
    return any(a.get("name") == issue.get("session") for a in agents)


def read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def lock_table(locks):
    table = locks.get("locks") if isinstance(locks.get("locks"), dict) else locks
    return [k for k, v in table.items() if isinstance(v, dict)]


def lock_name(entry, text, names):
    if isinstance(entry, dict):
        for key in ("lock", "name"):
            if isinstance(entry.get(key), str):
                return entry[key]
    for name in sorted(names, key=len, reverse=True):
        if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", text):
            return name
    for pattern in LOCK_NAME:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return "unknown"


def takeovers(path):
    try:
        locks = read_json(path, {})
    except ValueError as e:
        raise Transient(f"cannot read {path}: {e}")
    if not isinstance(locks, dict):
        return []
    names = lock_table(locks)
    found = []
    for entry in locks.get("log") or []:
        if isinstance(entry, dict):
            kind = " ".join(str(entry.get(k) or "") for k in ("event", "action", "type", "kind"))
            text = kind.strip() or json.dumps(entry, sort_keys=True)
        else:
            text = str(entry)
        if TAKEOVER.search(text):
            found.append((json.dumps(entry, sort_keys=True), lock_name(entry, text, names)))
    return found


def check(path, grace, side):
    issues = sdlc_state.load(path)["issues"]
    if all(v.get("status") == "cleaned" for v in issues.values()):
        return [("all_done", None)]
    prs = query(["gh", "pr", "list", "--state", "all", "--limit", "200", "--json", PR_FIELDS])
    agents = query(["claude", "agents", "--json"])
    now = datetime.datetime.now(datetime.timezone.utc)
    events = []
    for key in sorted(issues, key=int):
        issue = issues[key]
        if issue.get("status") == "cleaned":
            continue
        at = merged_at(key, issue, prs)
        if at:
            if (now - parse_time(at)).total_seconds() >= grace:
                events.append((f"unreported_merge {key}", f"unreported_merge {key} {at}"))
            continue
        who = issue.get("id") or issue.get("session")
        if issue.get("status") in ACTIVE and who and not alive(issue, agents):
            events.append((f"dead_session {key}", f"dead_session {key} {who}"))
    found = takeovers(os.path.join(os.path.dirname(path), "locks.json"))
    if side["takeovers"] is None:
        side["takeovers"] = [k for k, _ in found]
    else:
        events += [(f"lock_takeover {name}", k) for k, name in found if k not in side["takeovers"]]
    return [(line, k) for line, k in events if k not in side["reported"]]


def record(side, events):
    for line, key in events:
        if line.startswith("lock_takeover"):
            side["takeovers"].append(key)
        elif key:
            side["reported"].append(key)


def main():
    p = argparse.ArgumentParser(
        prog="reconcile.py",
        description="Report coordinator anomalies: unreported_merge, dead_session, lock_takeover or all_done.",
    )
    p.add_argument("state", help="coordinator name or path to its state file")
    p.add_argument("--until-anomaly", action="store_true", help="poll until something new needs the coordinator")
    p.add_argument("--interval", type=float, default=300, help="seconds between polls (default 300)")
    p.add_argument("--grace", type=float, default=600, help="seconds a merge may stay uncleaned (default 600)")
    args = p.parse_args()
    if args.interval <= 0:
        p.error("--interval must be positive")
    if args.grace < 0:
        p.error("--grace must not be negative")
    try:
        for tool in ("gh", "claude"):
            if not shutil.which(tool):
                raise sdlc_state.Fail(f"{tool} not found on PATH")
        path = sdlc_state.resolve(args.state)
        sdlc_state.load(path)
        side_path = os.path.join(os.path.dirname(path), f".reconcile-{os.path.basename(path)}")
        side = read_json(side_path, None)
        fresh = side is None
        if fresh:
            side = {"reported": [], "takeovers": None}
        delay = args.interval
        while True:
            try:
                events = check(path, args.grace, side)
                delay = args.interval
            except Transient as e:
                if not args.until_anomaly:
                    raise sdlc_state.Fail(str(e))
                delay = min(delay * 2, max(MAX_BACKOFF, args.interval))
                print(f"{e}; retrying in {delay:g}s", file=sys.stderr)
                time.sleep(delay)
                continue
            if args.until_anomaly:
                record(side, events)
                if events or fresh:
                    sdlc_state.write(side_path, side)
                    fresh = False
            for line, _ in events:
                print(line)
            sys.stdout.flush()
            if events or not args.until_anomaly:
                return 0
            time.sleep(delay)
    except (sdlc_state.Fail, ValueError, KeyError) as e:
        print(f"reconcile: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
