# phro-search structure review

Date: 2026-11-01. Base: commit d233fd6 (main). The owner confirmed every decision in section 3 on 2026-11-01, over three grilling rounds. This review changed no plugin code.

Method: a full read of the manifest, skill, references, hook, scripts, tests, evals and plan; script audits with the unit tests run (216 pass); an adversarial check of each finding against the code; checks of Claude Code platform behavior in the official docs (appendix A); then grilling over a design tree, one round per frontier, until no decision was open.

Every decision is ranked the same way: research outcome quality first (the right and original sources, recall of canonical work, correct and verified claims, decision-useful deliverables, fit to the need), then cost and latency, then robustness and hygiene.

## 1. Summary

Sound today:
- One router skill that loads one mode reference per run, and stdlib scripts for the mechanical work (SKILL.md:10-21, 56-66).
- Strong evidence discipline: archived originals, quotes checked against their lines (report.py:202-221), three adversarial votes per central claim, and unverified kept apart from refuted (report.md:76; report.py:158-160).
- Tests keep the docs and the code in sync (tests/test_plugin.py), and 216 unit tests pass on a fake network.
- Honest coverage: failed lanes and walls are reported, never passed off as silence (pulse.md:86; dig.md:51).

Largest problems, all verified:
1. Rounds assume blocking waits, but interactive sessions run subagents in the background by default, and most acceptance runs were headless (F1).
2. pdftotext -layout puts both columns of a two-column paper on one line, which breaks quote location (F16).
3. A located quote is not a supporting quote, and nothing checks support (F17).
4. Round 0 has no bibliographic method, so the saturation stop measures one search engine (F14).
5. OpenAlex data on legal copies, retractions and versions is thrown away, while walls are the main reason digs fall short (F15).
6. No source, claim or vote carries a date or version (F20).
7. No eval measures research outcomes (F27).
8. Pulse has no Hugging Face lane, though models lead the owner's topics (F22).
9. Subagents get every tool, Bash included, and every CLAUDE.md (F43).
10. The report has no decision table and no conditions that would flip the pick (F24).

Highest-value changes: measure outcomes first (R1), fix PDF text and OpenAlex use (R9), add the support pass (R5), isolate subagent tools (R3).

## 2. Findings by lens

Impact is the effect on research outcomes unless marked otherwise. "plan:N" is a line of docs/plans/2026-10-30-phro-search.md.

### 2.1 Flow and hand-off contracts

- F1. Dig and report say "wait for both" and "wait for every reply" (dig.md:18, 45; report.md:23, 61). In interactive sessions fork mode is on by default: subagents run in the background and their results arrive as notifications in later turns (appendix A6). A round can close, or saturation be counted, before every searcher has reported. Most acceptance runs were headless, where Claude can wait (plan:586, 600, 615). Impact: high.
- F2. Dig and report write the same extracts.json and report.html in one topic folder (SKILL.md:54; dig.md:58; report.md:57, 99), and report.md:105-107 encourages a report on a dug topic. report.py requires every central claim to be located in that single extracts.json (report.py:165-174), so a dig after a report fails --check, and a second report trips the 10-central cap (report.py:169-170). Impact: high.
- F3. Researchers write their own notes (report.md:26) and the docs agent writes a note and runs Bash (docs.md:27, 38), so briefs carry local paths against SKILL.md:70 (plan:624). report.md:80 says Claude Code refuses a subagent's report write; the docs do not say so (appendix A5). Impact: medium.
- F4. Docs mode writes into the user's repo at a default path it announces only afterwards (docs.md:8) and keeps no log (docs.md:47), yet it still passes through the earlier-topic grep and the topic lookup (SKILL.md:27, 48). Impact: medium.
- F5. The plan line before the first spend held in 8 of 11 headless runs; the Korean formalized report prompt failed 3 of 3, with the plan only in thinking (SKILL.md:49; plan:641). Impact: low for outcomes, medium for trust.
- F6. Mode references spell script paths as ${CLAUDE_PLUGIN_ROOT}/scripts/... (models.md:48-60, 114; pulse.md:42), but substitution is documented only for SKILL.md, not for files read with Read (appendix A3). Impact: low.

### 2.2 Error and exception handling

