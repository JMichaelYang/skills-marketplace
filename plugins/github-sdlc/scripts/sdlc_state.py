import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile

STATUSES = ("waiting", "running", "pr_open", "merged", "cleaned")
DONE = ("merged", "cleaned")
FIELDS = ("blockers", "session", "id", "status", "pr", "verify", "notes")
APPENDABLE = ("blockers", "notes")
RESERVED = ("locks.json",)
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
BLOCKED_RE = re.compile(r"blocked by\s+((?:#\d+(?:\s*(?:,|and|&)\s*)?)+)", re.I)


class Fail(Exception):
    pass


def run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise Fail(f"{cmd[0]} not found on PATH")
    if out.returncode:
        raise Fail(f"{' '.join(cmd)} failed: {out.stderr.strip()}")
    return out.stdout


def state_dir():
    common = run(["git", "rev-parse", "--git-common-dir"]).strip()
    return os.path.join(os.path.abspath(common), "github-sdlc")


def is_state_file(name):
    return (
        name.endswith(".json")
        and name not in RESERVED
        and not name.startswith(("watch-", "."))
    )


def check_name(name):
    if not NAME_RE.match(name) or not is_state_file(name + ".json"):
        raise Fail(f"invalid coordinator name: {name}")
    return name


def resolve(arg):
    if arg and (os.sep in arg or arg.endswith(".json")):
        return os.path.abspath(arg)
    d = state_dir()
    if arg:
        return os.path.join(d, check_name(arg) + ".json")
    found = sorted(f for f in os.listdir(d) if is_state_file(f)) if os.path.isdir(d) else []
    if len(found) == 1:
        return os.path.join(d, found[0])
    if not found:
        raise Fail(f"no state in {d}; run init first")
    raise Fail("several state files, pass --state: " + ", ".join(f[:-5] for f in found))


