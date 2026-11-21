"""LLM-reviewer baseline: ask Claude Haiku to flag the same issue classes as `trellis scan`, score both the same way.

Same sample as eval_scan.py (seed 0), restricted to PRs whose combined commit patches fit in --max-chars so the
model and Trellis see identical, untruncated input. A line flag counts only if its text was actually added to that
file in the PR; it is *undone* by the same PR-wide net-count rule as eval_scan.py. File-level flags are undone when
the PR's commits cancel out on that file. A false alarm is a merged PR where none of that reviewer's flags were undone.
Responses are cached in <out>.cache.jsonl; the run stops before spending more than --budget dollars.

Usage: python eval_llm.py <AIDev dir> <out.json> [--n 1000] [--budget 9] [--model claude-haiku-5-5]
"""

import argparse
import collections
import concurrent.futures as cf
import json
import os
import random
import re
import threading
import time
from pathlib import Path

import anthropic
import pyarrow.parquet as pq
from rd0_trellis import paths as P
from rd0_trellis.config import Config
from rd0_trellis.diff import FileDiff, from_github_files
from rd0_trellis.rules import line_rules, scope_findings

ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("out")
ap.add_argument("--n", type=int, default=1000)
ap.add_argument("--pool", type=int, default=12000)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--max-chars", type=int, default=14000)
ap.add_argument("--budget", type=float, default=9.0)
ap.add_argument("--model", default="claude-haiku-5-5")
# Conservative per-token prices used only for the spending guard; actual token counts are reported.
ap.add_argument("--price-in", type=float, default=2.0)
ap.add_argument("--price-out", type=float, default=10.0)
ap.add_argument("--workers", type=int, default=6)
a = ap.parse_args()
D = Path(a.data)
cfg = Config()
RULES = line_rules(cfg)

commits = collections.Counter(pq.read_table(D / "pr_commits.parquet", columns=["pr_id"]).column("pr_id").to_pylist())
pool = sorted(str(p) for p, n in commits.items() if n >= 2)
random.Random(a.seed).shuffle(pool)
cand = pool[: a.pool]
random.Random(a.seed + 1).shuffle(cand)
cand = cand[: a.n * 4]
need = set(cand)
pr = {}
for row in pq.read_table(D / "pull_request.parquet", columns=["id", "title", "body", "merged_at"]).to_pylist():
    if str(row["id"]) in need:
        pr[str(row["id"])] = row

meta = {"model": a.model, "seed": a.seed, "pool": a.pool, "n": a.n, "max_chars": a.max_chars}
meta_path = Path(a.out + ".meta.json")
if meta_path.exists() and json.loads(meta_path.read_text()) != meta:
    raise SystemExit(f"{meta_path} was made with other settings; use another output path")
meta_path.write_text(json.dumps(meta))
recs_path = Path(a.out + ".recs.json")
if recs_path.exists():
    recs = json.loads(recs_path.read_text())
    chosen = list(recs)
else:
    recs = collections.defaultdict(list)
    size = collections.Counter()
    pf = pq.ParquetFile(D / "pr_commit_details.parquet")
    cols = [c for c in ("pr_id", "sha", "filename", "status", "patch", "previous_filename") if c in pf.schema_arrow.names]
    t0 = time.time()
    for g in range(pf.num_row_groups):
        for r in pf.read_row_group(g, columns=cols).to_pylist():
            pid = str(r["pr_id"])
            if pid in pr and r.get("filename") and size[pid] <= a.max_chars:
                recs[pid].append(r)
                size[pid] += len(r.get("patch") or "") + len(r["filename"]) + 20
        if g % 40 == 0:
            print("scan", g, pf.num_row_groups, round(time.time() - t0), flush=True)
    chosen = [p for p in cand if p in recs and size[p] <= a.max_chars][: a.n]
    recs = {p: recs[p] for p in chosen}
    recs_path.write_text(json.dumps(recs))
print("chosen", len(chosen), flush=True)

