# report

A decision-ready answer from many sources. Researchers gather findings with exact quotes; every cited page is archived and each quote located in it; the claims the answer rests on are attacked by three verifiers each; this session writes the report on what survived. Researchers run as `phro-search:web-gatherer`, verifiers as `phro-search:verifier`, the support pass as `phro-search:local-reader`.

## Before spawning

- The confirmed brief heads `map.md`. Its required claims are 3 to 6 key questions (Q1 to Q6) the report must answer, at least one in the request's own words.
- Decision criteria: for a choice between options, the axes they are compared on (cost, accuracy, license, effort), taken from the brief's use and constraints.
- Subtopics: split the question so that no two overlap and together they cover every key question. For a choice between options, one researcher always takes the viewpoint independent of the vendors (critics, failure reports, independent measurements) across every option; add that viewpoint to any other question when it is contested.

| The question | Researchers |
|---|---|
| one focused question | 3: how it works and where it is used; measured results; limits, failures and criticism |
| a choice between options on criteria | 4 or 5: one per group of criteria, each covering every option, and the independent viewpoint |
| options, entities or regions taken one by one | one per option, at most 5, plus one for head-to-head comparisons when they exist, and the independent viewpoint when the options are a choice |
| a large set to enumerate | at most 6 slices along a natural split (kind, year, region) |

- Checkpoint: show the subtopics and the decision criteria in one round before spawning. Skip it when the user's brief already named them or there is no user to answer; log the skip and why.
- Log `research`, `archive`, `verify` and `write` sections in the round's shape of log.md (spawned, came back, fetched, decisions); `verify` adds `votes: <n> central claims; <s> survived, <r> refuted, <u> unverified; <m> missing votes`.
- Plan line: "PLAN: report; 5 researchers, up to 2 support readers, up to 30 verifier calls; ceiling 39 agent calls", with the researcher count from the table and the ceiling 34 above it (it counts the researchers, at most 2 for a gap round, a support reader and one more for reworded claims, and 3 verifiers for each of at most 10 central claims).

## Research

Spawn every researcher in one turn. Write each reply, as it comes, to `<topic>/notes/<subtopic>.md` under a `# <subtopic>` heading, in the shape the brief below asks, one finding per line; then read only the `Takeaway`, `Gaps` and finding lines of the notes (`grep -n "^Takeaway\|^Gaps\|^- F" <topic>/notes/*.md`); read them in full only to write.

```
You are a researcher for a decision report.

Question: <generic problem statement>
Your subtopic: <subtopic>. Other researchers cover: <other subtopics>; stay out of them.
Key questions: <Q1 ...>
Decision criteria: <criteria, or none>
Constraints: <time window, region, languages, versions>
Suggested sources: <official docs, papers, standards, benchmarks with their method, practitioners' own write-ups>

Method: short queries; open the page itself and never trust a snippet; never repeat a query; about 10 tool calls, never more than 15. Judge each source: original or aggregator, fact or speculation, who stands behind it. A conflict between sources and "no reliable source found" are findings too.

Write the notes in English, one section per key question:
## Q<n> <question>
Takeaway: <one or two sentences>
- F<n>. <one falsifiable claim>. Quote: "<the sentence from the page that states it, copied exactly in its own language>" <URL> (<paper | official | first-hand | observed | summary>)
Inferences: <what follows, marked as inference>
Gaps: <what you looked for and did not find, with the queries tried>
Keep each finding on one line. A finding without a URL and an exact quote goes under Gaps.
Reply with the notes, then one line per key question: answered, partly or gap.
```

One gap round at most: 1 or 2 researchers, only for a key question left without a finding; then go on. A key question still empty is a gap in the report.

## Archive and locate

