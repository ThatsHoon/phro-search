# Formats

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

Marks after the label, when known: `retracted` (OpenAlex marks the work retracted: it never backs a required or central claim), `preprint` (a submitted version, such as fetch.py's submitted-copy: quote the published version when one exists), `landing-page` (fetch.py took the copy from a landing page: check that it holds the full text, not only a record), `unchecked` (fetch.py could not ask OpenAlex, so neither copies nor a retraction were checked), `archived-copy` (fetch.py read a dead page from its closest Wayback snapshot: it shows the page as of that snapshot), `examples` (the writer's own work is shown; read these first when the user wants how skilled people do it), `measured` (the writer's own measurements or comparisons), `self-reported` (a score or feature stated by its own authors), `ai-assisted` (the writer says an AI wrote it), `promo` (leads to something the writer sells), `unread` (downloaded, read by nobody yet), `auto-captions` (automatic captions: frequent errors, quote only what is legible, have the user check the video), `unverified` (from a search report, not read in the original).

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
feedback: fit=<yes|partly|no>; missing=<what the answer says is missing or off: item | item, or none>
- feedback, verbatim: "<the user's answer>"
```

The `brief:` and `feedback:` lines start at column 0 so that later intakes can grep them. Modes with other steps log them in this shape; their references name the sections.

## sources/index.tsv

Written by `fetch.py`, one row per fetched source, never edited by hand: a header line, then `name`, `url` (as asked: a URL, `https://doi.org/<doi>` or `local:<file name>`), `final` (the URL read), `fetched` (UTC), `published` and `modified` (as the page or the PDF states them, `-` when it does not), `extraction` (pdftotext, ocr, html, arxiv-html, text or captions), `version` (published, accepted or submitted for an open-access copy, `arXiv vN`, `arXiv` when the URL names no version, or `-`), `marks` and `files`, tab-separated. A PDF's published and modified dates are the file's own creation and change dates. For an archived copy, `final` is the snapshot URL and `published` reads `archived <YYYY-MM-DD>`, the snapshot date. A reused source adds no row, and a name fetched again gets a new row that replaces the older one. The evidence page shows each quote's dates and a retracted mark from it.

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
