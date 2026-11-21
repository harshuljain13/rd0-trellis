"""Draw the paper's figures from research/results/*.json (no hand-typed numbers).

    python research/paper/scripts/make_figs.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  -- backend must be chosen before pyplot loads

H = Path(__file__).resolve().parent
RES = H.parent.parent / "results"
OUT = H.parent / "figures"
OUT.mkdir(exist_ok=True)
S = json.loads((RES / "scan_v1.json").read_text())
L = json.loads((RES / "llm_v1.json").read_text())
A = json.loads((RES / "audit_v1.json").read_text())
KILL_UNDONE, KILL_FA = 5.0, 3.0
GREY, BLUE, ORANGE, TEAL, RED, INK = "#8C8C8C", "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#1F2430"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7, "axes.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 300})
NAMES = {
    "scope:new-doc": "New doc", "bare-suppression": "Bare suppression", "workaround-comment": "Workaround comment",
    "commented-out-code": "Commented-out code", "scope:lockfile": "Lockfile", "scope:gitignore": ".gitignore",
    "scope:ci": "CI config", "scope:unrelated": "Outside named paths",
}


# Label offsets in points, chosen so nearby labels do not overlap.
OFFSET = {"scope:ci": (-4, -9), "scope:lockfile": (4, -9), "bare-suppression": (-62, 4), "scope:new-doc": (5, -7),
          "scope:unrelated": (8, -2)}


def ok(r):
    return 100 * r["undone_rate"] >= KILL_UNDONE and r["false_alarm_prs_per_100_prs"] <= KILL_FA


# Figure 2: every check against the pre-set bar.
fig, ax = plt.subplots(figsize=(3.4, 2.4))
ax.axvspan(KILL_UNDONE, 20, ymax=KILL_FA / 18, color=TEAL, alpha=0.12, lw=0)
ax.text(19.6, 0.4, "pass region", ha="right", va="bottom", color=TEAL, fontsize=6.5)
ax.axvline(100 * S["base_rate_line_undone"], color=GREY, ls="--", lw=0.6)
ax.text(100 * S["base_rate_line_undone"] + 0.2, 11.5, "line\nbaseline", color=GREY, fontsize=6)
ax.axvline(100 * S["base_rate_file_reverted"], color=GREY, ls=":", lw=0.6)
ax.text(100 * S["base_rate_file_reverted"] + 0.2, 11.5, "file\nbaseline", color=GREY, fontsize=6)
for k, r in S["rules"].items():
    x, y = 100 * r["undone_rate"], r["false_alarm_prs_per_100_prs"]
    lo, hi = (100 * v for v in r["undone_ci95"])
    c = BLUE if ok(r) else ORANGE
    ax.errorbar(x, y, xerr=[[x - lo], [hi - x]], fmt="none", ecolor=c, elinewidth=0.6, capsize=1.5)
    ax.scatter(x, y, s=12 + 0.4 * min(r["flags_per_100_prs"], 300), color=c, alpha=0.8, edgecolor=INK, lw=0.4, zorder=3)
    ax.annotate(NAMES.get(k, k), (x, y), xytext=OFFSET.get(k, (4, 3)), textcoords="offset points", fontsize=6, color=INK)
ax.set_xlim(0, 20)
ax.set_ylim(0, 18)
ax.set_xlabel("Flags undone in the same PR (%)")
ax.set_ylabel("False-alarm PRs per 100 PRs")
fig.tight_layout()
fig.savefig(OUT / "fig_checks.pdf")

# Figure 3: Trellis vs. Claude Haiku on the same PRs.
G = [("trellis_passing_two", "Trellis\n(2 passing)", BLUE), ("trellis_all", "Trellis\n(all 8)", "#A7B8D8"),
     ("llm_trellis_classes", "Haiku\n(same 8)", ORANGE), ("llm_all", "Haiku\n(+ bugs)", RED)]
panels = [("PRs flagged (%)", lambda r: 100 * r["prs_flagged"] / L["prs"]),
          ("Flags undone (%)", lambda r: 100 * r["undone_rate"]),
          ("False-alarm PRs / 100", lambda r: r["false_alarm_prs_per_100_prs"])]
fig, axes = plt.subplots(1, 3, figsize=(7.0, 1.9))
for ax, (title, f) in zip(axes, panels):
    vals = [f(L["groups"][g]) for g, *_ in G]
    bars = ax.bar(range(len(G)), vals, color=[c for *_, c in G], edgecolor=INK, lw=0.4)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=6)
    if "undone" in title:
        ax.axhline(100 * L["base_rate_line_undone"], color=GREY, ls="--", lw=0.6)
        ax.text(3.45, 100 * L["base_rate_line_undone"], "line\nbaseline", ha="right", va="bottom", fontsize=5.5, color=GREY)
    ax.set_xticks(range(len(G)), [n for _, n, _ in G], fontsize=6)
    ax.set_title(title, fontsize=7)
    ax.margins(y=0.15)
fig.tight_layout()
fig.savefig(OUT / "fig_llm.pdf")

# Figure 4: audit funnel and the most common checkable rules nothing enforces.
fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.0, 1.9), gridspec_kw={"width_ratios": [1, 1.3]})
steps = [("Sampled repos", A["sampled"]), ("Readable", A["reachable"]),
         ("With an instruction file", A["with_instruction_files"]), ("With extractable rules", A["with_rules"]),
         ("With an unenforced,\ncheckable rule", A["repos_with_unenforced_checkable_rule"])]
a1.barh(range(len(steps))[::-1], [v for _, v in steps], color=[GREY, GREY, BLUE, BLUE, ORANGE], edgecolor=INK, lw=0.4)
for i, (_, v) in enumerate(steps):
    a1.text(v + 4, len(steps) - 1 - i, f"{v}", va="center", fontsize=6)
a1.set_yticks(range(len(steps))[::-1], [n for n, _ in steps], fontsize=6)
a1.set_xlim(0, A["sampled"] * 1.15)
a1.set_title("(a) Repositories", fontsize=7)
top = A["top_enforceable"][:8][::-1]
a2.barh(range(len(top)), [v for _, v in top], color=ORANGE, edgecolor=INK, lw=0.4)
a2.set_yticks(range(len(top)), [n.replace("`", "") for n, _ in top], fontsize=6)
for i, (_, v) in enumerate(top):
    a2.text(v + 0.4, i, str(v), va="center", fontsize=6)
a2.set_title("(b) Most common enforceable rules (count)", fontsize=7)
fig.tight_layout()
fig.savefig(OUT / "fig_audit.pdf")
print("wrote", sorted(p.name for p in OUT.glob("*.pdf")))