@contextlib.contextmanager
def locked(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise Fail(f"no state at {path}; run init first")


def write(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update(path, event, change):
    with locked(path):
        data = load(path)
        change(data)
        data["log"].append({"at": now(), "event": event})
        write(path, data)


def number(text):
    raw = str(text).lstrip("#")
    if not raw.isdigit():
        raise Fail(f"not an issue number: {text}")
    return int(raw)


def blockers_in(body):
    found = []
    for match in BLOCKED_RE.finditer(body or ""):
        for b in re.findall(r"#(\d+)", match.group(1)):
            if int(b) not in found:
                found.append(int(b))
    return found


def view(n, fields):
    return json.loads(run(["gh", "issue", "view", str(n), "--json", fields]))


def fetch(numbers, known):
    tracked = set(known) | set(numbers)
    open_cache = {}
    entries = {}
    for n in numbers:
        issue = view(n, "number,title,body")
        blockers = []
        for b in blockers_in(issue.get("body")):
            if b == n:
                continue
            if b not in tracked:
                if b not in open_cache:
                    open_cache[b] = view(b, "state").get("state") == "OPEN"
                if not open_cache[b]:
                    continue
            blockers.append(b)
        entries[str(n)] = {
            "title": issue.get("title", ""),
            "blockers": blockers,
            "session": None,
            "id": None,
            "status": "waiting",
            "pr": None,
            "verify": None,
            "notes": "",
        }
    return entries


def unique(numbers):
    out = []
    for n in numbers:
        if n not in out:
            out.append(n)
    return out


def cmd_init(args):
    name = check_name(args.coordinator)
    path = os.path.join(state_dir(), name + ".json")
    if args.rules_file == "-":
        rules = sys.stdin.read()
    elif args.rules_file:
        with open(args.rules_file) as fh:
            rules = fh.read()
    else:
        rules = ""
    numbers = unique(number(n) for n in args.issues)
    issues = fetch(numbers, [])
    with locked(path):
        if os.path.exists(path):
            raise Fail(f"state already exists at {path}")
        write(path, {
            "coordinator": name,
            "rules": rules,
            "issues": issues,
            "log": [{"at": now(), "event": "init " + " ".join(f"#{n}" for n in numbers)}],
        })
    print(path)


def cmd_add(args):
    path = resolve(args.state)
    numbers = unique(number(n) for n in args.issues)
    existing = [int(k) for k in load(path)["issues"]]
    entries = fetch([n for n in numbers if n not in existing], existing)
    added = []

    def change(data):
        for key, entry in entries.items():
            if key not in data["issues"]:
                data["issues"][key] = entry
                added.append(key)

    update(path, "add " + " ".join(f"#{n}" for n in numbers), change)
    for n in numbers:
        if str(n) not in added:
            print(f"#{n} already tracked", file=sys.stderr)


def parse_pair(pair):
    if "=" not in pair:
        raise Fail(f"expected k=v or k+=v: {pair}")
    key, value = pair.split("=", 1)
    append = key.endswith("+")
    key = key.rstrip("+")
    if key not in FIELDS:
        raise Fail(f"unknown field {key}; expected one of {', '.join(FIELDS)}")
    if append and key not in APPENDABLE:
        raise Fail(f"+= only works for {', '.join(APPENDABLE)}")
    if key == "blockers":
        value = unique(int(b) for b in re.findall(r"\d+", value))
    elif key == "status" and value not in STATUSES:
        raise Fail(f"unknown status {value}; expected one of {', '.join(STATUSES)}")
    elif key == "notes":
        pass
    elif value == "":
        value = None
    return key, value, append


def cmd_set(args):
    path = resolve(args.state)
    n = str(number(args.issue))
    pairs = [parse_pair(p) for p in args.pairs]

    def change(data):
        issue = data["issues"].get(n)
        if issue is None:
            raise Fail(f"#{n} is not tracked; add it first")
        for key, value, append in pairs:
            if not append:
                issue[key] = value
            elif key == "blockers":
                issue[key] = unique(issue[key] + value)
            else:
                issue[key] = f"{issue[key]}\n{value}" if issue[key] else value

    update(path, f"set #{n} " + " ".join(args.pairs), change)


def cmd_get(args):
    data = load(resolve(args.state))
    if args.issue is None:
        out = data
    else:
        n = str(number(args.issue))
        if n not in data["issues"]:
            raise Fail(f"#{n} is not tracked")
        out = dict(number=int(n), **data["issues"][n])
    json.dump(out, sys.stdout, indent=2)
    print()


def cmd_unblocked(args):
    issues = load(resolve(args.state))["issues"]
    for n in sorted(int(k) for k, v in issues.items() if is_ready(issues, v)):
        print(n)


def is_ready(issues, v):
    return v["status"] == "waiting" and all(
        issues.get(str(b), {}).get("status") in DONE for b in v["blockers"]
    )


def label(issues, n):
    v = issues[n]
    text = f"#{n} {v.get('title', '')}".rstrip()
    if v["status"] in DONE:
        return f"{text} ✅"
    if is_ready(issues, v):
        return f"{text} ◄ ready"
    return f"{text} ({v['status']})"


def graph(issues):
    keys = sorted(issues, key=int)
    tracked = {k: [str(b) for b in issues[k]["blockers"] if str(b) in issues] for k in keys}
    depth = {}

    def level(k, seen=()):
        if k not in depth:
            parents = [p for p in tracked[k] if p not in seen]
            depth[k] = 1 + max((level(p, seen + (k,)) for p in parents), default=-1)
        return depth[k]

    parent = {}
    for k in keys:
        if tracked[k]:
            parent[k] = max(tracked[k], key=lambda p: (level(p), int(p)))
    children = {k: [c for c in keys if parent.get(c) == k] for k in keys}
    lines = []
    placed = set()

    def walk(k, prefix, branch, last, under=None):
        placed.add(k)
        others = [f"#{p}" for p in tracked[k] if p != under]
        extra = f" ◄ {'also ' if under else ''}{', '.join(others)}" if others else ""
        lines.append(prefix + branch + label(issues, k) + extra)
        pad = prefix + ("" if not branch else "    " if last else "│   ")
        kids = [c for c in children[k] if c not in placed]
        for i, c in enumerate(kids):
            end = i == len(kids) - 1
            walk(c, pad, "└─► " if end else "├─► ", end, k)

    for k in keys:
        if k not in parent:
            walk(k, "", "", True)
    for k in keys:
        if k not in placed:
            walk(k, "", "", True)
    return lines


def cell(value):
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def pr_link(pr):
    if pr is None or pr == "":
        return "-"
    pr = str(pr)
    return f"#{pr}" if pr.isdigit() else cell(pr)


def queued(entry):
    if isinstance(entry, dict):
        who = entry.get("session") or entry.get("holder") or "?"
        return f"{who} (#{entry['issue']})" if entry.get("issue") else str(who)
    return str(entry)


def load_locks():
    path = os.path.join(state_dir(), "locks.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise Fail(f"cannot read {path}: {e}")


def cmd_show(args):
    data = load(resolve(args.state))
    issues = data["issues"]
    locks = load_locks()
    print(f"Coordinator: {data.get('coordinator', '?')}")
    print()
    print("```")
    print("\n".join(graph(issues)) if issues else "(no issues)")
    print("```")
    print()
    print("| Issue | Session | Status | PR | Verify |")
    print("|---|---|---|---|---|")
    for k in sorted(issues, key=int):
        v = issues[k]
        print(f"| #{k} | {cell(v.get('session'))} | {cell(v['status'])} | {pr_link(v.get('pr'))} | {cell(v.get('verify'))} |")
    if locks:
        print()
        print("| Lock | Holder | Since | Queue | Note |")
        print("|---|---|---|---|---|")
        for name in sorted(locks):
            lock = locks[name] or {}
            holder, session = lock.get("holder"), lock.get("session")
            who = str(holder or session or "free")
            if holder and session and str(session) != str(holder):
                who += f" ({session})"
            queue = ", ".join(queued(q) for q in lock.get("queue") or []) or "-"
            print(f"| {cell(name)} | {cell(who)} | {cell(lock.get('since'))} | {cell(queue)} | {cell(lock.get('note'))} |")


def parser():
    state = argparse.ArgumentParser(add_help=False)
    state.add_argument("--state", help="coordinator name or path to its state file")
    p = argparse.ArgumentParser(prog="sdlc_state.py", description="Shared state for coordinated GitHub issues.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create <coordinator>.json from issues")
    s.add_argument("coordinator")
    s.add_argument("--issues", nargs="+", required=True)
    s.add_argument("--rules-file", help="file holding the rules text, or - for stdin")
    s.set_defaults(func=cmd_init)
    s = sub.add_parser("add", parents=[state], help="track more issues")
    s.add_argument("issues", nargs="+")
    s.set_defaults(func=cmd_add)
    s = sub.add_parser("set", parents=[state], help="set k=v or append k+=v on an issue")
    s.add_argument("issue")
    s.add_argument("pairs", nargs="+", metavar="k=v")
    s.set_defaults(func=cmd_set)
    s = sub.add_parser("get", parents=[state], help="print an issue, or the whole state")
    s.add_argument("issue", nargs="?")
    s.set_defaults(func=cmd_get)
    s = sub.add_parser("unblocked", parents=[state], help="print waiting issues whose blockers merged")
    s.set_defaults(func=cmd_unblocked)
    s = sub.add_parser("show", parents=[state], help="print the dependency chart, status table and locks")
    s.set_defaults(func=cmd_show)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        args.func(args)
    except Fail as e:
        print(f"sdlc_state: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
