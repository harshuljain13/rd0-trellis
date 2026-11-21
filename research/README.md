# Evaluation on AIDev

Data: [AIDev](https://huggingface.co/datasets/hao-li/AIDev) (`pull_request`, `pr_commits`, `pr_commit_details`,
`repository` parquet files, about 13.5 GB). Download them into one directory first.

| Script | Output | What it measures |
|---|---|---|
| `experiments/eval_v1/eval_scan.py` | `results/scan_v1.json` | `trellis scan` on every commit of 12,000 sampled agent PRs with 2 or more commits (seed 0). Line counts are summed over all of a PR's commits, per distinct line text per file. A line flag is *undone* when the PR removes that text from the file at least as often as it adds it. A file flag is *undone* when the PR's changes to the file cancel out. |
| `experiments/eval_v1/eval_llm.py` | `results/llm_v1.json` | Claude Haiku as an LLM reviewer vs `trellis scan` on the same PRs from the scan sample whose patches fit in 14,000 characters (862 PRs with a valid JSON reply out of 875 sent). Same scoring. Flags must quote a line the PR added. Responses are cached next to the output; `--budget` stops the run before the estimated spend exceeds it (default $9, priced conservatively at $2/$10 per million tokens). |
| `experiments/eval_v1/eval_audit.py` | `results/audit_v1.json` | `trellis audit` on randomly sampled non-fork AIDev repositories, read from the GitHub API. |

```bash
pip install -e "packages/rd0-trellis" pyarrow
python research/experiments/eval_v1/eval_scan.py ~/aidev research/results/scan_v1.json --sample 12000
ANTHROPIC_API_KEY=... python research/experiments/eval_v1/eval_llm.py ~/aidev research/results/llm_v1.json --n 1000 --budget 8.5
GITHUB_TOKEN=... python research/experiments/eval_v1/eval_audit.py ~/aidev research/results/audit_v1.json --sample 300
```

`eval_scan.py` peaks at about 12 GB of RAM on 12,000 PRs and takes about 12 minutes. 30,000 PRs needs more than 30 GB.

## Paper

Two drafts share `generated/` (numbers and tables from `scripts/make_numbers.py`) and `figures/` (plots from
`scripts/make_figs.py`, which needs matplotlib):

- `paper/workshop/main.tex`: 4-page workshop paper with RQ1-RQ3, the LLM-reviewer comparison and three figures.
- `paper/tooldemo/main.tex`: 2-page tool-demo version.

`make -C research/paper` rebuilds numbers, figures and both PDFs. `paper/CLAIMS.md` traces every number to a result file.

## Definitions

- **Baseline:** the share of distinct added code-line texts (per file per PR) that are undone by the same
  definition (`base_rate_line_undone`), and the share of changed files whose changes cancel out
  (`base_rate_file_reverted`).
- **False alarms per 100 PRs:** merged PRs where none of a check's flags were undone, per 100 sampled PRs
  (`false_alarm_prs_per_100_prs`). This is an upper bound: some surviving flags were real problems that the
  team accepted.
- **Kill rule, fixed before the run:** a built-in check stays on by default only if at least 5% of its flags are
  undone and it has at most 3 false alarms per 100 PRs.

## Threats to validity

- AIDev has no commit timestamps, so counts are summed over the PR's commits and order is ignored.
- Being undone is a proxy for being corrected. A line can also be rewritten during ordinary iteration, which is
  why each rate is compared with the baseline.
- PRs with one commit (40% of AIDev) cannot show a correction and are excluded.
- The LLM baseline is one model with one prompt, on smaller PRs only. Its cost is reported as tokens, not dollars.
