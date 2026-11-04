# Evals

Defaults change only on these numbers (R1 in `docs/structure-review.md`). The outcome sets and the routing set run headless with `claude -p` in your own environment, where your other skills are installed, not inside `claude plugin eval`, whose sandbox drops those skills and refuses Bash and Write grants on native Windows. Scripts grade them. Each eval pass has a cost cap of 50 USD.

Commands below use `python3`; on Windows run `python` from Git Bash.

| Folder or script | Set | Decides |
|---|---|---|
| `intake/` | intake cases for `claude plugin eval` (T5.3; commands in the top README) | the intake |
| `routing/prompts.tsv`, `dev/routing.py` | routing | trigger phrases (backlog item 16, R15) |
| `dev/score_round0.py` | round-0 recall | haiku searchers (R4), the citation list in round 0 (R8) |
| `dev/score_verifiers.py` | verifier set | the vote rule (R6) |

## Routing

`routing/prompts.tsv` has one prompt per line: `id`, `kind` (`in`, `near` or `out`), `expect` (the mode, or `none`), `lang`, `prompt`, `note`. The 28 in-scope and 6 out-of-scope prompts rebuild T5.1's set (two are verbatim, the rest reconstructed from its topics); the 12 near misses come from R1 and P9: "보고서로 정리해줘" about a document in hand, a scikit-learn "best model for", "새 글 확인" about Slack, and complaints from a coding session.

```bash
python3 -I dev/routing.py --dry-run
python3 -I dev/routing.py
python3 -I dev/routing.py --kind near --runs 3
python3 -I dev/routing.py --from evals/routing/runs/<stamp>
```

Each prompt runs 3 times (`--runs`) with the plugin loaded from this repo (`--installed` tests the installed one instead), read-only tools and no web, in a fresh empty folder, with the prompt on standard input. Every stream is saved under `evals/routing/runs/<stamp>/` (ignored by git), and `--from` grades a saved folder again. The script reads from the stream whether phro-search fired and which mode reference it read first, and prints one `RUN` line per run, one `PROMPT` line per prompt and the totals. It passes at 90 percent or more firing on in-scope prompts and 10 percent or less on near misses and out-of-scope prompts. T5.1 cost 0.18 to 0.74 USD a run, so the full set (138 runs) can reach the cap: `--cap` (default 50) starts no run past it, and `--budget` caps each run (default 1 USD). Check `search?` runs by hand: the skill fired but read no mode reference and wrote no plan line. `--model`, `--tools`, `--timeout`, `--cwd`, `--out` and `--skill` adjust the runs.

Item 16 adds a trigger phrase only when it raises in-scope firing here and the near misses stay quiet.

## Round-0 recall

1. Mark the canonical works of 2 or 3 closed topics in a gold file, one work per line: a DOI (best), an OpenAlex W id or a title, with tab-separated alternatives for the same work.
2. Run round 0 only, in a scratch topic root, 3 times per arm: haiku against sonnet searchers (R4), and two web searchers against one web searcher plus the `chain.py topic` list (R8).
3. Score each arm's folders together:

```bash
python3 -I dev/score_round0.py gold.txt runs/a1/flood-mapping runs/a2/flood-mapping runs/a3/flood-mapping
python3 -I dev/score_round0.py gold.txt runs/a1/flood-mapping --found "round 0"
```

`RECALL` is the share of gold works in the map's Sources table or `sources/index.tsv`, and `RECALL-BY` splits it by the Found in column, which shows each method's share and the overlap. `ARCHIVED` is the share of the map's Original URLs that `fetch.py` archived as the original itself (not a Wayback copy of a dead page, a wall or a summary); `--found` keeps only rows whose Found in cell contains the text. `MEAN` averages the repeats. Haiku replaces sonnet when its recall is at least 95 percent of sonnet's and its archived share is no more than 5 points lower; the pair replaces two web searchers when its recall is at least theirs.

## Verifier set

Make 20 to 30 planted claims from T2.4's `claims.json` (overstated, outdated, contradicted and true variants), let 3 verifiers vote on each, and list the truth in a planted file, one claim per line: `<claim id> <true|false> [<variant>]`. A default run sends one verifier first on a reviewed source, so the FALSE line's "votes not refuting" reads as the chance that it lets a false claim pass.

```bash
python3 -I dev/score_verifiers.py planted.tsv research/<topic>/claims.json
```

It prints each claim with its votes and verdict, the false refutations of true claims and the false survivals of false claims (by vote and by verdict), and an `R6` line: above 10 percent of true claims with a verdict ending refuted, the vote rule switches to "refuted needs a stated reason from the check list; could not check is no vote".

## New gold items

`dev/feedback_gold.py ~/research` lists what users said a delivered result missed; add the items that hold up to the gold file or the planted claims by hand.