- F7. The retry policies differ. Only models.py retries 5xx and timeouts (models.py:202-241); fetch.py, chain.py and watch.py retry 429 only (fetch.py:154; chain.py:135; watch.py:117); pulse.py retries 429 and 422 but not 500 (pulse.py:143), although arctic-shift returns 500 for uncached queries (plan:670). Transient errors become lost lanes and failed fetches. Impact: medium.
- F8. chain.py find sends a title raw into the OpenAlex title.search filter, so a comma breaks the filter; a test pins this (chain.py:207-210; tests/test_chain.py:170-172). Impact: medium.
- F9. Without pdftotext every PDF fails, arXiv included, before the arXiv HTML fallback runs (fetch.py:349-351, 372-376, 470-473). Impact: high on machines without poppler.
- F10. models.py has no overall deadline (60 s per request with retries, over 40 requests), and main catches only Usage, Drift, Fail and ValueError, so an unexpected response shape prints a traceback (models.py:202-241, 985-997). Impact: low.
- F11. Non-atomic writes in models.py stick: a truncated snapshot becomes the day's KEPT baseline, a truncated card is never fetched again, and a truncated facts cache fails later shortlists (models.py:516, 610, 896). Impact: low.
- F12. Pulse lane exceptions keep only the type name (pulse.py:417-418). Impact: low.
- F13. watch.py check exits 0 when only some feeds failed (watch.py:399); watch.md does not say so. Impact: low.

### 2.3 Domain knowledge

- F14. Round 0 runs two web searchers on the same engine (briefs.md:10; dig.md:16). Their overlap drives the 70 percent stop (dig.md:17, 49), although theory.md:88 grants that they are not independent samples. A search sorted by citations ranks the original first (theory.md:115), but chain.py has no topic query (chain.py:207-210), and nothing checks the map against the field's most cited works. Impact: high.
- F15. chain.py requests only best_oa_location and open_access and prints one URL (chain.py:39, 165-170): no repository copies, version, work type, venue or retraction flag. fetch.py fetches a DOI at the publisher as given (fetch.py:474). Walls stopped 2 of 5 earlier topics and left two T1.8 claims partial (plan:179, 571). Impact: high.
- F16. pdftotext runs with -layout (fetch.py:353), which mixes the columns of a two-column page on one line (dig.md:41; formats.md:92). Quotes that span lines and words hyphenated at a line end then fail the check (report.py:213-221), and a finding without a located quote can never be central (report.md:54). Impact: high.
- F17. report.py proves that a quote sits near a line, not that it supports the claim (report.py:202-221). In dig, the agent that located the quote also sets the claim's status (dig.md:58); T1.8 needed a rerun to correct a stop note that called partial claims sourced (plan:571). In report, verifiers check quote fidelity with web tools only and two lines either side (report.md:64, 68). Impact: high.
- F18. All three verifiers share one brief and one model (report.md:3, 61), unsure means refuted (report.md:71), and two refutations kill a claim (report.md:76). Their errors correlate: in T2.4 one brief added a ratio, and the votes refuted that ratio (plan:578). Impact: medium.
- F19. No method looks for counter-evidence on purpose (briefs.md:14), although at least half of dig's required claims ask how well a method works or where it fails (intake.md:122). Impact: medium.
- F20. fetch.py keeps only the title and body and does not store the extraction path it prints (fetch.py:334-344, 500); the sources table has no date column (formats.md:23); reused votes never expire (report.md:107). Impact: high in fast fields.
- F21. Standards are one of the owner's topic classes (plan:178), but edition, status, errata and normative text are not handled (formats.md:39-46). Impact: medium.
- F22. Pulse has no Hugging Face lane (pulse.py:32), and a T3.5 brief wrongly said no notable model had shipped (plan:586). Models mode has no board for embeddings and only self-reported values for current LLMs (models.md:34-38); the embedding prompt went to another skill in 3 of 3 runs (plan:618). Impact: high for model topics.
- F23. The intake promises sources in English and the user's language (intake.md:65; dig.md:16), but pulse has no Korean lane and may not quote web supplements (pulse.md:51; check.py:16-18). Impact: low for this owner (R12).
- F24. The report template has no table of options by criteria, no conditions under which another option wins, and no list of the claims the pick rests on (report.md:83-89). Critics join only when a question is known to be contested (report.md:9). T2.4's added value was exactly such a condition (plan:578). Impact: medium.

### 2.4 Self-correction

