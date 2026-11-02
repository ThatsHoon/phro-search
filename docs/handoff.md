# Handoff: phro-search improvement work

State on 2026-11-02, for the next session that continues this work.

## Ground rules from the owner

- Talk to the owner in Korean. Everything written into the repo (skill, references, agents, scripts, docs) is English.
- Instructions must be token efficient: each rule in exactly one place, no duplicates, no contradictions. SKILL.md is loaded every run, so keep it short.
- Root-cause fixes, no workarounds.
- Work on branch `claude/optimistic-volta-rio18v` and push only there. Never push to main. Open no PR unless the owner asks.
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
- `hooks/` holds the egress guard: `hooks.json`, `egress.sh`, `egress.py`.
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

## Open: needs the owner's machine, data or a live check

1. Item 16, trigger phrases: run a live routing pass with `dev/routing.py` (evals/routing/prompts.tsv), then adjust the SKILL.md description and when_to_use. Together they are capped at 1,536 characters.
2. The R1 eval runs: gold lists for round-0 recall (`dev/score_round0.py`), the planted verifier set (`dev/score_verifiers.py`, which decides R6's vote-rule switch), and the routing pass. The owner chose to run all evals headless on Windows.
3. R9: measure PDF modes on the owner's topics with `dev/pdf_modes.py` before merging. Merging the branch switches quoting to reading-order text.
4. R13: check the routes and terms of MTEB and of a measured board for current LLMs.
5. The pulse hf lane is kept or dropped by the owner's replay of the T3.5 topic, small multilingual models.
6. Live route checks:
   - chain.py topic and related.
   - The Hugging Face routes.
   - watch's OpenAlex source kind.
   - The Wayback route of fetch.py.
7. Check that the Agent tool accepts `subagent_type: phro-search:<name>`. SKILL.md falls back to `<name>`, else it stops.
8. R17: the hook on Windows without Git Bash, and `hooks/egress.sh` run in Git Bash.
9. Three reruns of the Korean report prompt after the PLAN line change.
10. The README allow rule and the Windows install package names, checked on a real install.
11. T5.3, the rating of 5 real requests (plan:643).

## Open: can be done without the owner

- Check `report.md`'s opening sentence that maps report roles to agent types against SKILL.md's agent rule. The audit flagged it as a possible repeat; it was kept because it maps roles. Cut it if it adds nothing.
- `intake.md` and `models.md` restate parts of SKILL.md intake step 5 (lettered options, recommended first, a "don't know" option). Decide whether intake.md, as the question template, should own that rule and SKILL.md only point at it.
- `pulse.md`'s plan field list repeats defaults stated earlier in the file. It was kept as the schema; trim it if tokens matter more.
- Before claiming any script behavior in the docs, run that script's `--help`.

## Working method that worked

- When fixing a finding, first write a test that fails on the old code. Check that by stashing the script, running the test, then restoring the script.
- Do not apply overlapping text moves mechanically. An earlier dedup pass moved paragraphs into the wrong files. After any move, grep both files and read the edited spot.
- Record each build round in structure-review.md section 7 so the record stays current.