added = collections.defaultdict(collections.Counter)
removed = collections.defaultdict(collections.Counter)
files = collections.defaultdict(dict)
trellis_flags = set()  # (pid, path, rule, line-text or None)
for pid in chosen:
    for r in recs[pid]:
        fds = from_github_files([r])
        if not fds:
            continue
        f = fds[0]
        files[pid].setdefault(f.path, f.status)
        for _, ln in f.added:
            added[(pid, f.path)][ln.strip()] += 1
        for _, ln in f.removed:
            removed[(pid, f.path)][ln.strip()] += 1
        if f.status == "deleted" or P.is_skipped(f.path, cfg.ignore):
            continue
        text = dict(f.added)
        for rule in RULES:
            if rule.applies(f.path):
                for no, *_ in rule.hits(f.path, f.added):
                    trellis_flags.add((pid, f.path, rule.id, text.get(no, "").strip()))
    fds = [FileDiff(path=p, status=s) for p, s in files[pid].items()]
    for fnd in scope_findings(fds, f'{pr[pid]["title"] or ""}\n{pr[pid]["body"] or ""}', cfg):
        m = fnd.message
        kind = "scope:" + ("lockfile" if "lockfile" in m.lower() else "gitignore" if "gitignore" in m
                           else "ci" if "CI configuration" in m else "new-doc" if "new document" in m
                           else "unrelated" if "outside the area" in m else "other")
        trellis_flags.add((pid, fnd.path, kind, None))

CATS = {
    "workaround-comment": "a comment that excuses a hack or workaround (e.g. 'temporary fix', 'HACK') instead of fixing it",
    "bare-suppression": "a lint/type suppression (eslint-disable, # noqa, # type: ignore, @ts-ignore...) with no reason",
    "commented-out-code": "code left commented out",
    "scope:new-doc": "a new summary/notes/report document nobody asked for",
    "scope:lockfile": "a lockfile changed without a matching manifest change",
    "scope:gitignore": "an unexplained .gitignore change",
    "scope:ci": "an unexplained CI configuration change",
    "scope:unrelated": "a file change unrelated to what the PR title/description says it does",
    "bug": "any other real defect a reviewer should ask to change (logic error, broken code, security issue)",
}
SYSTEM = (
    "You review pull requests written by coding agents. Report only problems a careful human reviewer would ask the "
    "author to fix. Categories:\n" + "\n".join(f"- {k}: {v}" for k, v in CATS.items()) +
    "\nReply with JSON only: {\"issues\": [{\"category\": ..., \"path\": ..., \"line\": <exact text of one added "
    "line, without the leading +, or null for a whole-file issue>, \"why\": <under 15 words>}]}. "
    "Return {\"issues\": []} if the PR is fine."
)


def prompt(pid):
    p = pr[pid]
    parts = [f"Title: {p['title'] or ''}\nDescription:\n{(p['body'] or '')[:2000]}\n\nCommits' patches:"]
    for r in recs[pid]:
        parts.append(f"--- {r['filename']} ({r.get('status')})\n{r.get('patch') or ''}")
    return "\n".join(parts)


cache_path = Path(a.out + ".cache.jsonl")
cache = {}
if cache_path.exists():
    for ln in cache_path.read_text().splitlines():
        d = json.loads(ln)
        cache[d["pid"]] = d
lock = threading.Lock()
spent = [sum(d["in"] * a.price_in + d["out"] * a.price_out for d in cache.values()) / 1e6]
client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": os.environ["ANTHROPIC_WORKSPACE_ID"]}
                             if os.environ.get("ANTHROPIC_WORKSPACE_ID") else None)


def call(pid):
    text = prompt(pid)
    reserve = (len(text) / 2 * a.price_in + 1000 * a.price_out) / 1e6  # worst case, held until the reply arrives
    with lock:
        if spent[0] + reserve > a.budget:
            return None
        spent[0] += reserve
    for attempt in range(5):
        try:
            t = time.time()
            m = client.messages.create(model=a.model, max_tokens=1000, system=SYSTEM, thinking={"type": "disabled"},
                                       messages=[{"role": "user", "content": text}])
            break
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError):
            time.sleep(5 * 2**attempt)
    else:
        with lock:
            spent[0] -= reserve
        return None
    txt = "".join(b.text for b in m.content if b.type == "text")
    d = {"pid": pid, "in": m.usage.input_tokens, "out": m.usage.output_tokens, "sec": round(time.time() - t, 2),
         "raw": txt}
    with lock:
        spent[0] += (d["in"] * a.price_in + d["out"] * a.price_out) / 1e6 - reserve
        cache[pid] = d
        with cache_path.open("a") as fh:
            fh.write(json.dumps(d) + "\n")
    return d


todo = [p for p in chosen if p not in cache]
with cf.ThreadPoolExecutor(a.workers) as ex:
    for i, _ in enumerate(ex.map(call, todo)):
        if i % 50 == 0:
            print("llm", i, len(todo), round(spent[0], 3), flush=True)
done = [p for p in chosen if p in cache]


