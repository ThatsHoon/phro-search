# models

Pick a model for a task under constraints from public leaderboards. `models.py` reads the boards, joins Hub facts, applies the hard filters and marks the Pareto front; `follow` saves the cards of the few models that matter and greps them for the must-have features. This session writes the brief, picks from the front and says what the pick trades away. A board number is a measurement on that board's test sets and hardware at one date: it never proves the model works on the user's data, so every pick ends with a check on that data. No subagents; the plugin neither downloads nor runs models.

## 1. Intake: the model questions

Ask the open ones in this order, with the intake question rules. Look up what the environment can tell (the repo's runtime, a device spec in the docs) instead of asking.

| Slot | Why it matters | Default when unknown |
|---|---|---|
| Task | picks the board and the table | from the request |
| Languages | speech boards measure only some languages | the user's language |
| Memory or device | the weight budget (`--max-gb`), at 16-bit or 4-bit | no budget; ask when the model runs on a device |
| Runtime or format | GGUF, ONNX, MLX, Core ML, OpenVINO, Transformers | any |
| License | permissive (Apache, MIT, BSD, CC-BY), open with terms, any | permissive for a product, any for research |
| Latency | streaming speech (TTFA), real-time factor (RTFx) | none |
| Must-have features | what `follow --need` must find in the card | only what the request names; `follow` still prints the task's features |
| Recency | `--since`; "latest" means the last 12 months | none |
| Hosted services | APIs without weights may join the front (`--off-hub`) | no |

Candidate briefs, example: "Which speech recognition model for German should run on a phone?"
- A (recommended: on-device is stated). models: Open ASR multilingual table, German column, weights at most 1 GB at 4-bit, permissive license. Done when: the front with sizes and licenses; streaming and timestamps confirmed, denied or not stated for the pick and 2 alternates.
- B. models: the same table with hosted services allowed, for the best accuracy with no device limit.
- C. report: on-device speech runtimes compared (whisper.cpp, sherpa-onnx, Core ML), with a decision table.

Example, compromised: "Find papers on small text classifiers" when the use is a classifier to ship: restate the object as a small model to fine-tune (models: no board ranks fine-tuned classifiers, so the Open SLM board for small decoders plus encoders by name), keep dig as the alternative.

## 2. Boards

| `--board` | Tables | Ranks by (direction) | Notes |
|---|---|---|---|
| `asr` (Open ASR) | `english` (default), `multilingual`, `longform`, `private` | Average WER (lower), RTFx (higher) | `--lang` picks a multilingual column: German, French, Italian, Spanish, Portuguese, Hindi, Dutch; no other language is measured; hosted services sit near the top |
| `tts` (Open TTS) | `quality` per `--lang`, `--clone` for voice cloning; `streaming` per `--hardware` (A100, CPU, H200) | Average WER (lower), Average RTFx, UTMOS (en), Average SIM with `--clone` (higher); TTFA p50 and p95 in ms (lower) | the language list is the Space's own; a wrong `--lang` prints it; quality averages the Seed-TTS, CV3-Eval and MiniMax sets |
| `llm` (Open LLM) | `main` | average_score, IFEval, BBH, MATH Level 5, GPQA, MUSR, MMLU-PRO (higher) | frozen since 2025-03-20: newer models are absent |
| `slm` (Open SLM) | `main` | Intelligence Index, hellaswag, arc, arcChall, piqa, arithmark3 (higher) | small LMs up to about 400M parameters; the index is computed as the page does |
| `arena` (LMArena) | `text` (default), `search` | rating (higher) | votes from people comparing answers, updated often; names are display names, so every row is off the Hub |
| `hub:<org>/<dataset>` | `main` | value (direction from the board) | a Hub benchmark's leaderboard: current models, mostly self-reported |

Hub benchmarks that rank general models (2026-10-30): `Idavidrein/gpqa`, `TIGER-Lab/MMLU-Pro`, `cais/hle`, `openai/gsm8k`, `MathArena/aime_2026`, `SWE-bench/SWE-bench_Verified`, `LiquidAI/ifstruct-v1.0`, `MMMU/MMMU_Pro`, `allenai/olmOCR-bench`, `mteb/BRIGHT`. The full list is https://huggingface.co/api/datasets?filter=benchmark:official.

Pick the board from the task: speech recognition `asr`, speech synthesis `tts` (`streaming` when latency matters), a small LM `slm`, a current LLM `arena` for how people rate its answers, or a `hub:` benchmark close to the use, with `llm` only for models before March 2025.

No board measures the task or the language (a classifier to fine-tune, a language the speech boards skip): say so in the one-line answer, keep the closest table as a proxy and name what it measures, and add up to 3 models the boards do not rank but the field uses for that task or language (encoders for classification, models whose cards list the language). `follow` takes any Hub repo; their card scores go in a self-reported column of their own.

## 3. Run

Plan line: "PLAN: models; <board> <table>, snapshot, shortlist, follow up to 5, about 3 minutes; ceiling 0 agent calls".

1. Snapshot: `models.py snapshot <topic_dir> --board asr --table multilingual`. Speech synthesis adds `--lang Korean --clone` or `--table streaming --hardware CPU`. One snapshot per board and day (`KEPT`); `--refresh` takes another. It prints `SNAPSHOT` (rows, rows linked off the Hub, the board's revision), `NEW` and `GONE` since the topic's last snapshot, then `OK`. `FAIL schema-drift` (exit 2) means the board changed shape: report it, never guess its columns, and use another board.
2. Shortlist: `models.py shortlist <topic_dir> --board asr --lang German --max-gb 1 --license permissive`, plus `--since YYYY-MM-DD`, `--metric <column>` (default the table's first metric), `--off-hub`, `--top N` (at most 15). The same `--lang`, `--clone`, `--hardware` and `--table` pick the snapshot. It looks up at most 40 models on the Hub, 1 s apart: give the call a 5-minute timeout. Filters on the board's own columns (size, license, date) act before any lookup.
3. Read the rows. `FRONT` or `MODEL`, the repo, the metric (and the board's speed), the label, params, the 16-bit size (stored size when params are unknown), the 4-bit estimate, license class and license, created, formats, notes. `OFFHUB` rows have no Hub repo: a hosted service, or a model the board does not link. `# dropped` counts what each filter removed. Notes to act on:
   - `fits at 4-bit`, `over budget by N%`: kept, with the budget caveat;
   - `params ... miss part of the weights`: the count covers some files only; the size shown is the largest file;
   - `board row: <name>`: the board ran a variant or runtime (`(audio.cpp)`, `(RL)`); name it in the table;
   - `gated`, `license unknown: read it`, `languages not stated`, `card says multilingual`;
   - `quantized: <formats>`: derivatives on the Hub, not measured by the board.
4. No model left is a valid answer: name the filter that removed the most and offer to relax that one.
5. Choose up to 5 to follow: the front first by the primary metric, then the next best that meet every hard constraint, and the models the boards do not rank (section 2) when no board measures the task or the language.
6. Follow: `models.py follow <topic_dir> <org/name> <org/name> --need "streaming,word timestamps"`. `--task asr|tts|llm` picks the feature list (default from the shortlist's board). It saves the card at the repo sha (`sources/hf-<org>--<name>-<sha7>.md`, never overwritten) and the facts with the config and the paper abstracts (`models/hub/<org>--<name>.json`). It prints `FACTS`, one `FEATURE` hit per task feature and up to 3 per need (`file:line: text`, or `not stated`), and `HOP` lines for each need still not stated. A gated repo serves its card only after its terms are accepted: `FACTS` says `card gated` and a `HOP <repo> card page <url>` line points at the model page, which shows the card.
7. Read each hit in context before calling a feature present: `grep -n -B2 -A2 -i "<term>" <topic_dir>/<file>`. A hit can deny the feature ("streaming is not supported") or mean something else; a denial is "no" with its location.
8. Hops, at most 2 per model and only for needs still not stated: the paper (`fetch.py <topic_dir>/sources arxiv-<id>-<short-title> https://arxiv.org/abs/<id>`), the repository README from the `HOP` line (`fetch.py <topic_dir>/sources <name> <repo url>`), and for a gated card the model page (`fetch.py <topic_dir>/sources hf-page-<org>--<name> <page url>`, the name lowercased with `_` as `-`), then grep them the same way. After that the feature is "not stated in card, config, paper or repo".
9. Stop when every model on the front that was followed has its metric, size, license and each must-have feature confirmed, denied or not stated after the hops.

## 4. Labels

These label a model row's values; they are not the source marks of `references/formats.md`.

- `measured`: a board's own score under its test sets and hardware.
- `verified`: a hub leaderboard value the Hub marks verified.
- `self-reported`: other hub leaderboard values, and everything from cards, papers and repositories: features, languages, scores.
- Measured and self-reported scores never share a column or a cell: a board's score or speed (WER, SIM, RTFx, TTFA) sits in a board column, with "not on the board" for a model it did not run, and a score from a card gets a self-reported column of its own. A feature column holds yes, no or not stated from cards, papers and repositories; the board's own mark for that feature (Streaming API, Voice cloning) may stand beside it, tagged "board". The Languages cell covers the requested languages only: "board" when the board measured them, "self-reported" when only the card lists them.
- Sizes are estimates from the parameter count: 16-bit is 2 bytes a parameter, 4-bit 0.55 bytes (scales and unquantized layers included). Downloads and likes are popularity, never quality.

## 5. Deliverable

`<topic_dir>/models-<date>.md`, in the user's language (headings and labels too):

```
# <task>: model choice, <date>
<one line: the pick and why>

| Model | <metric> (<board>, <date>) | Params | 16-bit | 4-bit | License | Languages | <need> | Created | Label |
|---|---|---|---|---|---|---|---|---|---|
| [org/name](https://huggingface.co/org/name) | 4.02 [1] | 0.63B [2] | 1.25 GB | 0.34 GB | permissive (cc-by-4.0) [2] | German: board | yes [3] | 2025-08-04 [2] | measured |

[1] sources/board-asr-multilingual-2026-10-30.tsv:5
[2] models/hub/org--name.json
[3] sources/hf-org--name-a1b2c3d.md:41

## <the pick: a heading that says why>
<what it wins on, what it trades away>

## <alternates>
<up to 2, each with when to choose it instead>

## <caveats>

## <check on your data>
<2 or 3 models, how many samples, which metric, what result would change the pick>
```

- Every number has a location: the snapshot line (`grep -n "<model>" <topic_dir>/sources/board-<...>.tsv`), the facts file, or the card line. Sizes point at the params they come from.
- One column per must-have feature, plus the board's speed when latency matters. Feature cells are yes, no or not stated, each with its location; "not stated" names where it was looked for.
- One row per model followed; a model the board ran in a variant gets the variant in its cell. The pick and the alternates are named by the repo id in their row: a port (`-hf`, a GGUF repo) is another repo with its own size.

Caveats, every one that applies:
- the board's own test sets and hardware (RTFx and TTFA on the board's GPU or the chosen hardware); the user's audio or text may differ;
- a frozen board and its date;
- languages the board does not measure: a card's language list is self-reported;
- self-reported scores from hub boards and cards;
- weights only: KV cache, activations and audio buffers come on top; 4-bit quality is not measured by the boards;
- gated models need their terms accepted; an unknown or custom license must be read; this is not legal advice.

## 6. Deliver

Check the file with `check.py --kind models <topic_dir>/models-<date>.md`. Then reply in the user's language, with no lead-in: the one-line answer, the table's top rows, the pick and alternates with when to choose each, the caveats, the check on their data, the file path and the feedback question. Log the run (board, snapshot, filters, models followed, hops, minutes).


## Hand-offs

- To report: when the choice turns on more than the boards (serving cost, a stack, a team's skills).
- To dig: the method lineage or the originals behind a model.
- To pulse: what users said about a model in the last N days.
- To docs: how to run the pick in a given runtime.

## Files

- `sources/board-<board>[-<table>][-<lang>[-clone] or -<hardware>]-<date>.tsv`, written by `models.py snapshot`: line 1 `# board= table= route= url= revision= fetched=` (plus `lang= clone=` or `hardware=`), line 2 the board's headers without decoration plus `link`, then one line per board row, its values verbatim (markup stripped, footnote marks kept). Later snapshots that day end in `-2` and on. A same-day snapshot cut short is no baseline: snapshot takes another under the next number, and shortlist never reads a cut one.
- `models/shortlist.json`: `{board, table, snapshot, metric, direction, filters, models}`; a model is `{repo, name, off_hub, link, scores, label, source, params, weight_gb, gb_16, gb_4bit, license, license_class, languages, languages_label, created, formats, gated, notes, front, dropped}`, and `quantized` on the front.
- `models/hub/<org>--<name>.json`: one repo's Hub facts, one key per line (`repo, url, sha, pipeline_tag, library, created, modified, gated, license, license_name, license_link, license_class, languages, base_model, arxiv, params, params_by_dtype, weight_gb, weight_source, largest_file_gb, formats, gguf, config, downloads, likes, card, config_file, files, fetched`); `follow` adds `papers` (`id, title, abstract, published, github`) and `quantized` (`count, formats, first`). A file fetched today is reused.
- `sources/hf-<org>--<name>-<sha7>.md`: a model card at that repo sha; a gated repo's card comes from its model page as `sources/hf-page-<org>--<name>.md`, saved by `fetch.py`. A card an earlier run left empty or cut short is fetched again; any other saved card is never overwritten.
- `models-<date>.md`: the deliverable (section 5).