- F25. Learning is recall of the user's preferences: the intake greps the brief and feedback lines of earlier topics (SKILL.md:27; intake.md:26). Process failures are logged per topic (formats.md:68, 75) but never aggregated; docs keeps no log (docs.md:47), watch has no log step, and the feedback answer is free text that cannot be counted (SKILL.md:77). Impact: medium.
- F26. The intake grep reads every brief and feedback line of every topic. At about 25 runs a month (plan:178) it passes the Grep tool's default limit of 250 lines in roughly 5 months (an estimate). Impact: low now.
- F27. Nothing in tests/ or evals/ measures recall, claim correctness or verifier accuracy. All 15 intake cases grade process; even form-en-adam, which names its gold papers, is graded only on asking no questions (evals/intake/form-en-adam/case.yaml:12-25). The searcher tier, the 2-searcher cap (dig.md:77), the round-0 method and the vote rule have no numbers behind them, and T5.3's rating of 5 real requests is still open (plan:643). Impact: high.

### 2.5 Token and context efficiency

- F28. Model placement is prose. "Light model tier" names no model (briefs.md:7; dig.md:12), other roles say "mid model (sonnet)" (report.md:3; docs.md:14), and spawn lines in the log record no model (formats.md:66). The work left to models is judgment, since the mechanical work is already scripted. Impact: medium.
- F29. watch.py check prints every new item (watch.py:372-375), 215 lines of strangers' text in T5.2 (plan:623), and watch.md:26 filters only at delivery. Impact: low; also an injection surface.
- F30. formats.md (about 11 KB, every mode) loads whenever a working file is written (SKILL.md:50). Impact: low.
- F31. The check loop resends the whole reply through standard input on every pass (SKILL.md:76; dig.md:73). Impact: low.
- F32. The 600-character cap is the owner's rule, not the platform's (tests/test_plugin.py:133; plan:523); the platform truncates description plus when_to_use at 1,536 characters (appendix A2). Vague prompts fired no skill in 2 of 3 first-pass runs (plan:627), and "best model for" is the only English trigger (SKILL.md:3). Precision is good: 12 of 12 out-of-scope runs stayed quiet (plan:618). Impact: medium.
- F33. Subagents load every CLAUDE.md unless their agent file sets omitClaudeMd (appendix A4). Impact: low; also privacy.

### 2.6 Reuse

- F34. fetch.py refuses an existing name and keeps no URL index, so "never download again" (report.md:51) depends on the model (fetch.py:483-485). Impact: medium (cost).
- F35. Five scripts carry their own HTTP helper, and the helpers behave differently; the SHARED test guards only the egress and clean copies (tests/test_plugin.py:15-17). B3 came from one of these copies. Impact: low.
- F36. chain.py caches nothing, and a title search costs OpenAlex credits each time (dig.md:36; plan:565). Impact: low.

### 2.7 Install and config robustness

- F37. Quoted ~ paths are not expanded: fetch.py and models.py write silently into a literal ~ folder, and report.py and check.py fail (fetch.py:505; models.py:974; report.py:300; check.py:260). Impact: medium on Windows.
- F38. README.md lists no requirements (Python 3.10+, Git Bash on Windows, poppler, tesseract and pdftoppm, yt-dlp), no setup for the term list and no example allow rule (README.md:7-27). Impact: medium for publication (T5.6).
- F39. SKILL.md:58 calls python; stock macOS and many Linux systems have only python3, which the hook already handles (hooks/hooks.json:9). Impact: low.
- F40. Native Windows headless refuses Bash and Write grants, so evals that run scripts cannot run there (plan:628), and claude plugin eval drops the competing skills a routing test must beat (plan:615). Impact: shapes how evals run (R1).

### 2.8 Safety boundaries

- F41. The egress hook fails open when its interpreter cannot start (a missing python, or the Windows Store stub, exits 127 or 9009) or when its 10 s timeout fires, because only exit 2 blocks (hooks/hooks.json:9-10; hooks/egress.py:1-2, 50-71; appendix A1). A global onFailure block would instead cut all web access for installs with no term list, since a plugin hook runs in every session and no list passes by design (plan:569). Impact: safety.
- F42. watch.py check sends stored feed URLs with no term check, unlike add (watch.py:298-303, 336-352), against the plan's rule that every network script checks terms (plan:495). Impact: safety.
- F43. Subagents get the full tool set, so a web-reading agent can use curl, which the WebSearch|WebFetch matcher never sees (hooks/hooks.json:5), and an injected page could steer it to local files; SKILL.md:71 is only a prompt rule. Impact: safety.
- F44. check.py's invisible-character rule applies to quote lines too (check.py:8), so a quote holding a no-break space or a soft hyphen fails; in T1.8 such a quote was dropped to pass the check (plan:571). Impact: medium (evidence integrity).

