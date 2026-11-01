# Formats

Working files are English. Claim text, translations and deliverables are in the user's language; quotes stay verbatim in their own language.

## map.md

```
# map: <topic>

## Brief
<the brief, references/intake.md section 7>

## Terms
- <term> (<the user's words for it>): <URL or sources/ file> (unverified)

## People
- <name> (<affiliation>): <main work> (unverified)

## Venues
- <conference, journal, list, tag, repository, channel>: <URL>

## Sources
| Label | Work | Files | Original URL | Found in |
|---|---|---|---|---|
| paper | Bates 1989, berrypicking | bates-1989-berrypicking.pdf, .txt | <URL> | round 1, backward |

## Next leads
- <lead not yet followed>: <why it has a strong scent>
```

- Section order is fixed; appends go to the end of each section, so the rounds do not scatter the table.
- One table row per work; its files (PDF and text, an abstract page) share the row.
- A line taken from a searcher's report and not yet read in the original ends in (unverified); drop the mark once checked.
- Required claim lines carry a location and a short quote only: `- [x] C2 <claim>: sources/<file>:<line> "<short quote>"`; a partly sourced claim is `- [~]`.
- Older topics may use other heading words in the same order. Append under the matching heading; never rename or rewrite them.

## Labels and marks

One label per source, no scores; the reader decides what to trust by reading the original.
- `paper`: peer reviewed or conference papers, and arXiv preprints.
- `first-hand`: the record of the person who did the thing (tried, built or measured it): a post, a video, a README. A primary source even when personal.
- `observed`: someone describing other people's work or methods. Add the observed people to Next leads; their own records are the primary source.
- `summary`: collected or restated knowledge (explainers, roundups, encyclopedias, glossaries). Good for finding what to follow backward; back claims with `first-hand` or `paper` sources where possible.
- `official`: documents and announcements by the maker of a tool or product.

