# Claims ledger

Every number in the paper comes from a file below. Numbers in the LaTeX come from `generated/numbers.tex`, built by `scripts/make_numbers.py`.

| Claim | Value | Source |
|---|---|---|
| Sampled multi-commit agent PRs / merged | 11,996 / 8,211 | `results/scan_v1.json` -> `prs`, `merged` |
| Baseline: distinct added code lines undone / changed files cancelled out | 10.8% / 3.2% | same -> `base_rate_line_undone`, `base_rate_file_reverted` |
| Per-check undone rate, 95% CI, flags/100 PRs | Table 1 | same -> `rules.*` |
| False alarms per 100 PRs | Table 1 | same -> `false_alarm_prs_per_100_prs` |
| Checks passing the pre-set bar | 2 of 8 | same, with 5% undone and 3 FA/100 |
| Audit: sampled / reachable / with instruction files / with rules | 300 / 295 / 135 / 134 | `results/audit_v1.json` |
| Audit: extracted rules, enforced / enforceable / judgment | 14,710; 0.1% / 1.4% / 98.4% | same -> `status` |
| Repos with an unenforced, checkable rule | 61 of 134 | same -> `repos_with_unenforced_checkable_rule` |
| Single-commit PRs are 40% of AIDev | 145,185 of 359,738 | `pr_commits.parquet`, PRs with one commit |
| Few substantive human review comments repeat in a repo | 2.6% | panel research review (not re-run here; see CHECKLIST.md) |
| LLM baseline: PRs / merged / max patch chars / line baseline | 862 / 612 / 14,000 / 11.3% | `results/llm_v1.json` -> `prs`, `merged`, `max_chars`, `base_rate_line_undone` |
| LLM vs Trellis: PRs flagged, flags/100, undone, FA/100 | Table 2 | same -> `groups.*` |
| Haiku tokens per PR and seconds per PR | 3.7k / 1.6 s | same -> `tokens_in`, `tokens_out`, `mean_seconds` |
| Figures 2-4 (workshop paper) | plotted values | `scripts/make_figs.py` reads `results/scan_v1.json`, `results/llm_v1.json`, `results/audit_v1.json` |