1. Collect the URLs of the finding lines; one per host and path. Fetch at most 25 with `fetch.py <topic>/sources <name> <url>`, passing a paper's DOI so its legal open-access copies come first: first the pages behind findings the answer would rest on, then by label (paper, official, first-hand before summary). Reuse what `sources/` already holds; never download again. Every FAIL goes to `log.md`; a walled page behind a likely central finding goes to the user's browser, as in dig.
2. Locate each finding: grep a distinctive phrase of its quote in the fetched copy (`grep -n -F -e "<phrase>" -e "<phrase>" <topic>/sources/<file>` for several at once), read a few lines around a hit, and take the text exactly as the copy has it. Not found (the page changed, the researcher paraphrased, the fetch failed): the finding stays URL-only.
3. Write `claims.json`: one entry per finding the report may use. Importance:
   - central: the answer would change if it were false; at most 10 in one report's view, each located in that view (`extracts-<stem>.json`); a URL-only finding is never central, nor is one whose source is retracted;
   - supporting: backs a section;
   - tangential: context.

   ```
   [{"id": "c1", "claim": "<one falsifiable claim, in English>", "quote": "<exact text: as located, or as the researcher copied it>",
     "url": "<original URL>", "label": "paper", "importance": "central",
     "votes": [{"refuted": false, "confidence": "high", "evidence": "<what the verifier checked>", "counter_source": "<URL>", "checked": "<YYYY-MM-DD>"}],
     "verdict": "survived"}]
   ```

   - Ids run c1, c2 and on in the order the findings are taken, and are never reused in a topic. `claim` is English; `quote` is the located text, or the researcher's copy when unlocated.
   - `votes` holds only replies that parsed, at most 3, each with `checked`, the day the verifier ran; `verdict` follows the vote rule in Verify. A claim never sent to verifiers has no votes and no verdict.
4. Write the report's view, `extracts-<stem>.json` (the stem of `report-<stem>.md`: the date, then -2 and on), with one claim per located finding, carrying its id, its claim text in the user's language, its located quotes and status `partial` (`sourced` once the support pass in Verify rates a quote full); conflicting findings go side by side under `disagreements`, unfetched pages under `unreached`. Run `report.py <topic> <stem> --check` and fix each MISMATCH by copying the source text exactly.

## Standards

For a source that is a standard, a specification or an RFC. Families: robotics and mapping (OGC; ISO/TC 211, geographic information; ISO/TC 204, intelligent transport systems; ASAM OpenDRIVE and OpenSCENARIO; ROS REPs), and IETF and W3C.
- Before quoting one, take its body, document id, edition and status from the body's own index, never from a secondary page, and write them into the claim ("RFC 9110, Internet Standard, obsoletes RFC 7231"; "ISO 19115:2003, withdrawn, revised by ISO 19115-1:2014"):
  - IETF: the RFC Editor's page for the RFC: status, obsoleted by, updated by, and its errata. A verified erratum that touches the quoted text is quoted with it.
  - W3C: the document's status section and the latest version its TR page names (Recommendation, Candidate Recommendation, Working Draft, Note, superseded or obsolete).
  - ISO, IEC and IEEE: the catalog page: edition, publication date, stage, and withdrawn or revised by.
  - OGC: the standard's page in OGC's standards list (version and status); ASAM: the standard's page (release version); ROS: the REP's header in the REP index (Status, Replaced-By).
- Mark each standards quote normative (a requirement stated in a normative clause or annex) or informative (notes, examples, introductions, informative annexes). Only a normative quote says what the standard requires.
- A superseded, withdrawn or draft text never backs a central claim about current requirements; quote it only for history or for what a draft proposes, and say so in the claim.
- ISO, IEC and IEEE full texts are out of reach: cite the catalog page for edition and status, send the full text to the user's browser path as a walled item, and quote its clauses only from a copy the user saves. A free preview counts as the text for the clauses it shows.

## Verify

Before any vote, run the support pass (`references/briefs.md`) on every located quote in the view, central and supporting, and write each `support` and `qualifier` into the view. A central claim with no full rating is lowered to supporting, or reworded to what its source says and rated again: one more support pass takes all the reworded claims together, and a reworded claim still below full is lowered to supporting. Only a central claim rated full is sent.

Three verifiers per central claim, one per starting point: counter-evidence; source standing and date; benchmark and marketing. Several claims may share a turn, at most 12 verifiers at once; record a claim's verdict only when each of its three verifiers has replied or been stopped.

