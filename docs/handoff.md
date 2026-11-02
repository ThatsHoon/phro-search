# Handoff: phro-search improvement work

State on 2026-11-02, for the next session that continues this work.

## Ground rules from the owner

- Talk to the owner in Korean. Everything written into the repo (skill, references, agents, scripts, docs) is English.
- Instructions must be token efficient: each rule in exactly one place, no duplicates, no contradictions. SKILL.md is loaded every run, so keep it short.
- Root-cause fixes, no workarounds.
- Work on a branch and push there. Main moves only when the owner says merge. Open no PR unless the owner asks.
- Commit as the owner, with a plain message and no AI attribution or trailers:
  `git -c user.name=thatshoon -c user.email=gagea45@gmail.com commit -m "<message>"`.
  A stop hook may ask to re-author commits as Claude. Do not, unless the owner says so.
- Never print secrets or credentials (OPENALEX_API_KEY, HF_TOKEN, GH_TOKEN).

## Where things are

- `docs/structure-review.md` is the review record and the main source of truth:
  - Findings F1 to F44.
  - Decisions R1 to R18, accepted details P1 to P18, backlog items 1 to 18.
  - Plan amendments, section 7 "Open items" with a status paragraph for each build round, and the appendices (platform facts).
- `docs/plans/2026-10-30-phro-search.md` is the original plan and acceptance log (cited as plan:<line>).
- `skills/search/SKILL.md` is the router: intake, routing to six modes (dig, report, pulse, docs, models, watch), and the rules for every mode.
- Mode rules live in `skills/search/references/<mode>.md`.
  - `briefs.md` holds the agent briefs shared by modes and `formats.md` the shared file formats.
  - `theory.md` says why the rules exist and points at them.
- `agents/` holds three agents, `web-gatherer`, `verifier` and `local-reader`. They are spawned as `phro-search:<name>`.
- `hooks/` holds the egress guard (`egress.sh`, `egress.py`) and the plan line check (`plan_line.sh`, `plan_line.py`).
- `scripts/` holds stdlib Python run as `python -I`: fetch, chain, report, watch, pulse, models, check.
- `dev/` holds maintainer tools: pdf_modes, agent_cost, routing, score_round0, score_verifiers, feedback_gold.
- `evals/` holds the routing prompts and the README on running the R1 evals.

## How to verify

- `python3 -m unittest discover -s tests -t .` runs the full suite (pytest is not installed). It must pass before every commit.
- Guards in `tests/test_plugin.py` that edits often trip:
  - Size caps: a reference under 200 lines, SKILL.md under 150.
  - English only where the model reads.
  - No dashes, emoji or invisible characters in .md, .py and .json files.
  - Every command and flag the docs name must appear in the scripts' --help.
  - Each mode's Plan line must be literal: `PLAN: <mode>; ...; ceiling <number> <...> calls`.
  - Copies of shared code must stay byte-identical across scripts:
    - `egress_terms`, `_edge`, `egress_hit` (from hooks/egress.py).
    - `clean`, `NAMES`, `OA_RANKS`, `oa_kind`, `oa_order`.

## Done

- Backlog items 1 to 18 are built on the branch, except the parts that need the owner (below).
- Two review passes of the build were applied, each fix with a test. The second pass is listed at the end of structure-review.md section 7. Its main changes:
  - Timeouts are retried once, with 20 s per request.
  - watch gives each feed a share of the deadline.
  - models' deadline is set per command.
  - egress reads both HOME and USERPROFILE.
  - full support needs a source that is not retracted.
  - report's support pass rates all located quotes and rates reworded claims again.
  - hf and the OpenAlex watch kind page back far enough.
  - routing and the verifier scoring were fixed.
  - dig rates quotes before the evidence page, counts the --since audit apart, and seeds in two steps.
- An audit of the instruction docs was applied:
  - Contradictions fixed: plan ceilings, question order, pulse supplements for any region, the timeout status, the topic path, and the exception for hand-offs between modes.
  - Duplicate rules cut.
  - Maintainer notes removed from the skill.
  - It found no broken pointers and no command or flag the scripts reject.

## Open: the owner decides

The numbers behind each are in structure-review.md section 7, round of 2026-11-02.

1. Routing is at 22/28 in scope against a threshold of 90 percent. Two misses went to imozuru and one to huggingface-best. T5.4 is committed in phro-gcp-mlflow but not pushed, because that repo is public and phro-search is still private. The owner moves both skills out of `~/.claude/skills` (a permission check stops the agent from doing it), then `dev/routing.py --installed --runs 3` gives the number to judge.
2. The R1 eval runs that need the owner's data: gold lists for round-0 recall (`dev/score_round0.py`) and the planted verifier set (`dev/score_verifiers.py`, which decides R6's vote-rule switch).
3. T5.3, the rating of 5 real requests (plan:643).

## Open: needs another machine

- R17: the hook on Windows without Git Bash. Without Git on PATH `sh` is not found, but Claude Code's behavior there is untested.
- R13: an MTEB per-task board needs a rule for the split and for averaging subsets, and only then a board.

## Rules for later work

- Before claiming any script behavior in the docs, run that script's `--help`.
- The README's `phro-search@phro` install line works only after T5.6.

## Working method that worked

- When fixing a finding, first write a test that fails on the old code. Check that by stashing the script, running the test, then restoring the script.
- Do not apply overlapping text moves mechanically. An earlier dedup pass moved paragraphs into the wrong files. After any move, grep both files and read the edited spot.
- Record each build round in structure-review.md section 7 so the record stays current.
