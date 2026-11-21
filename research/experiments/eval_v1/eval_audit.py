"""Run `trellis audit` on a random sample of AIDev repositories and count how many agent-instruction rules
are already enforced, could be enforced by a tool, or are judgment calls.

Usage: GITHUB_TOKEN=... python eval_audit.py <AIDev dir> <out.json> [--sample N] [--seed S]
"""

import argparse
import collections
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow.parquet as pq
from rd0_trellis.audit import audit
from rd0_trellis.github import GitHub

ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("out")
ap.add_argument("--sample", type=int, default=800)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()

repos = pq.read_table(Path(a.data) / "repository.parquet", columns=["full_name", "is_forked", "stars"]).to_pylist()
names = sorted(r["full_name"] for r in repos if not r["is_forked"])
random.Random(a.seed).shuffle(names)
names = names[: a.sample]
BUDGET = 300  # API calls per repo; giant monorepos with hundreds of package configs are skipped


class Budgeted(GitHub):
    """One client per repo: audit sets `gh.repo`, so a shared client would race across threads."""

    n = 0

    def _req(self, *args, **kw):
        self.n += 1
        if self.n > BUDGET:
            raise RuntimeError("call budget")
        return super()._req(*args, **kw)


done = [0]


def one(name):
    done[0] += 1
    if done[0] % 50 == 0:
        print(done[0], flush=True)
    try:
        rep = audit(name, gh=Budgeted())
    except Exception as e:  # deleted, private or empty repos
        return {"repo": name, "error": str(e) if isinstance(e, RuntimeError) else type(e).__name__}
    return {
        "repo": name,
        "files": rep.files,
        "langs": rep.langs,
        "items": [{"status": i.status, "tool": i.tool, "title": i.title} for i in rep.items],
    }


with ThreadPoolExecutor(4) as ex:
    rows = list(ex.map(one, names))

ok = [r for r in rows if "error" not in r]
withf = [r for r in ok if r["files"]]
with_rules = [r for r in withf if r["items"]]
status = collections.Counter(i["status"] for r in with_rules for i in r["items"])
tools = collections.Counter(i["tool"] for r in with_rules for i in r["items"] if i["status"] != "judgment")
titles = collections.Counter(i["title"] for r in with_rules for i in r["items"] if i["status"] == "enforceable")
kinds = collections.Counter(f.split("/")[-1] if "/" not in f.rstrip("/") else f for r in withf for f in r["files"])
per_repo = [
    {s: sum(i["status"] == s for i in r["items"]) for s in ("enforced", "enforceable", "judgment")} for r in with_rules
]
med = sorted(x["enforceable"] for x in per_repo)
out = {
    "sampled": len(names),
    "reachable": len(ok),
    "with_instruction_files": len(withf),
    "with_rules": len(with_rules),
    "rules": sum(status.values()),
    "status": dict(status),
    "repos_with_unenforced_checkable_rule": sum(x["enforceable"] > 0 for x in per_repo),
    "median_enforceable_per_repo": med[len(med) // 2] if med else 0,
    "tools": dict(tools.most_common()),
    "top_enforceable": titles.most_common(25),
    "instruction_files": kinds.most_common(15),
}
Path(a.out).write_text(json.dumps(out, indent=2))
Path(a.out).with_suffix(".rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
print(json.dumps(out, indent=2))
