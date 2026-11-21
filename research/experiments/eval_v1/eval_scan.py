"""Replay `trellis scan` on AIDev agent PRs and measure which flags the PR itself later undid.

Counts are per distinct line text per file per PR, summed over all of the PR's commits, so commit order
(which AIDev does not record) does not matter. A line flag is *undone* when the PR removes that text from the
file at least as many times as it adds it (no added copy survives). A scope flag is *undone* when the PR's
commits cancel out on that file: every line text is added and removed equally often. Undone flags are a proxy
for "a reviewer, CI or the agent corrected it"; a merged PR where none of a check's flags were undone counts as
one false alarm for that check.

Usage: python eval_scan.py <AIDev dir> <out.json> [--sample N] [--seed S]
"""

import argparse
import collections
import json
import random
import time
from pathlib import Path

import pyarrow.parquet as pq
from rd0_trellis import paths as P
from rd0_trellis.config import Config
from rd0_trellis.diff import FileDiff, from_github_files
from rd0_trellis.rules import line_rules, scope_findings

ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("out")
ap.add_argument("--sample", type=int, default=30000)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
D = Path(a.data)
cfg = Config()
RULES = line_rules(cfg)

commits = collections.Counter(pq.read_table(D / "pr_commits.parquet", columns=["pr_id"]).column("pr_id").to_pylist())
pool = sorted(str(p) for p, n in commits.items() if n >= 2)
random.Random(a.seed).shuffle(pool)
need = set(pool[: a.sample])

pr = {}
t = pq.read_table(D / "pull_request.parquet", columns=["id", "title", "body", "agent", "merged_at", "repo_url"])
for row in t.to_pylist():
    pid = str(row["id"])
    if pid in need:
        pr[pid] = row
need &= set(pr)

added = collections.defaultdict(collections.Counter)  # (pid, path) -> hash(line) -> times added in the PR
removed = collections.defaultdict(collections.Counter)
files = collections.defaultdict(dict)  # pid -> path -> status (first seen)
flags = set()  # (pid, path, rule, hash(line))
t0 = time.time()
pf = pq.ParquetFile(D / "pr_commit_details.parquet")
cols = [c for c in ("pr_id", "sha", "filename", "status", "patch", "previous_filename") if c in pf.schema_arrow.names]
for g in range(pf.num_row_groups):
    tb = pf.read_row_group(g, columns=cols).to_pylist()
    for r in tb:
        pid = str(r["pr_id"])
        if pid not in need or not r.get("filename"):
            continue
        fds = from_github_files([r])
        if not fds:
            continue
        f = fds[0]
        files[pid].setdefault(f.path, f.status)
        key = (pid, f.path)
        for _, ln in f.added:
            added[key][hash(ln.strip())] += 1
        for _, ln in f.removed:
            removed[key][hash(ln.strip())] += 1
        if f.status == "deleted" or P.is_skipped(f.path, cfg.ignore):
            continue
        text = dict(f.added)
        for rule in RULES:
            if rule.applies(f.path):
                for no, *_ in rule.hits(f.path, f.added):
                    flags.add((pid, f.path, rule.id, hash(text.get(no, "").strip())))
    if g % 20 == 0:
        print(g, pf.num_row_groups, len(flags), round(time.time() - t0), flush=True)


def undone_line(pid, path, h):
    return removed[(pid, path)][h] >= added[(pid, path)][h] > 0


def undone_file(pid, path):
    ad, rm = added[(pid, path)], removed[(pid, path)]
    return bool(ad or rm) and ad == rm


# Line baseline, same unit and label as a line flag: distinct added code-line texts per file per PR.
base_n = base_u = 0
for (pid, path), ad in added.items():
    if not P.is_code(path) or P.is_skipped(path, cfg.ignore):
        continue
    for h in ad:
        base_n += 1
        base_u += undone_line(pid, path, h)

# File base rate: share of changed files whose whole change another commit in the same PR reverts.
fbase_n = fbase_u = 0
for pid, fs in files.items():
    for path in fs:
        fbase_n += 1
        fbase_u += undone_file(pid, path)


def wilson(k, n, z=1.96):
    if not n:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(c - h, 4), round(c + h, 4)]


by = collections.defaultdict(lambda: {"flags": 0, "undone": 0, "survived_merged": 0, "prs": set()})
pr_any = collections.defaultdict(lambda: [False, False])  # pid -> [flagged, any flag undone] for default-on rules
for pid, path, rule, h in sorted(flags):
    b = by[rule]
    b["flags"] += 1
    b["prs"].add(pid)
    u = undone_line(pid, path, h)
    b["undone"] += u
    pr_any[(rule, pid)][0] = True
    pr_any[(rule, pid)][1] |= u
    b["survived_merged"] += (not u) and bool(pr[pid]["merged_at"])

for pid, fs in files.items():
    fds = [FileDiff(path=p, status=s) for p, s in fs.items()]
    text = f'{pr[pid]["title"] or ""}\n{pr[pid]["body"] or ""}'
    for fnd in scope_findings(fds, text, cfg):
        m = fnd.message
        kind = "scope:" + (
            "lockfile" if "lockfile" in m.lower()
            else "gitignore" if "gitignore" in m
            else "ci" if "CI configuration" in m
            else "new-doc" if "new document" in m
            else "unrelated" if "outside the area" in m
            else "other"
        )
        b = by[kind]
        b["flags"] += 1
        b["prs"].add(pid)
        u = undone_file(pid, fnd.path)
        b["undone"] += u
        pr_any[(kind, pid)][0] = True
        pr_any[(kind, pid)][1] |= u
        b["survived_merged"] += (not u) and bool(pr[pid]["merged_at"])

n = len(files)
out = {
    "prs": n,
    "merged": sum(bool(pr[p]["merged_at"]) for p in files),
    "base_rate_line_undone": round(base_u / max(base_n, 1), 4),
    "base_lines": base_n,
    "base_rate_file_reverted": round(fbase_u / max(fbase_n, 1), 4),
    "base_files": fbase_n,
    "agents": dict(collections.Counter(pr[p]["agent"] for p in files)),
    "rules": {
        r: {
            "flags": b["flags"],
            "prs_flagged": len(b["prs"]),
            "undone": b["undone"],
            "undone_rate": round(b["undone"] / max(b["flags"], 1), 4),
            "undone_ci95": wilson(b["undone"], b["flags"]),
            "prs_with_undone_flag": sum(v[1] for (rr, _), v in pr_any.items() if rr == r),
            "prs_all_flags_survived_merged": (fa := sum(
                1 for (rr, p), v in pr_any.items() if rr == r and not v[1] and pr[p]["merged_at"]
            )),
            "false_alarm_prs_per_100_prs": round(100 * fa / max(n, 1), 2),
            "flags_per_100_prs": round(100 * b["flags"] / max(n, 1), 2),
            "surviving_flags_on_merged_per_100_prs": round(100 * b["survived_merged"] / max(n, 1), 2),
        }
        for r, b in sorted(by.items())
    },
}
Path(a.out).write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