Marks after the label, when known: `retracted` (OpenAlex marks the work retracted: it never backs a required or central claim), `preprint` (a submitted version, such as fetch.py's submitted-copy: quote the published version when one exists), `landing-page` (fetch.py took the copy from a landing page: check that it holds the full text, not only a record), `unchecked` (fetch.py could not ask OpenAlex, so neither copies nor a retraction were checked), `examples` (the writer's own work is shown; read these first when the user wants how skilled people do it), `measured` (the writer's own measurements or comparisons), `self-reported` (a score or feature stated by its own authors), `ai-assisted` (the writer says an AI wrote it), `promo` (leads to something the writer sells), `unread` (downloaded, read by nobody yet), `auto-captions` (automatic captions: frequent errors, quote only what is legible, have the user check the video), `unverified` (from a search report, not read in the original).

## File names and locations

- `<author>-<year>-<short-title>` in lowercase ASCII with hyphens; arXiv papers `arxiv-<id>-<short-title>`.
- A PDF gives `<name>.pdf`, `<name>.txt` (its text in reading order: grep and quote this) and `<name>.layout.txt` (page layout, table rows kept); an OCR'd PDF gives no layout copy; an arXiv paper read from its HTML version gives `<name>.md`.
- A location is `sources/<file>:<line>`; video captions are located by time, `sources/<file>.md [12:34]`.

## log.md

Append only; re-read only the last round.

```
# log: <topic>

## <YYYY-MM-DD> intake
brief: mode=<mode>; object=<...>; deliverable=<...>; scope=<...>; evidence=<...>; budget=<...>
intake: level=<formalized|conscious|compromised|visceral>; rounds=<n>; questions=<n>; candidates=<n>; picked=<A|B|C|edited|none>; defaulted=<slots or none>; gate=<yes|no>
- answers, verbatim: <...>

## <YYYY-MM-DD> round <n>
- pending: <agents spawned and not yet reported or stopped>
- spawned: <agent> (<model>, <effort>): <method, what it was asked>: <returned | stopped>
- came back: <terms, people, venues, sources>; already known: <k> of <n>
- fetched: <name> OK | <name> FAIL <reason> <URL>
- decisions: <what and why>
- next leads: <2 to 4 leads for the next round>

## <YYYY-MM-DD> stop
stop: <dig: claims sourced | saturation k of n | 4 rounds | wall | budget; report: answered | budget>
stopped agents: <none | which>
intake-end: rescopes=<n>; drift=<claims added, dropped, reworded>
feedback: "<the user's answer, verbatim>"
```

The `brief:` and `feedback:` lines start at column 0 so that later intakes can grep them. Report mode writes `research`, `archive`, `verify` and `write` sections in the round's shape (spawned, came back, fetched, decisions); `verify` adds `votes: <n> central claims; <s> survived, <r> refuted, <u> unverified; <m> missing votes`. Pulse mode writes one `pulse` section: `- run: pulse/<stem>.json; lanes: <lane> <status>, ...; clusters: <n> over the floor, <m> weak; supplements: <queries>; brief: pulse/<stem>.md`.

## sources/index.tsv

Written by `fetch.py`, one row per fetched source, never edited by hand: a header line, then `name`, `url` (as asked: a URL, `https://doi.org/<doi>` or `local:<file name>`), `final` (the URL read), `fetched` (UTC), `published` and `modified` (as the page or the PDF states them, `-` when it does not), `extraction` (pdftotext, ocr, html, arxiv-html, text or captions), `version` (published, accepted or submitted for an open-access copy, `arXiv vN`, `arXiv` when the URL names no version, or `-`), `marks` and `files`, tab-separated. A PDF's published and modified dates are the file's own creation and change dates. A reused source adds no row, and a name fetched again gets a new row that replaces the older one. The evidence page shows each quote's dates and a retracted mark from it.

## extracts.json

```
{"title": "...", "question": "...", "stopped": "<stop reason>",
 "claims": [{"claim": "...", "status": "sourced", "note": "...",
             "quotes": [{"file": "<file in sources/>", "line": 12, "end": 14, "text": "<verbatim>", "translation": "...", "mark": "...",
                         "support": "full", "qualifier": {"file": "...", "line": 30, "text": "<verbatim>"}}]}],
 "disagreements": [{"topic": "...", "quotes": [{"file": "...", "line": 3, "text": "...", "who": "..."}]}],
 "unreached": ["<item>: <why>, <URL>"]}
```

- `status` is `sourced`, `partial` or `none`. One claim per required claim, in the user's language. `note` is one flat line on who did what: no conclusions, no ratings.
- `support` is the support reader's rating of the quote (full, partial, none or contradicts); a `sourced` claim needs a full one. `qualifier` is the source's own sentence that limits the claim, located and checked like a quote.
- `text` is copied from the source exactly: the same characters and spelling, auto-caption errors kept. Whitespace and line breaks may differ. Skip text with the ellipsis character (…); the pieces must appear in order (older PDF text copies, made in page layout, mix two columns on one line).
- `line` is the `grep -n` line of the first piece, `end` the last line when the extract spans lines; the check looks 2 lines either side.
- Dig writes `extracts.json`. Each report writes its own view, `extracts-<stem>.json`, with the stem of its `report-<stem>.md`; there each claim also carries `id`, its claims.json id, and holds that claim's located quotes, and the evidence page shows its votes.
- `translation` goes with quotes that are not in the user's language; the page marks it as a translation.
- `disagreements` set conflicting sources side by side without judging; `unreached` lists what could not be read and why.
- `report.py` also reads the files of older topics (an older tool's status values and its translation key).

## claims.json (report)

```
[{"id": "c1", "claim": "<one falsifiable claim, in English>", "quote": "<exact text: as located, or as the researcher copied it>",
  "url": "<original URL>", "label": "paper", "importance": "central",
  "votes": [{"refuted": false, "confidence": "high", "evidence": "<what the verifier checked>", "counter_source": "<URL>", "checked": "<YYYY-MM-DD>"}],
  "verdict": "survived"}]
```

- Ids run c1, c2 and on in the order the findings are taken, and are never reused in a topic.
- `importance` is `central` (the answer rests on it: at most 10 in one report's view, each located in that view, `extracts-<stem>.json`), `supporting` or `tangential`.
- `votes` holds only replies that parsed, at most 3, each with `checked`, the day the verifier ran. `verdict`: 2 refutations, `refuted`; fewer than 2 votes, `unverified`; otherwise `survived`. A claim never sent to verifiers has no votes and no verdict.

## notes/<subtopic>.md (report)

One file per researcher, English, one section per key question; each finding on one line so it can be grepped:

```
# <subtopic>
## Q1 <key question>
Takeaway: <one or two sentences>
- F1. <one falsifiable claim>. Quote: "<exact sentence from the page>" <URL> (<label>)
Inferences: <marked as inference>
Gaps: <looked for and not found, with the queries tried>
```

## Pulse files

`pulse/plan.json`, written by this session:

```
{"intent": "<what the user wants to learn>", "entity": "<head word first; optional>", "freshness": "balanced", "days": 30,
 "subqueries": [{"label": "main", "search_query": "<keywords with the anchor>", "ranking_query": "<what an on-topic item is about>",
                 "lanes": ["hn", "reddit", "github", "arxiv", "youtube"], "weight": 1.0}],
 "subreddits": ["<broad>"], "dedicated_subreddits": ["<the entity's own>"], "reddit_queries": ["<one or two words>"], "github_repos": ["<owner/name>"],
 "youtube_queries": ["<spoken phrasing>"]}
```

- `label` is unique and not `dedicated`, `reddit`, `repo` or `youtube`. `lanes` defaults to all five, `weight` to 1.0, `ranking_query` to the search query, `reddit_queries` (at most 3) to the entity, else the first subquery; subreddits are names, a leading `r/` is dropped.
- `pulse/<stem>.json`, written by `pulse.py`: `{topic, as_of, window: {from, to}, days, freshness, plan, lanes: {<lane>: {status, count, note}}, items, clusters, weak}`. The stem is the as-of date, with `-2` and on for later runs that day. `lanes` lists the lanes the plan used.
- An item: `{id, lane, lanes, url, links: {<lane>: <its page there>}, title, author, date, engagement: {<lane>: {<count>: n}}, snippet, comments: [{author, score, text, url}], exempt, score, relevance, subquery, grounded, pool}`. `date` is a UTC `YYYY-MM-DD`, or null when undated. A comment's `score` is its reactions on GitHub, its score on Reddit (as arctic-shift archived it, often below the live one) and its reply count on Hacker News. `exempt` marks dedicated subreddits and named repositories; `grounded` false keeps an item out of clusters; `pool` marks the items clustered.
- A cluster: `{id, title, score, lanes, items: [<item ids>, best first], labels}`, labels `single-lane` and `thin`. `clusters` are over the floor, `weak` under it.
- `pulse/<stem>-evidence.md`: the lanes, then each cluster with its items, links, snippets and comments, then the weak signals.
- `pulse/<stem>.md`: the brief (`references/pulse.md`).

## Model files

- `sources/board-<board>[-<table>][-<lang>[-clone] or -<hardware>]-<date>.tsv`, written by `models.py snapshot`: line 1 `# board= table= route= url= revision= fetched=` (plus `lang= clone=` or `hardware=`), line 2 the board's headers without decoration plus `link`, then one line per board row, its values verbatim (markup stripped, footnote marks kept). Later snapshots that day end in `-2` and on.
- `models/shortlist.json`: `{board, table, snapshot, metric, direction, filters, models}`; a model is `{repo, name, off_hub, link, scores, label, source, params, weight_gb, gb_16, gb_4bit, license, license_class, languages, languages_label, created, formats, gated, notes, front, dropped}`, and `quantized` on the front.
- `models/hub/<org>--<name>.json`: one repo's Hub facts, one key per line (`repo, url, sha, pipeline_tag, library, created, modified, gated, license, license_name, license_link, license_class, languages, base_model, arxiv, params, params_by_dtype, weight_gb, weight_source, largest_file_gb, formats, gguf, config, downloads, likes, card, config_file, files, fetched`); `follow` adds `papers` (`id, title, abstract, published, github`) and `quantized` (`count, formats, first`). A file fetched today is reused.
- `sources/hf-<org>--<name>-<sha7>.md`: a model card at that repo sha; a gated repo's card comes from its model page as `sources/hf-page-<org>--<name>.md`, saved by `fetch.py`.
- `models-<date>.md`: the deliverable (`references/models.md`).

## Watch files

- `watch.tsv`: a header line, then one feed per line: kind, name, feed URL, venue URL, tab-separated.
- `watch-state.json`: the item URLs already seen, per feed.
- `watch/<YYYY-MM-DD-HHMM>.md`: one file per check.