```
You are a verifier. Try to refute one claim.

Claim: <its claims.json text, copied exactly>
Quoted support: "<quote>" from <URL> (<label>)
Context from the archived copy: <the located paragraph, from its first line to its last>
Start with: <counter-evidence | source standing and date | benchmark and marketing>
It serves the question: <Q>

A support reader has already checked that the quote states the claim. Search from your starting point, then check, in order: does a credible source contradict it; is the source strong enough for the claim (a maker's page on its own product's results is weak); is it outdated; is it marketing or a picked benchmark. If you are unsure, the claim is refuted. At most 8 tool calls.
Reply with one JSON object and nothing else:
{"refuted": <true or false>, "confidence": "<high, medium or low>", "evidence": "<one or two sentences on what you checked>", "counter_source": "<URL, only when a source contradicts the claim>"}
```

Vote rule: a reply that is missing, not that JSON object, or without a true or false `refuted` is no vote. Record the votes under the claim in `claims.json`, each with today's date as `checked`, then its verdict: 2 refutations, refuted; fewer than 2 votes, unverified (a failed check, never read as refuted); otherwise survived. Verification runs once and is never repeated to rescue a claim; a claim is never reworded after its votes. `report.py` checks every verdict against its votes.

## Write

Write the report in this session, where the claims, votes and extracts already are. Read the notes in full and `STYLE.md`, then write `<topic>/report-<stem>.md` in the user's language, quotes in their own language:

```
# <title>
<one paragraph that answers the question first (BLUF), naming its as-of date (YYYY-MM-DD) and citing the claims it rests on>
## <a heading that states the pick, or the landscape's main finding>: the decision table (a choice), or the table of entities by key questions (a landscape or standards report)
## <3 to 5 sections whose headings state their finding>
## <when another option wins> (a choice): the conditions under which another option is the better pick, each citing the claims behind it
## <what would change this answer> (a choice): the 1 to 3 central claims the pick rests on most, and for each the check the user can run
## <a heading that starts with the word for conclusion in the report's language>: new implications only, citing the claims they rest on
## <evidence>: a table with the columns id, claim, label, location (sources/<file>:<line>, or URL only), URL, vote
## <refuted and unverified claims>: each with the reason from its votes
```

- The decision table: the options as rows, the brief's decision criteria as columns. Each cell is a short value with the claims behind it ("40 ms [c3]"), or the word unknown alone, in the report's language, when no claim backs it. Mark a cell unverified when none of its claims survived votes; a refuted claim never fills a cell. A landscape or standards report has no pick: its table puts the entities (projects, vendors, standards) as rows and the key questions as columns, under the same cell rule, and it has no "when another option wins" or "what would change this answer".
- Cite claims inline as [c3] or [c3, c7]. Every fact cites a claim; add nothing that is not in claims.json.
- The BLUF and the conclusion cite survived claims only. A refuted claim appears in a section only as refuted, with why.
- Prose, not lists, outside the tables. Say what is unknown, give the strongest case for the other side, and take a position where the evidence allows one.
- Check the report with `check.py --kind report <topic>/report-<stem>.md`.

## Deliver

1. `report.py <topic> <stem>` builds `evidence-<stem>.html` with the votes beside each claim; it must print OK.
2. With no lead-in: the report's BLUF paragraph as it stands in the file; the report path, then `evidence-<stem>.html`; the tally (central claims survived, refuted, unverified); key questions left as gaps; important walled pages with URL and why they matter; process problems (failed fetches, missing votes, agents that overstepped their brief).
3. The feedback question.

## Again on the same topic

A new report gets a new stem (`report-<date>-2.md` on the same day) and its own view and page; earlier reports are never overwritten. Reuse `sources/` and `claims.json`: new findings take the next ids, and claims already verified keep their votes. A central claim whose newest vote is older than the brief's recency need, or has no `checked` date, is verified again under a new id (its claim, quote and URL copied, fresh votes); the old claim keeps its votes, and from then on reports cite the new id. Gaps become required claims for a dig, and a dig archive feeds a report without downloading again.