## 3. Decisions

"Rejected" lists the options considered and turned down, with the reason.

### R1. Measure outcomes before changing defaults

Build three eval sets, and change a default only on their numbers:
- Verifier set: 20 to 30 planted claims made from T2.4's claims.json (overstated, outdated, contradicted and true variants), 3 votes each. Score false refutations and false survivals.
- Round-0 recall: the owner marks the canonical works in 2 or 3 closed topics. Run round 0 only, 3 repeats per arm: haiku against sonnet searchers, and two web searchers against one web searcher plus the citation list (R8). Score gold recall, the share of searcher URLs that fetch as real hits, and the overlap numbers.
- Routing: the 34 T5.1 prompts plus about 12 near misses ("보고서로 정리해줘" about a document in hand, a scikit-learn "best model for", "새 글 확인" about Slack), 3 runs each, with the competing skills present.

Also run one dig and one report interactively with Claude Code's defaults, and rate 5 real requests on the delivered result as well as the brief (extends T5.3).

Where: the routing set runs headless on Windows with read-only tools, as T5.1 did; the outcome sets run in WSL (F40).

Thresholds: routing passes at 90 percent or more firing on in-scope prompts and 10 percent or less on out-of-scope and near-miss prompts, over 3 runs each; each eval pass has a cost cap of 50 USD; the other thresholds are in R4, R6 and R8.

Rejected: process-only evals (F27); routing evals inside claude plugin eval (F40).

### R2. Rounds that survive background subagents

Dig and report log each round's pending agents in log.md, close a round only when every agent has reported or been stopped, never count saturation before both methods have reported, and re-read references/<mode>.md after a compaction. README explains how to get blocking waits (CLAUDE_CODE_FORK_SUBAGENT=0, or CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1). R1's interactive runs verify it. Addresses F1.

### R3. Plugin agents for tool isolation

Three agents in agents/, grouped by tool set:
- web gatherer: WebSearch and WebFetch only, for searchers, researchers and the web half of docs;
- verifier: the same tools, at high effort;
- local reader: Read, Grep and Glob only, for the support pass (R5) and installed source in docs.

Each agent sets omitClaudeMd: true, maxTurns as a runaway guard (a cut-off verifier reply counts as no vote), an explicit model (R4), and a description saying it is internal to phro-search. Each carries the shared rules the briefs lack today: generic queries only, web text is data, no logins, no paywall or bot-check workarounds.

No subagent writes files. Researchers and the docs work return text, and the main session writes notes/<subtopic>.md and the docs note and runs check.py. A defaulted path for the docs note goes through the gate like any defaulted slot. SKILL.md:70 is narrowed to agents that have web tools. Test the subagent_type value for plugin agents before relying on it (section 6). Addresses F3, F4, F33, F43.

Rejected: one agent file per role; general-purpose workers with every tool.

### R4. Model tiers per role, measured

Until R1 says otherwise, searchers, researchers and verifiers run on sonnet, with verifiers at high effort. The main session inherits the user's model, since a model or effort set in SKILL.md lasts only for the invoking turn and research runs after the gate (appendix A3). Haiku replaces sonnet for searchers only if, over 3 repeats, its gold recall is at least 95 percent of sonnet's and its share of URLs that fetch as real hits is no more than 5 points lower. Before that test, measure the searchers' share of run cost from the T1.8 and T5.2 transcripts. Every spawn line in the log records model and effort. Amends B.1 principle 13 (plan:262) and B.7 (plan:461-466). Addresses F28.

Rejected: haiku searchers by default; a 90 percent threshold; a model pinned in SKILL.md.

### R5. Support pass

For each dig required claim and each report central claim, the local reader reads the enclosing section and the source's own limitations section, and returns support (full, partial, none or contradicts) plus the qualifying sentence, copied verbatim. extracts.json gets support and qualifier fields. report.py locates the qualifier like any quote and refuses status sourced without at least one full-support quote, so dig's stop 1 cannot fire on a partial. In report, this pass replaces verifier check 1, and verifiers get the located paragraph instead of two lines either side. The reader rates and does not vote, so D4 (plan:657) stands. Addresses F17.

