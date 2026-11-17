import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

PLACEHOLDER = re.compile(r"\{T(\d+)\}")
BLOCKED = re.compile(r"Blocked by ([^\n]*)")
REFS = re.compile(r"(?:\{T\d+\}|#\d+)(?:, (?:\{T\d+\}|#\d+))*\.")
ISSUE_URL = re.compile(r"/issues/(\d+)\s*$")


def fail(message):
    print(f"create_epic: {message}", file=sys.stderr)
    sys.exit(2)


def load_plan(path):
    try:
        with open(path) as f:
            plan = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"cannot read plan {path}: {e}")
    if not isinstance(plan, list) or not plan:
        fail("plan must be a non-empty JSON list")
    for i, ticket in enumerate(plan, 1):
        if not isinstance(ticket, dict):
            fail(f"T{i} must be an object")
        for key in ("title", "body"):
            if not isinstance(ticket.get(key), str) or not ticket[key].strip():
                fail(f"T{i} needs a non-empty {key}")
        labels = ticket.get("labels", [])
        if not isinstance(labels, list) or not all(isinstance(l, str) and l for l in labels):
            fail(f"T{i} labels must be a list of strings")
        for line in BLOCKED.findall(ticket["body"]):
            if not REFS.fullmatch(line.strip()):
                fail(f"T{i} has 'Blocked by {line.strip()}'; list only {{T<k>}} or #N refs, comma-separated, ending in '.'")
        for k in map(int, PLACEHOLDER.findall(ticket["body"])):
            if not 1 <= k < i:
                fail(f"T{i} references {{T{k}}}, which is not an earlier ticket")
    return plan


def load_state(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"cannot read state {path}: {e}")
    return {int(k): int(v) for k, v in state.items()}


def save_state(path, state):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump({str(k): v for k, v in sorted(state.items())}, f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def render(body, state):
    return PLACEHOLDER.sub(lambda m: f"#{state[int(m.group(1))]}" if int(m.group(1)) in state else m.group(0), body)


def blockers(body):
    found = []
    for line in BLOCKED.findall(body):
        for n in re.findall(r"#(\d+)", line):
            if int(n) not in found:
                found.append(int(n))
    return found


def create(ticket, body, repo, workdir):
    fd, body_path = tempfile.mkstemp(dir=workdir, suffix=".md")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(body)
        cmd = ["gh", "issue", "create", "--title", ticket["title"], "--body-file", body_path]
        for label in ticket.get("labels", []):
            cmd += ["--label", label]
        if repo:
            cmd += ["--repo", repo]
        result = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(body_path)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return None
    match = ISSUE_URL.search(result.stdout.strip())
    if not match:
        sys.stderr.write(result.stdout)
        return None
    return int(match.group(1)), result.stdout.strip()


def report(plan, state):
    rows = []
    edges = {}
    for i, ticket in enumerate(plan, 1):
        n = state[i]
        deps = blockers(render(ticket["body"], state))
        title = ticket["title"].replace("|", "\\|")
        rows.append(f"| #{n} | {title} | {', '.join(f'#{d}' for d in deps) or '—'} |")
        for d in deps:
            edges.setdefault(d, []).append(n)
    print("| # | Title | Blocked by |")
    print("|---|---|---|")
    print("\n".join(rows))
    print()
    print("```")
    blocked = {n for children in edges.values() for n in children}
    filed = [state[i] for i in range(1, len(plan) + 1)]
    sources = [d for d in edges if d not in filed] + filed
    for n in sources:
        if n in edges:
            print(f"#{n} ─► " + ", ".join(f"#{c}" for c in edges[n]))
        elif n not in blocked:
            print(f"#{n} (independent)")
    print("```")


def main():
    parser = argparse.ArgumentParser(prog="create_epic.py")
    parser.add_argument("plan")
    parser.add_argument("--repo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan = load_plan(args.plan)
    state_path = re.sub(r"\.json$", "", args.plan) + ".filed.json"
    state = load_state(state_path)
    unknown = [i for i in state if not 1 <= i <= len(plan)]
    if unknown:
        fail(f"{state_path} records tickets missing from the plan: {unknown}")
    workdir = os.path.dirname(os.path.abspath(args.plan))

    pending = [i for i in range(1, len(plan) + 1) if i not in state]
    if args.dry_run:
        for i in pending:
            ticket = plan[i - 1]
            labels = ", ".join(ticket.get("labels", [])) or "none"
            print(f"## T{i}: {ticket['title']} (labels: {labels})\n\n{render(ticket['body'], state)}\n")
        print(f"{len(plan) - len(pending)} filed, {len(pending)} to file")
        return

    for count, i in enumerate(pending):
        if count:
            time.sleep(3)
        ticket = plan[i - 1]
        created = create(ticket, render(ticket["body"], state), args.repo, workdir)
        if created is None:
            print(f"create_epic: failed to file T{i}; fix the cause and rerun to resume", file=sys.stderr)
            sys.exit(1)
        state[i] = created[0]
        save_state(state_path, state)
        print(f"T{i} {created[1]}", flush=True)

    report(plan, state)


if __name__ == "__main__":
    main()
