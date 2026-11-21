"""Write generated/numbers.tex and generated/tab_scan.tex from research/results/*.json (no hand-typed numbers)."""

import json
from pathlib import Path

H = Path(__file__).resolve().parent
RES = H.parent.parent / "results"
OUT = H.parent / "generated"
OUT.mkdir(exist_ok=True)
S = json.loads((RES / "scan_v1.json").read_text())
A = json.loads((RES / "audit_v1.json").read_text()) if (RES / "audit_v1.json").exists() else None
N = S["prs"]
KILL_UNDONE, KILL_FA = 0.05, 3.0
NAMES = {
    "scope:new-doc": "New summary/notes document",
    "bare-suppression": "Suppression with no reason",
    "workaround-comment": "Workaround comment",
    "commented-out-code": "Commented-out code",
    "scope:lockfile": "Lockfile without manifest",
    "scope:gitignore": "\\texttt{.gitignore} change",
    "scope:ci": "CI config change",
    "scope:unrelated": "File outside named paths",
}


def fa(r):
    return 100 * r["prs_all_flags_survived_merged"] / N


def ok(r):
    return r["undone_rate"] >= KILL_UNDONE and fa(r) <= KILL_FA


def macro(name, val):
    return f"\\newcommand{{\\{name}}}{{{val}}}\n"


m = ""
m += macro("nPRs", f"{N:,}") + macro("nMerged", f"{S['merged']:,}")
m += macro("baseLine", f"{100 * S['base_rate_line_undone']:.1f}") + macro("baseFile", f"{100 * S['base_rate_file_reverted']:.1f}")
m += macro("nLines", f"{S['base_lines'] / 1e6:.1f}M") + macro("nFiles", f"{S['base_files']:,}")
m += macro("nPass", str(sum(ok(r) for r in S["rules"].values()))) + macro("nChecks", str(len(S["rules"])))
for k, r in S["rules"].items():
    tag = "".join(w.capitalize() for w in k.replace("scope:", "scope-").split("-"))
    m += macro(f"undone{tag}", f"{100 * r['undone_rate']:.1f}") + macro(f"fa{tag}", f"{fa(r):.1f}")
    m += macro(f"flags{tag}", f"{r['flags_per_100_prs']:.1f}")
if A:
    for k in ("sampled", "reachable", "with_instruction_files", "with_rules", "rules", "repos_with_unenforced_checkable_rule"):
        m += macro("a" + "".join(w.capitalize() for w in k.split("_")), f"{A[k]:,}")
    for s in ("enforced", "enforceable", "judgment"):
        v = A["status"].get(s, 0)
        m += macro("a" + s.capitalize(), f"{v:,}") + macro("a" + s.capitalize() + "Pct", f"{100 * v / max(A['rules'], 1):.1f}")
(OUT / "numbers.tex").write_text(m)

rows = sorted(S["rules"].items(), key=lambda kv: (not ok(kv[1]), fa(kv[1])))
t = "\\begin{tabular}{lrrrl}\\toprule\nCheck & Flags/100 & Undone \\% [95\\% CI] & FA/100 & \\\\\\midrule\n"
for k, r in rows:
    lo, hi = r["undone_ci95"]
    t += (f"{NAMES.get(k, k)} & {r['flags_per_100_prs']:.1f} & {100 * r['undone_rate']:.1f} "
          f"[{100 * lo:.1f}, {100 * hi:.1f}] & {fa(r):.1f} & {'pass' if ok(r) else 'fail'} \\\\\n")
t += "\\bottomrule\\end{tabular}\n"
(OUT / "tab_scan.tex").write_text(t)

L = json.loads((RES / "llm_v1.json").read_text()) if (RES / "llm_v1.json").exists() else None
if L:
    m += macro("lPRs", f"{L['prs']:,}") + macro("lMerged", f"{L['merged']:,}") + macro("lMaxChars", f"{L['max_chars']:,}")
    m += macro("lBase", f"{100 * L['base_rate_line_undone']:.1f}") + macro("lSec", f"{L['mean_seconds']:.1f}")
    m += macro("lTokIn", f"{L['tokens_in'] / 1e6:.2f}M") + macro("lTokOut", f"{L['tokens_out'] / 1e6:.2f}M")
    m += macro("lTokPerPR", f"{(L['tokens_in'] + L['tokens_out']) / L.get('calls', L['prs']) / 1e3:.1f}k")
    LG = [("trellis_passing_two", "TrTwo", "Trellis, the two passing checks"),
          ("trellis_all", "TrAll", "Trellis, all eight checks"),
          ("llm_trellis_classes", "LlmSame", "Haiku, the same eight classes"),
          ("llm_all", "LlmAll", "Haiku, all issues incl.\\ bugs")]
    t = "\\begin{tabular}{lrrrr}\\toprule\nReviewer & PRs flagged \\% & Flags/100 & Undone \\% & FA/100 \\\\\\midrule\n"
    for g, tag, name in LG:
        r = L["groups"][g]
        pct = 100 * r["prs_flagged"] / L["prs"]
        m += macro(f"l{tag}Pct", f"{pct:.0f}") + macro(f"l{tag}Flags", f"{r['flags_per_100_prs']:.1f}")
        m += macro(f"l{tag}Undone", f"{100 * r['undone_rate']:.1f}") + macro(f"l{tag}Fa", f"{r['false_alarm_prs_per_100_prs']:.1f}")
        m += macro(f"l{tag}N", f"{r['flags']:,}")
        t += (f"{name} & {pct:.0f} & {r['flags_per_100_prs']:.1f} & {100 * r['undone_rate']:.1f} "
              f"& {r['false_alarm_prs_per_100_prs']:.1f} \\\\\n")
    t += "\\bottomrule\\end{tabular}\n"
    (OUT / "tab_llm.tex").write_text(t)
(OUT / "numbers.tex").write_text(m)
print(m)