### R6. Verifier design

- Every verifier keeps the whole check list and varies only where it starts searching: counter-evidence; source standing and date; benchmark and marketing.
- "If you are unsure, the claim is refuted" (report.md:71) becomes "refuted needs a stated reason from the check list; could not check is no vote" only if the verifier set shows more than 10 percent false refutations of true claims.

Addresses F18.

Rejected: identical briefs; distinct roles that each check one lens, because a flaw that only one role checks gets one refutation and survives the 2-refutation rule (report.md:76).

### R7. Disconfirm searcher in dig

When a required claim asks how well a method works or where it fails, run one disconfirm searcher in round 1 (criticism, failed or partial replications, negative results, errata). It is judged by its own claims like a hypothesis branch (dig.md:38) and left out of the overlap count. The searcher ceiling rises from 8 to 9 or 10 calls (dig.md:12). Addresses F19.

Rejected: a disconfirm searcher in every dig; none.

### R8. Round 0 with a bibliographic method

Add chain.py topic '<anchor terms>' [--since YEAR], an OpenAlex title-and-abstract search sorted by citations that excludes paratext, erratum and editorial types, plus a second call with --since for recent leaders; add chain.py related <W id> for the neighbors move.

In fields with papers, round 0 becomes one English web searcher plus the citation list, and saturation is counted between the two. A Korean searcher joins only for Korea-specific topics (R12). Fields without papers keep two web searchers (term search; surveys and textbooks). The switch waits for R1 and ships if the pair's gold recall is at least that of two web searchers.

