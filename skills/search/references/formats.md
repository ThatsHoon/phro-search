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

Marks after the label, when known: `examples` (the writer's own work is shown; read these first when the user wants how skilled people do it), `measured` (the writer's own measurements or comparisons), `self-reported` (a score or feature stated by its own authors), `ai-assisted` (the writer says an AI wrote it), `promo` (leads to something the writer sells), `unread` (downloaded, read by nobody yet), `auto-captions` (automatic captions: frequent errors, quote only what is legible, have the user check the video), `unverified` (from a search report, not read in the original).

## File names and locations

- `<author>-<year>-<short-title>` in lowercase ASCII with hyphens; arXiv papers `arxiv-<id>-<short-title>`.
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
- spawned: <searcher, method, what it was asked>: <returned | stopped>
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

The `brief:` and `feedback:` lines start at column 0 so that later intakes can grep them. Report mode writes `research`, `archive`, `verify` and `write` sections in the round's shape (spawned, came back, fetched, decisions); `verify` adds `votes: <n> central claims; <s> survived, <r> refuted, <u> unverified; <m> missing votes`.

## extracts.json

```
{"title": "...", "question": "...", "stopped": "<stop reason>",
 "claims": [{"claim": "...", "status": "sourced", "note": "...",
             "quotes": [{"file": "<file in sources/>", "line": 12, "end": 14, "text": "<verbatim>", "translation": "...", "mark": "..."}]}],
 "disagreements": [{"topic": "...", "quotes": [{"file": "...", "line": 3, "text": "...", "who": "..."}]}],
 "unreached": ["<item>: <why>, <URL>"]}
```

- `status` is `sourced`, `partial` or `none`. One claim per required claim, in the user's language. `note` is one flat line on who did what: no conclusions, no ratings.
- `text` is copied from the source exactly: the same characters and spelling, auto-caption errors kept. Whitespace and line breaks may differ. Skip text with the ellipsis character (…); the pieces must appear in order (two-column PDFs mix columns on one line).
- `line` is the `grep -n` line of the first piece, `end` the last line when the extract spans lines; the check looks 2 lines either side.
- In report mode each claim also carries `id`, its claims.json id, and holds that claim's located quotes; the evidence page then shows its votes.
- `translation` goes with quotes that are not in the user's language; the page marks it as a translation.
- `disagreements` set conflicting sources side by side without judging; `unreached` lists what could not be read and why.
- `report.py` also reads the files of older topics (an older tool's status values and its translation key).

## claims.json (report)

```
[{"id": "c1", "claim": "<one falsifiable claim, in English>", "quote": "<exact text: as located, or as the researcher copied it>",
  "url": "<original URL>", "label": "paper", "importance": "central",
  "votes": [{"refuted": false, "confidence": "high", "evidence": "<what the verifier checked>", "counter_source": "<URL>"}],
  "verdict": "survived"}]
```

- Ids run c1, c2 and on in the order the findings are taken, and are never reused in a topic.
- `importance` is `central` (the answer rests on it: at most 10, each located in extracts.json), `supporting` or `tangential`.
- `votes` holds only replies that parsed, at most 3. `verdict`: 2 refutations, `refuted`; fewer than 2 votes, `unverified`; otherwise `survived`. A claim never sent to verifiers has no votes and no verdict.

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

## Watch files

- `watch.tsv`: a header line, then one feed per line: kind, name, feed URL, venue URL, tab-separated.
- `watch-state.json`: the item URLs already seen, per feed.
- `watch/<YYYY-MM-DD-HHMM>.md`: one file per check.