def parse(raw):
    """Issues list, or None when the reply is not a valid {"issues": [...]} object."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        issues = json.loads(m.group(0)).get("issues") if m else None
    except (json.JSONDecodeError, AttributeError):
        return None
    return issues if isinstance(issues, list) else None


parsed = {p: parse(cache[p]["raw"]) for p in done}
bad_json = sum(v is None for v in parsed.values())
called = list(done)  # billed, including replies dropped below
done = [p for p in done if parsed[p] is not None]  # a failed review is not a clean review
llm_flags, unmatched = set(), 0
for pid in done:
    for it in parsed[pid]:
        if not isinstance(it, dict):
            continue
        cat, path, line = it.get("category"), it.get("path"), it.get("line")
        cat = cat if cat in CATS else "bug"
        if path not in files[pid]:
            unmatched += 1
            continue
        if line:
            line = str(line).strip()
            if not added[(pid, path)][line] and line.startswith("+") and added[(pid, path)][line[1:].strip()]:
                line = line[1:].strip()  # model kept the diff marker
            if not added[(pid, path)][line]:
                unmatched += 1
                continue
        llm_flags.add((pid, path, cat, line or None))


def undone(pid, path, line):
    ad, rm = added[(pid, path)], removed[(pid, path)]
    if line is None:
        return bool(ad or rm) and ad == rm
    return rm[line] >= ad[line] > 0


def score(flags, prs):
    n = len(prs)
    by = collections.defaultdict(lambda: {"flags": 0, "undone": 0})
    per_pr = collections.defaultdict(lambda: [False, False])
    by["ALL"]  # always report the total, even with no flags
    for pid, path, cat, line in flags:
        if pid not in prs:
            continue
        u = undone(pid, path, line)
        for k in (cat, "ALL"):
            by[k]["flags"] += 1
            by[k]["undone"] += u
            per_pr[(k, pid)][0] = True
            per_pr[(k, pid)][1] |= u
    out = {}
    for k, b in sorted(by.items()):
        fa = sum(1 for (kk, p), v in per_pr.items() if kk == k and not v[1] and pr[p]["merged_at"])
        out[k] = {"flags": b["flags"], "undone": b["undone"], "undone_rate": round(b["undone"] / max(b["flags"], 1), 4),
                  "prs_flagged": sum(1 for (kk, _), v in per_pr.items() if kk == k),
                  "flags_per_100_prs": round(100 * b["flags"] / max(n, 1), 2),
                  "false_alarm_prs_per_100_prs": round(100 * fa / max(n, 1), 2)}
    return out


prs = set(done)
tin, tout = sum(cache[p]["in"] for p in called), sum(cache[p]["out"] for p in called)
base = [undone(p, path, ln) for (p, path), ad in added.items() if p in prs and P.is_code(path) and not P.is_skipped(path, cfg.ignore) for ln in ad]
res = {
    "model": a.model, "prs": len(done), "merged": sum(bool(pr[p]["merged_at"]) for p in done),
    "max_chars": a.max_chars, "base_rate_line_undone": round(sum(base) / max(len(base), 1), 4),
    "tokens_in": tin, "tokens_out": tout, "calls": len(called),
    "mean_seconds": round(sum(cache[p]["sec"] for p in called) / max(len(called), 1), 2),
    "guard_cost_usd": round((tin * a.price_in + tout * a.price_out) / 1e6, 3),
    "guard_prices_per_mtok": [a.price_in, a.price_out], "llm_unmatched_flags": unmatched, "llm_no_json": bad_json,
    "trellis": score(trellis_flags, prs), "llm": score(llm_flags, prs),
}
TRELLIS_CATS = [c for c in CATS if c != "bug"]
GROUPS = {
    "trellis_all": (trellis_flags, TRELLIS_CATS),
    "trellis_passing_two": (trellis_flags, ["scope:new-doc", "bare-suppression"]),
    "trellis_without_unrelated": (trellis_flags, [c for c in TRELLIS_CATS if c != "scope:unrelated"]),
    "llm_all": (llm_flags, list(CATS)),
    "llm_trellis_classes": (llm_flags, TRELLIS_CATS),
    "llm_bug_only": (llm_flags, ["bug"]),
}
res["groups"] = {g: score({f for f in fl if f[2] in cs}, prs).get("ALL", {}) for g, (fl, cs) in GROUPS.items()}
Path(a.out).write_text(json.dumps(res, indent=2))
print(json.dumps({k: v for k, v in res.items() if k not in ("trellis", "llm")}, indent=2))
print("budget note: --budget 0 rescoring reuses the cache and makes no API calls")
for who in ("trellis", "llm"):
    for k, v in res[who].items():
        print(who, k, v)