Ships now, without the test: a canonical audit before delivery (each of the top 20 works for the confirmed terms is in the map, out of scope with a one-line reason, or missing and sent to Next leads; log "audit: k of 20" as the run's recall estimate), and seeding from earlier topics' Sources rows, shown as "from earlier topic X" and never applied unseen. Addresses F14.

Rejected: two web searchers with the citation list as an uncounted reference; no change.

### R9. Sources: PDF text, OpenAlex, provenance, Wayback

- PDF text: write pdftotext's reading-order output as <name>.txt, the file to grep and quote, and the -layout output as <name>.layout.txt for tables. For arXiv, try the HTML version first and fall back to the PDF on any failure (404, a conversion notice, too short). Before switching, measure on the earlier topics' PDFs: hyphen-split line ends, quotes that needed ellipses, table rows kept intact. Drop the column ellipsis rule (formats.md:92) only if the counts support it. Addresses F9, F16.
- OpenAlex: normalize titles before title.search (commas and pipes become spaces, a leading ! is dropped, standalone AND, OR and NOT are lowercased) and flip tests/test_chain.py:170-172. Add type, venue, publication_date, is_retracted and locations to FIELDS, with a flags column: retracted, preprint, erratum or comment, accepted copy available. chain.py oa <DOI or W id> lists every open-access location, published before accepted before submitted, with repository and arXiv copies ahead of publisher pages that bot-check. Given a DOI, fetch.py tries those locations before the publisher and names the version it archived. cites gets --sort recent and --since. An optional OPENALEX_API_KEY comes from the environment and is never printed. A retracted work never backs a required or central claim; a preprint carries a mark, and the published version is quoted when one exists. watch gets an OpenAlex source kind for journals and proceedings that have no feed. Addresses F8, F15.
- Provenance: fetch.py writes one row per source to sources/index.tsv: URL, final URL, fetched_at, the page's published and modified dates where it states them, the extraction path, and the open-access version. It reuses a source already fetched from the same URL and refuses a taken name with a different URL. Dates and versions appear in the sources table, the extracts and the evidence page, and a report's BLUF names its as-of date. Votes carry their check date; a reused central vote older than the brief's recency need is verified again, while report.md:76 still forbids reruns to rescue a claim. Addresses F20, F34.
- Wayback: snapshots only for dead public pages (404, 410, DNS, TLS, timeout), marked as archived copies with their date; never for 401, 403, 451 or wall pages.

Rejected: a hard pdftotext dependency; DOIs fetched only at the publisher.

### R10. One evidence base, one view per deliverable

The topic keeps one growing evidence base: sources/, sources/index.tsv and claims.json. Each deliverable gets its own view: dig keeps extracts.json and report.html; each report writes extracts-<stem>.json and evidence-<stem>.html, with the existing stem rule (the date, then -2 and on); report.py <topic> [<stem>] checks quotes, locations and the 10-central cap only for the claims that view cites. Addresses F2.

Rejected: one folder per run (it breaks report.html's relative sources/ links and vote reuse); file names versioned by date only (same-day runs collide).

### R11. Standards

Families: robotics and mapping (OGC, ISO/TC 211 and TC 204, ASAM OpenDRIVE and OpenSCENARIO, ROS REPs), plus IETF and W3C. Before quoting, take the body, document id, edition and status from the body's own index (RFC obsoleted-by and errata, W3C status, ISO edition and withdrawal). Mark each quote normative or informative. A superseded or draft text never backs a central claim about current requirements. Assumption, the owner's default: no institutional access to ISO, IEC or IEEE full texts, so their catalog pages are cited for edition and status, and full texts go to the user's browser path. Addresses F21.

### R12. Korean sources

Korean community and academic sources are secondary and serve Korea-specific topics (national standards, market, regulation). No Korean-specific adapters now; watch already finds feeds through typed alternate links (watch.py:207-225). For a Korea-specific pulse topic, a web supplement may be quoted once fetch.py has archived it and the quote is located in that copy; pulse.md:51 and check.py:16-18 change to allow it. Addresses F23.

Rejected: adapters now for GeekNews, velog, Naver blog, KCI or RISS.

### R13. Coverage for model topics

Amend D3 (plan:656): add a keyless hf lane to pulse.py. It collects models created in the window that match the subquery, with likes, downloads and trending score as engagement, plus daily papers with upvotes and comments. Wire it into the lane table (pulse.md:25-30), check.py NAMES and the coverage line. Keep it only if a replay of the T3.5 topic surfaces the model family that brief missed.

In models mode, add MTEB for embeddings and rerankers after a live route check, then add embedding phrasing to the triggers. Add one measured board for current LLMs that passes three tests: keyless public data, terms that allow automated reads, and scores the board measures itself. Candidates to check: HELM, Epoch AI, LiveBench, LMArena. Addresses F22.

### R14. Report deliverable

For a choice between options, the template adds:
- a decision table with options as rows and the brief's criteria as columns, each cell a short value with its claim id, or "unknown" when no claim backs it, unverified cells marked;
- "when another option wins": conditions, each citing claims;
- "what would change this answer": the 1 to 3 central claims the pick rests on most, and the check the user can run.

check.py --kind report checks that every table cell cites a claim or says unknown. A landscape or standards report gets a table of entities by key questions instead. The independent-viewpoint researcher (critics, failure reports, independent measurements) becomes the default for every choice, not only for questions already known to be contested (report.md:9), at the cost of one more agent call. Addresses F24.

### R15. Triggers and routing

Keep one router skill (D1, plan:654). Replace the 600-character test on the description (tests/test_plugin.py:133) with a cap of about 1,000 characters on description plus when_to_use. Move English triggers for each mode, and situational phrasing, into when_to_use. Add a docs trigger and narrow "one-fact lookups" to facts that need no check against a primary source. Separate "보고서로 정리해줘" from summarizing a document already in hand. Add only the phrases that raise recall in R1's routing set while the near misses stay quiet. Docs skips the earlier-topic grep and the ~/research lookup. Amends B.12 item 2 (plan:523). Addresses F4, F32.

Rejected: a separate docs skill (one more listing entry in every session and a competing trigger, while the router picked the right mode for 19 of 19 dig, report, pulse and watch prompts, plan:616); the full 1,536 characters.

### R16. Self-improvement loop

The answer to the feedback question on a delivered result is logged verbatim plus a normalized line (feedback: fit=yes|partly|no; missing=...), with no extra question to the user. Each missing item becomes a gold item in R1's sets, and references and defaults change only when an eval run passes its threshold. Knowledge accumulates through the sources index (R9), seeding and the canonical audit (R8). The intake reads the brief and feedback lines of related topics only, found through */map.md. Addresses F25, F26.

Rejected: a cross-topic lessons ledger written by scripts, because it would replay remote text, store private terms, turn one transient error into a rule for a whole host, and reopen the settled "No new file" (plan:332); a host failure cache, to be reconsidered only if walls keep repeating after R18's retry policy.

### R17. Egress policy

Run the hook through a small sh wrapper. It exits 0 at once when no term list exists (no forbidden.txt under HOME or USERPROFILE, no .phro/project.json from the working folder upward), so Python starts only where protection is promised. Otherwise it tries py -3, python3 and python in turn and exits 2 with a repair hint when none runs. No global onFailure. watch.py check re-checks the terms before each feed request (B3). Ad hoc curl from the main session is accepted as a known gap; R3 closes the hole on the research path. Add a test that runs the hooks.json command itself with no Python on PATH, with and without a list. Addresses F41, F42.

Rejected: a global "onFailure": "block" (F41); scanning Bash and PowerShell commands in the hook, which would start a process on every Bash call in every session and block local commands that name a listed term, which tests/test_egress.py:94-99 lets through by design.

### R18. Scripts and install

- One retry and timeout policy in every HTTP helper: retry 429, 5xx and timeouts after 2, 4 and 8 s, with Retry-After capped at 60 s, under one run deadline. GitHub's rate-limit 403 is not retried, and a bot-check 403 or 503 stays a wall. Addresses F7.
- README: requirements, a per-OS install hint inside each "missing tool" FAIL line, how to create the term list, an example allow rule for the scripts, and the note on blocking waits (R2). Addresses F38.
- SKILL.md says python3 outside Windows, and the references use the scripts path that SKILL.md gives. Addresses F6, F39.

Rejected: a doctor.py preflight, a second copy of the requirements that drifts (the plan already left out last30days' doctor, plan:108); a shared module imported through sys.path.insert, since a file named like a stdlib module could shadow it. If shared code is ever wanted, load it by path with importlib as tests/_load.py does, keep the egress guard standalone, and do it after the research fixes.

## 4. Backlog

Ordered by effect on research outcomes. Land each item with a failing test first. Bug labels from the review: B1 quoted ~ paths, B2 PDFs without pdftotext, B3 watch check egress, B4 commas in chain find titles, B5 models.py deadline and tracebacks, B6 non-atomic writes, B7 lane errors without messages, B8 fetch name reuse, B9 watch exit codes.

1. PDF reading-order text, layout copy, arXiv HTML first; closes B2 (R9; F9, F16).
2. OpenAlex: title normalization (B4), fields and flags, chain.py oa, DOI to open-access copies, recent cites, optional key, an OpenAlex source kind in watch (R9; F8, F15).
3. Evidence base: sources/index.tsv, URL reuse (B8), dates and versions, vote check dates, per-report views (R9, R10; F2, F20, F34).
4. Rounds that survive background subagents, and the re-read after compaction (R2; F1).
5. Support pass and verifier start points (R5, R6; F17, F18).
6. Agents for tool isolation, the main session writing every file, the docs gate (R3; F3, F4, F43).
7. chain.py topic and related, the canonical audit, seeding (R8; F14).
8. One retry policy (F7); lane and chain errors keep their message (B7, F12); a models.py deadline and FAIL lines instead of tracebacks (B5, F10).
9. Report template: decision table, flip conditions, critics by default (R14; F24).
10. Disconfirm searcher (R7; F19).
11. hf lane, MTEB, a measured board for current LLMs (R13; F22).
12. Standards section (R11; F21); Wayback for dead public pages (R9).
13. Safety: egress in watch check (B3, F42); the hook wrapper (R17, F41); ~ expansion at every entry point (B1, F37); quote lines normalize no-break spaces and soft hyphens instead of failing (F44).
14. Tokens: above about 20 new items watch prints a numbered index with the full lines in watch/<stamp>.md (F29); formats.md blocks for single modes move into their mode references (F30); the check loop works on a saved file and edits only the flagged spans (F31); the intake grep reads related topics only (F26); the plan line becomes a literal, language-neutral first line at the spawn step, followed by 3 reruns of the Korean report prompt (F5).
15. Triggers (R15; F32), once the routing set exists.
16. Atomic writes in models.py (B6, F11); watch exit codes documented (B9, F13).
17. README and python3 (R18; F38, F39).

The evals (R1) run alongside the backlog. Build the verifier set and the routing script first, because items 5, 10 and 15 depend on them.

## 5. Plan amendments

- D3 (plan:656): add the keyless hf lane (R13).
- D4 (plan:657): dig gains a support reader that rates and does not vote (R5).
- B.1 principle 13 (plan:262) and B.7 (plan:461-466): tiers set per role and measured; agents grouped by tool set; no subagent writes (R3, R4).
- B.10 (plan:495): restore the term check in watch check; the hook fails closed only where a term list exists (R17).
- B.12 item 2 (plan:523): about 1,000 characters on description plus when_to_use (R15).
- T5.3 (plan:626): rate the 5 real requests on the delivered result as well as the brief, and add interactive dig and report runs (R1).
- T5.6 (plan:646): README requirements and the note on blocking waits before publishing (R2, R18).
- Unchanged: "No new file" for learning from earlier runs (plan:332; R16).

## 6. Open items and assumptions

- Assumed: no institutional access to ISO, IEC or IEEE full texts (R11).
- The subagent_type value for plugin agents is not documented; test it before R3 relies on it.
- Substitution of ${CLAUDE_PLUGIN_ROOT} in files read with Read is not documented (F6); backlog item 17 removes the dependence.
- report.md:80 says Claude Code refuses a subagent's write; this is unconfirmed, and R3 makes it moot.
- OpenAlex's keyless budget: plan:565 measured 1,000 credits a day per IP address, and one OpenAlex docs page suggests a different figure. Check it live when adding the optional key.
- The routes and terms of the measured-board candidates (R13) are not checked yet.
- T5.3's rating of 5 real requests is still open (plan:643).

## Appendix A. Platform facts relied on

Checked in the official Claude Code docs on 2026-11-01.

- A1. Hooks: a PreToolUse exit 2 blocks the call; any other non-zero exit, and a timeout, let it through unless the hook sets "onFailure": "block" (Claude Code 2.1.295 or later). A plugin hook applies in every session where the plugin is enabled, and fires for subagent tool calls too. https://code.claude.com/docs/en/hooks
- A2. Skill listing: description plus when_to_use is truncated at 1,536 characters. https://code.claude.com/docs/en/skills
- A3. Skills: ${CLAUDE_PLUGIN_ROOT}, ${CLAUDE_SKILL_DIR} and ${CLAUDE_PLUGIN_DATA} are substituted in SKILL.md and in allowed-tools rules, and are not exported to the Bash tool. allowed-tools, model and effort last only for the current turn. Hooks declared in a skill stay registered for the rest of the session. https://code.claude.com/docs/en/skills, https://code.claude.com/docs/en/plugins-reference
- A4. Plugin agents: tools is an enforced allowlist; model is a default that a model alias passed per call overrides; permissionMode, hooks and mcpServers are ignored; omitClaudeMd and maxTurns are supported. https://code.claude.com/docs/en/sub-agents, https://code.claude.com/docs/en/plugins/components
- A5. Background subagents keep Write, Bash, WebSearch and WebFetch, and their permission prompts surface in the main session. https://code.claude.com/docs/en/sub-agents
- A6. Fork mode is on by default (in an interactive terminal from 2.1.232, everywhere from 2.1.302): subagents run in the background, and their results arrive as notifications in a later turn. CLAUDE_CODE_FORK_SUBAGENT=0 or CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 make Claude wait. A plugin cannot set them: plugin settings accept only agent and subagentStatusLine. https://code.claude.com/docs/en/sub-agents, https://code.claude.com/docs/en/env-vars
- A7. A plugin cannot ship permission allow rules. https://code.claude.com/docs/en/plugins-reference

## Appendix B. How the first-round recommendations changed

The first round leaned on robustness. Re-judged against research outcomes:
- Kept: one router skill, with new reasons (R15); the bug list, reordered by research impact (section 4).
- Revised: agent files are for tool isolation, not enforced tiers, because a per-call model overrides an agent file's model (R3, R4); the hook fails closed only where a term list exists, not globally (R17); no doctor, but PDF text became a research-quality fix (R9, R18); outcome evals come before routing evals, and routing runs outside claude plugin eval (R1); one evidence base with views per deliverable instead of per-run versions (R10); one retry policy first, shared code later and by path (R18); watch prints an index instead of a capped list (backlog item 14).
- Withdrawn: the cross-topic lessons ledger (R16); moving theory.md, which nothing loads at runtime.
- Corrected claims: "harness-enforced tiers" was wrong (A4), and the 600-character cap is the owner's rule, not the platform's (A2).
