import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

STATUSES = ("waiting", "running", "pr_open", "merged", "cleaned")
DONE = ("merged", "cleaned")
FIELDS = ("blockers", "session", "id", "status", "pr", "verify", "notes")
APPENDABLE = ("blockers", "notes")
RESERVED = ("locks.json",)
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STAMP = "%Y-%m-%dT%H:%M:%SZ"
MIN_STALE = 60
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
    return datetime.datetime.now(datetime.timezone.utc).strftime(STAMP)


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


def holding(lock):
    holder, session = lock.get("holder"), lock.get("session")
    who = str(holder or session or "free")
    if holder and session and str(session) != str(holder):
        who += f" ({session})"
    return who


def locks_path():
    return os.path.join(state_dir(), "locks.json")


def load_locks():
    path = locks_path()
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
            queue = ", ".join(queued(q) for q in lock.get("queue") or []) or "-"
            print(f"| {cell(name)} | {cell(holding(lock))} | {cell(lock.get('since'))} | {cell(queue)} | {cell(lock.get('note'))} |")


def check_lock(name):
    if not NAME_RE.match(name):
        raise Fail(f"invalid lock name: {name}")
    return name


def stamp(text):
    try:
        return datetime.datetime.strptime(text, STAMP).replace(tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def alive_sessions():
    try:
        out = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True, timeout=60)
        agents = json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        agents = None
    if not isinstance(agents, list):
        return None
    return {str(a[k]) for a in agents if isinstance(a, dict) for k in ("name", "id", "sessionId") if a.get(k)}


def log_lock(entry):
    with open(os.path.join(state_dir(), "locks.log"), "a") as fh:
        fh.write(json.dumps(dict(at=now(), **entry)) + "\n")


def reap(name, lock, me, alive, max_hold, t):
    held = lock.get("session")
    if held and held != me:
        if alive is not None and held not in alive:
            reason = "missing from claude agents"
        elif t - stamp(lock.get("since")) > max_hold:
            reason = f"held past {max_hold / 60:g}m"
        else:
            reason = None
        if reason:
            log_lock({"lock": name, "event": "takeover", "from": held, "holder": lock.get("holder"), "by": me, "reason": reason})
            print(f"took over {name} from {held}: {reason}", file=sys.stderr)
            lock.update(holder=None, session=None, since=None, note=f"taken over from {held}: {reason}")
    lock["queue"] = [
        q for q in lock.get("queue") or []
        if q.get("session") == me
        or not (
            (alive is not None and q.get("session") not in alive)
            or t - stamp(q.get("seen")) > max(MIN_STALE, 3 * float(q.get("poll") or 0))
        )
    ]


def leave(path, name, me):
    with locked(path):
        locks = load_locks()
        lock = locks.get(name)
        if lock:
            lock["queue"] = [q for q in lock.get("queue") or [] if q.get("session") != me]
            write(path, locks)


def interrupt(signum, frame):
    raise KeyboardInterrupt


def cmd_lock_acquire(args):
    name = check_lock(args.name)
    if args.poll <= 0 or args.max_hold <= 0:
        raise Fail("--poll and --max-hold must be positive")
    path = locks_path()
    me = args.session
    issue = number(args.issue) if args.issue else None
    signal.signal(signal.SIGTERM, interrupt)
    try:
        while True:
            alive = alive_sessions()
            with locked(path):
                locks = load_locks()
                lock = locks.setdefault(name, {"holder": None, "session": None, "since": None, "note": None, "queue": []})
                reap(name, lock, me, alive, args.max_hold * 60, time.time())
                queue = lock["queue"]
                mine = next((q for q in queue if q.get("session") == me), None)
                got = lock["session"] == me
                if not got and lock["session"] is None and (not queue or queue[0] is mine):
                    lock.update(holder=f"#{issue}" if issue else me, session=me, since=now())
                    if mine:
                        queue.remove(mine)
                    got = True
                elif not got and args.wait:
                    if mine is None:
                        mine = {"session": me, "issue": issue, "since": now()}
                        queue.append(mine)
                    mine.update(seen=now(), poll=args.poll)
                write(path, locks)
                state = dict(lock)
            if got:
                print(f"acquired {name}")
                if state.get("note"):
                    print(f"note: {state['note']}")
                return
            if not args.wait:
                holder = holding(state) if state.get("session") else "the queue"
                raise Fail(f"{name} is held by {holder}; pass --wait to queue")
            time.sleep(args.poll)
    except KeyboardInterrupt:
        leave(path, name, me)
        raise Fail(f"stopped waiting for {name}")


def cmd_lock_release(args):
    name = check_lock(args.name)
    path = locks_path()
    with locked(path):
        locks = load_locks()
        lock = locks.get(name)
        if not lock:
            raise Fail(f"no lock named {name}")
        if lock.get("session") == args.session:
            lock.update(holder=None, session=None, since=None, note=args.note or None)
        else:
            queue = lock.get("queue") or []
            lock["queue"] = [q for q in queue if q.get("session") != args.session]
            if len(lock["queue"]) == len(queue):
                raise Fail(f"{args.session} does not hold {name}")
        write(path, locks)


def cmd_lock_status(args):
    locks = load_locks()
    names = [check_lock(args.name)] if args.name else sorted(locks)
    t = time.time()
    for name in names:
        lock = locks.get(name)
        if lock is None:
            raise Fail(f"no lock named {name}")
        if lock.get("session"):
            print(f"{name}: held by {holding(lock)} since {lock.get('since')} ({(t - stamp(lock.get('since'))) / 60:.0f}m)")
        else:
            print(f"{name}: free")
        if lock.get("note"):
            print(f"  note: {lock['note']}")
        if lock.get("queue"):
            print("  queue: " + ", ".join(queued(q) for q in lock["queue"]))


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
    s = sub.add_parser("lock", help="FIFO locks on shared devices, kept in locks.json")
    ls = s.add_subparsers(dest="lock_cmd", required=True)
    s = ls.add_parser("acquire", help="take a lock, or with --wait queue until it is yours")
    s.add_argument("name")
    s.add_argument("--session", required=True)
    s.add_argument("--issue")
    s.add_argument("--wait", action="store_true")
    s.add_argument("--max-hold", type=float, default=30, metavar="MINUTES", help="take over a holder older than this (default 30)")
    s.add_argument("--poll", type=float, default=10, metavar="SECONDS", help="seconds between checks while waiting (default 10)")
    s.set_defaults(func=cmd_lock_acquire)
    s = ls.add_parser("release", help="release a lock, or leave its queue")
    s.add_argument("name")
    s.add_argument("--session", required=True)
    s.add_argument("--note", default="", help="one-line result for the next holder")
    s.set_defaults(func=cmd_lock_release)
    s = ls.add_parser("status", help="print holders, notes and queues")
    s.add_argument("name", nargs="?")
    s.set_defaults(func=cmd_lock_status)
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
