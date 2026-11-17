#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

FAILED_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
VIEW_FIELDS = "state,mergeable,reviews,comments,statusCheckRollup"


def gh(*args):
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit("gh not found on PATH")
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return json.loads(result.stdout or "null")


def find_pr(issue):
    closes = re.compile(rf"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s+#{issue}\b", re.IGNORECASE)
    prs = gh("pr", "list", "--state", "all", "--limit", "200", "--json", "number,headRefName,body,state")
    matches = [
        pr for pr in prs or []
        if pr.get("headRefName", "").startswith(f"{issue}-") or closes.search(pr.get("body") or "")
    ]
    if not matches:
        return None
    matches.sort(key=lambda pr: (pr.get("state") == "OPEN", pr["number"]), reverse=True)
    return matches[0]["number"]


def one_line(text):
    return " ".join((text or "").split())


def login(item):
    return (item.get("author") or {}).get("login") or "unknown"


def items(view):
    for review in view.get("reviews") or []:
        if review.get("state") == "PENDING":
            continue
        yield f"review:{review['id']}", f"review {review.get('state')} by {login(review)}: {one_line(review.get('body'))}"
    for comment in view.get("comments") or []:
        yield f"comment:{comment['id']}", f"comment by {login(comment)}: {one_line(comment.get('body'))}"
    for check in view.get("statusCheckRollup") or []:
        name = check.get("name") or check.get("context") or "unknown"
        outcome = check.get("conclusion") or check.get("state") or ""
        if outcome.upper() in FAILED_CONCLUSIONS:
            run = check.get("detailsUrl") or check.get("targetUrl") or check.get("startedAt") or ""
            yield f"ci:{name}:{run}", f"ci_failed {name}"


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save(path, state):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".watch-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def poll(issue, path):
    pr = find_pr(issue)
    if pr is None:
        return []
    view = gh("pr", "view", str(pr), "--json", VIEW_FIELDS)
    state = load(path)
    baseline = state is None or state.get("pr") != pr
    if baseline:
        state = {"pr": pr, "seen": [], "conflicting": False}
    seen = set(state["seen"])
    events = []
    for key, line in items(view):
        if key not in seen:
            seen.add(key)
            events.append(line)
    pr_state = view.get("state")
    mergeable = view.get("mergeable")
    if pr_state == "OPEN" and mergeable == "CONFLICTING" and not state["conflicting"]:
        events.append("conflicting")
    if mergeable in ("CONFLICTING", "MERGEABLE"):
        state["conflicting"] = mergeable == "CONFLICTING"
    state["seen"] = sorted(seen)
    if baseline:
        events = []
    if pr_state == "MERGED":
        events.append("merged")
    elif pr_state == "CLOSED":
        events.append("closed")
    for line in events:
        print(line)
    sys.stdout.flush()
    save(path, state)
    return events


def main():
    parser = argparse.ArgumentParser(description="Wait for new events on an issue's PR.")
    parser.add_argument("issue", type=int)
    parser.add_argument("state_dir")
    parser.add_argument("--interval", type=float, default=60, help="seconds between polls (default 60)")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    os.makedirs(args.state_dir, exist_ok=True)
    path = os.path.join(args.state_dir, f"watch-{args.issue}.json")
    while True:
        try:
            if poll(args.issue, path):
                return 0
        except (RuntimeError, json.JSONDecodeError) as e:
            print(e, file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
