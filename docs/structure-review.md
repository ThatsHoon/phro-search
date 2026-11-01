# phro-search structure review

Date: 2026-11-01. Base: commit d233fd6 (main). The owner confirmed the decisions in section 3 and the backlog list in section 5 on 2026-11-01, over two rounds of questions and a final confirmation of the summary, after sending a first round back for rethinking. After the first version of this document, the owner also accepted the 18 details in section 4 and re-confirmed two decisions that rested on corrected facts (R1's eval environment, R17's Windows shell). Text marked "consequence" follows directly from the decisions; section 7 lists what is still unknown. This review changed no plugin code.

Method: a full read of the manifest, skill, references, hook, scripts, tests, evals and plan; script audits with the unit tests run (216 pass); an adversarial check of each finding against the code; checks of Claude Code platform behavior in the official docs (appendix A); then grilling over a design tree, one round per frontier, until no decision was open; then a citation check of this document.

Every decision is ranked the same way: research outcome quality first (the right and original sources, recall of canonical work, correct and verified claims, decision-useful deliverables, fit to the need), then cost and latency, then robustness and hygiene.

## 1. Summary

Sound today:
- One router skill that loads one mode reference per run, and stdlib scripts for the mechanical work (SKILL.md:10-21, 56-66).
- Strong evidence discipline: archived originals, quotes checked against their lines (report.py:202-221), three adversarial votes per central claim, and unverified kept apart from refuted (report.md:76; report.py:158-160).
- Tests keep the docs and the code in sync (tests/test_plugin.py), and 216 unit tests pass on a fake network.
- Honest coverage: failed lanes are named with their reason, never passed off as silence, and walled items go to the user with their URL (pulse.md:86; dig.md:69).

Largest problems, all verified:
1. Rounds assume blocking waits, but interactive sessions do not wait for subagents by default, and the interactive path for dig and report is untested (F1).
2. Dig and report overwrite each other's evidence files in one topic folder (F2).
3. pdftotext -layout puts both columns of a two-column paper on one line, which breaks quote location (F16).
4. A located quote is not a supporting quote, and nothing checks support (F17).
5. Round 0 has no bibliographic method, so the saturation stop measures one search engine (F14).
6. OpenAlex data on legal copies, retractions and versions is thrown away, while walls are the main reason digs fall short (F15).
7. No fetched source, claim or vote carries a date or version (F20).
8. No eval measures research outcomes (F27).
9. Pulse has no Hugging Face lane, though model topics are a core class of the owner's research (F22).
10. Subagents get every tool, Bash included, and every CLAUDE.md (F43, F33).

Highest-value changes: measure outcomes first (R1), make rounds survive background subagents (R2), fix PDF text and OpenAlex use (R9), keep one evidence base with a view per deliverable (R10), add the support pass (R5), isolate subagent tools (R3).

## 2. Findings by lens

Impact is the effect on research outcomes unless marked otherwise. "plan:N" is a line of docs/plans/2026-10-30-phro-search.md.

### 2.1 Flow and hand-off contracts

- F1. Dig and report say "wait for both" and "wait for every reply" (dig.md:18, 45; report.md:23, 61). In interactive sessions fork mode is on by default: subagents run in the background, Claude does not block on them, and their results arrive as notifications in later turns; in claude -p Claude can wait (appendix A6). A round can close, or saturation be counted, before every searcher has reported. The only acceptance run of dig whose mode is recorded ran headless (plan:620-621), and T1.8 and T2.4 do not record how they ran (plan:571, 578), so the interactive path for dig and report is untested. Impact: high.
- F2. Dig and report write the same extracts.json and report.html in one topic folder (SKILL.md:54; dig.md:58; report.md:57, 99), and report.md:105-107 encourages a report on a dug topic. report.py requires every central claim to be located in that single extracts.json (report.py:165-174), so a dig after a report fails --check, and a second report trips the 10-central cap (report.py:169-170). Impact: high.
- F3. Researchers write their own notes (report.md:26) and the docs agent writes a note and runs Bash (docs.md:27, 38), so briefs carry local paths against SKILL.md:70 (plan:624). report.md:80 says Claude Code refuses a subagent's report write; the docs do not say so (appendix A5). Impact: medium.
- F4. Docs mode names the note path in its plan line (docs.md:9) but never gates it, and flags a defaulted path only in the reply (docs.md:8). It keeps no log (docs.md:47), yet still passes through the earlier-topic grep and the topic lookup (SKILL.md:27, 48). Impact: medium.
- F5. The plan line before the first spend held in 8 of 11 headless runs; the Korean formalized report prompt failed 3 of 3, with the plan only in thinking (SKILL.md:49; plan:641). Impact: low for outcomes, medium for trust.
- F6. Mode references spell script paths as ${CLAUDE_PLUGIN_ROOT}/scripts/... (models.md:48-60, 114; pulse.md:42). The docs say the variable is substituted in skill, command and agent content; they do not say whether a file the skill loads with Read is covered (appendix A3). Impact: low.

### 2.2 Error and exception handling

- F7. The retry policies differ. Only models.py retries 5xx and timeouts (models.py:202-241); fetch.py, chain.py and watch.py retry 429 only (fetch.py:154; chain.py:135; watch.py:117); pulse.py retries 429 and arctic-shift's 422 but not 500 (pulse.py:143), although arctic-shift returns 500 for uncached queries (plan:670). Transient errors become lost lanes and failed fetches. Impact: medium.
- F8. chain.py find sends a title raw into the OpenAlex title.search filter, so a comma breaks the filter; a test pins this (chain.py:207-210; tests/test_chain.py:170-172). Impact: medium.
- F9. Without pdftotext every PDF fails, arXiv included, before the arXiv HTML fallback runs (fetch.py:349-351, 372-376, 470-473). Impact: high on machines without poppler.
- F10. models.py has no overall deadline (60 s per request with retries, over 40 requests), and main catches only Usage, Drift, Fail and ValueError, so an unexpected response shape prints a traceback (models.py:202-241, 985-997). Impact: low.
- F11. Non-atomic writes in models.py stick: a truncated snapshot becomes the day's KEPT baseline, a truncated card is never fetched again, and a truncated facts cache fails later shortlists (models.py:516, 610, 896). Impact: low.
- F12. Pulse lane exceptions keep only the type name (pulse.py:417-418). Impact: low.
- F13. watch.py check exits 0 when only some feeds failed (watch.py:399); watch.md does not say so. Impact: low.

### 2.3 Domain knowledge

- F14. Round 0 runs two web searchers on the same engine (briefs.md:10; dig.md:16). Their overlap drives the 70 percent stop (dig.md:17, 49), although theory.md:88 grants that they are not independent samples. Sorting by citations puts originals ahead of commentaries, as the trial runs found for title search (theory.md:115), but chain.py offers only that title lookup and no topic query (chain.py:207-210), and nothing checks the map against the field's most cited works. Impact: high.
- F15. chain.py requests only best_oa_location and open_access and prints one URL (chain.py:39, 165-170): no repository copies, version, work type, venue or retraction flag. fetch.py fetches a DOI at the publisher as given (fetch.py:474). Walls stopped 2 of 5 earlier topics and left two T1.8 claims partial (plan:179, 571). Impact: high.
- F16. pdftotext runs with -layout (fetch.py:353), which mixes the columns of a two-column page on one line (dig.md:41; formats.md:92). Quotes that span lines and words hyphenated at a line end then fail the check (report.py:213-221), and a finding without a located quote can never be central (report.md:54). Impact: high.
- F17. report.py proves that a quote sits near a line, not that it supports the claim (report.py:202-221). In dig, the agent that located the quote also sets the claim's status (dig.md:58); T1.8 needed a rerun to correct a stop note that called partial claims sourced (plan:571). In report, verifiers check quote fidelity with web tools only and two lines either side (report.md:64, 68). Impact: high.
- F18. All three verifiers share one brief and one model (report.md:3, 61), unsure means refuted (report.md:71), and two refutations kill a claim (report.md:76). Their errors correlate: in T2.4 one brief added a ratio, and the votes refuted that ratio (plan:578). Impact: medium.
- F19. No method looks for counter-evidence on purpose (briefs.md:14), although at least half of dig's required claims must need the originals, typically how well a method works or where it fails (intake.md:122). Impact: medium.
- F20. fetch.py keeps only the title and body and does not store the extraction path it prints (fetch.py:334-344, 500); the sources table has no date column (formats.md:23); reused votes never expire (report.md:107). Models-mode snapshots and cards are the exception: they carry a date or a repo sha (formats.md:146, 149). Impact: high in fast fields.
- F21. Standards are one of the owner's topic classes (plan:178), but edition, status, errata and normative text are not handled (formats.md:39-46). Impact: medium.
- F22. Pulse has no Hugging Face lane (pulse.py:32), and a T3.5 brief wrongly said no notable model had shipped (plan:586). In models mode, current LLMs have only Hub leaderboards, mostly self-reported, and no board that measures them itself (models.md:34-36); for embeddings there is no general board such as MTEB, only the reasoning-retrieval board mteb/BRIGHT (models.md:38). The embedding prompt went to another skill in 3 of 3 runs (plan:618). Impact: high for model topics.
- F23. The intake's default scope is English plus the user's language (intake.md:65; dig.md:16), but pulse has no Korean lane and may not quote web supplements (pulse.md:51; check.py:16-18). Impact: low for this owner (R12).
- F24. The report template has no table of options by criteria, no conditions under which another option wins, and no list of the claims the pick rests on (report.md:83-89). For a choice between options, critics join only when the question is known to be contested (report.md:9, 14). T2.4's added value was exactly such a condition (plan:578). Impact: medium.

### 2.4 Self-correction

- F25. Learning is recall of the user's preferences: the intake greps the brief and feedback lines of earlier topics (SKILL.md:27; intake.md:26). Process failures are logged per topic (formats.md:68, 75) but never aggregated; docs keeps no log (docs.md:47), watch has no log step, and the feedback answer is free text that cannot be counted (SKILL.md:77). Impact: medium.
- F26. The intake grep reads every brief and feedback line of every topic. At about 25 runs a month (plan:178) it passes the Grep tool's default limit of 250 lines in roughly 5 months (an estimate). Impact: low now.
- F27. Nothing in tests/ or evals/ measures recall, claim correctness or verifier accuracy. All 15 intake cases grade process; even form-en-adam, which names its gold papers, is graded only on asking no questions (evals/intake/form-en-adam/case.yaml:12-25). The searcher tier, the 2-searcher cap (dig.md:77), the round-0 method and the vote rule have no numbers behind them, and T5.3's rating of 5 real requests is still open (plan:643). Impact: high.

### 2.5 Token and context efficiency

- F28. Model placement is prose. "Light model tier" names no model (briefs.md:7; dig.md:12), other roles say "mid model (sonnet)" (report.md:3; docs.md:14), and spawn lines in the log record no model (formats.md:66). The work left to models is judgment, since the mechanical work is already scripted. Impact: medium.
- F29. watch.py check prints every new item (watch.py:372-375), 215 lines of strangers' text in T5.2 (plan:623), and watch.md:26 filters only at delivery. Impact: low; also an injection surface.
- F30. formats.md (about 11 KB, every mode) loads whenever a working file is written (SKILL.md:50). Impact: low.
- F31. Pulse and models run check.py on the whole reply through standard input on every pass (pulse.md:92; models.md:114; SKILL.md:76); dig.md:73 already allows a saved file. Impact: low.
- F32. The 600-character cap is the owner's rule, not the platform's (tests/test_plugin.py:133; plan:523); the platform truncates description plus when_to_use at 1,536 characters (appendix A2). Vague prompts fired no skill in 2 of 3 first-pass runs (plan:627), and "best model for" is the only English trigger (SKILL.md:3). Precision is good: 12 of 12 out-of-scope runs stayed quiet (plan:618). Impact: medium.
- F33. Subagents load every CLAUDE.md unless their agent file sets omitClaudeMd (appendix A4). Impact: low; also privacy.

### 2.6 Reuse

- F34. fetch.py refuses an existing name and keeps no URL index, so "never download again" (report.md:51) depends on the model (fetch.py:483-485). Impact: medium (cost).
- F35. Five scripts carry their own HTTP helper, and the helpers behave differently; the SHARED test guards only the egress, clean and NAMES copies (tests/test_plugin.py:15-17). B3 is a separate gap: watch.py's check command has lacked the term check since 0.1.0 (watch.py:336-352). Impact: low.
- F36. chain.py caches nothing, and a title search costs OpenAlex credits each time (dig.md:36; plan:565). Impact: low.

### 2.7 Install and config robustness

- F37. Quoted ~ paths are not expanded: fetch.py and models.py write silently into a literal ~ folder, and report.py and check.py fail (fetch.py:505; models.py:974; report.py:300; check.py:260). Impact: medium on Windows.
- F38. README.md lists no requirements (Python 3.10+, Git Bash on Windows, poppler, tesseract and pdftoppm, yt-dlp), no setup for the term list and no example allow rule (README.md:7-27). Impact: medium for publication (T5.6).
- F39. SKILL.md:58 calls python; stock macOS and many Linux systems have only python3, which the hook already handles (hooks/hooks.json:9). Impact: low.
- F40. claude plugin eval refuses Bash and Write grants on native Windows, so no mode can start inside its sandbox (plan:628), and it drops the competing skills a routing test must beat (plan:615). Headless claude -p in the owner's environment did run scripts and write files (T5.2, plan:620-623). Impact: shapes how evals run (R1).

### 2.8 Safety boundaries

- F41. On POSIX systems and on Windows with Git Bash, the egress hook fails open when its interpreter cannot start (a missing python, or the Windows Store stub, exits 127 or 9009) or when its 10 s timeout fires, because only exit 2 blocks (hooks/hooks.json:9-10; hooks/egress.py:1-2, 50-71; appendix A1). On Windows without Git Bash, Claude Code runs a shell-form command through PowerShell and treats a failure as a block (appendix A1); the POSIX syntax of hooks/hooks.json:9 would fail there, so every WebSearch and WebFetch would be blocked in every session (inferred from the docs, not tested). A global onFailure block would cut all web access for installs with no term list, since a plugin hook runs in every session where the plugin is enabled and no list passes by design (plan:569). Impact: safety, and an outage risk on Windows without Git Bash.
- F42. watch.py check sends stored feed URLs with no term check, unlike add (watch.py:298-303, 336-352), against the plan's rule that every network script checks terms (plan:495). Impact: safety.
- F43. Subagents get the full tool set, so a web-reading agent can use curl, which the WebSearch|WebFetch matcher never sees (hooks/hooks.json:5), and an injected page could steer it to local files; SKILL.md:71 is only a prompt rule. Impact: safety.
- F44. check.py's invisible-character rule applies to quote lines too (check.py:8), so a quote holding a no-break space or a soft hyphen fails; in T1.8 such a quote was dropped to pass the check (plan:571). Impact: medium (evidence integrity).

## 3. Decisions

Confirmed by the owner. "Rejected" lists the options considered and turned down, with the reason.

### R1. Measure outcomes before changing defaults

Build three eval sets, and change a default only on their numbers:
- Verifier set: 20 to 30 planted claims made from T2.4's claims.json (overstated, outdated, contradicted and true variants), 3 votes each. Score false refutations and false survivals.
- Round-0 recall: the owner marks the canonical works in 2 or 3 closed topics. Run round 0 only and compare haiku against sonnet searchers (3 repeats, R4), and two web searchers against one web searcher plus the citation list (R8). Score gold recall, the share of searcher URLs that fetch.py archives as the original itself (not a dead page, a wall or a summary), and the overlap numbers.
- Routing: the 34 T5.1 prompts plus near misses ("보고서로 정리해줘" about a document in hand, a scikit-learn "best model for", "새 글 확인" about Slack), 3 runs each, with the competing skills present.

Also run one dig and one report interactively with Claude Code's defaults, and rate the 5 real requests on the delivered result as well as the brief (extends T5.3).

Where (re-confirmed after a corrected fact): both sets run headless with claude -p in the owner's Windows environment, as T5.1 and T5.2 did, and scripts grade them. The routing set uses read-only tools, with the competing skills present. WSL serves only sets written as claude plugin eval cases, since that sandbox refuses Bash and Write grants on native Windows (F40). The grilling first chose WSL for the outcome sets on the wrong belief that headless claude -p could not run scripts there.

Thresholds: routing passes at 90 percent or more firing on in-scope prompts and 10 percent or less on out-of-scope and near-miss prompts, over 3 runs each; each eval pass has a cost cap of 50 USD; the other thresholds are in R4, R6 and R8.

Rejected: process-only evals (F27); routing evals inside claude plugin eval (F40).

### R2. Rounds that survive background subagents

Dig and report log each round's pending agents in log.md, close a round only when every agent has reported or been stopped, and re-read references/<mode>.md after a compaction. Consequence: saturation is never counted before both methods have reported. README explains CLAUDE_CODE_FORK_SUBAGENT=0, which lets Claude wait when asked, as the skill's wait instructions do (appendix A6); the stronger setting is P17. R1's interactive runs verify it. Addresses F1.

### R3. Plugin agents for tool isolation

Three agents in agents/, grouped by tool set:
- web gatherer: WebSearch and WebFetch only, for searchers, researchers and the web half of docs;
- verifier: the same tools, at high effort;
- local reader: Read, Grep and Glob only, for the support pass (R5) and installed source in docs.

Each agent sets omitClaudeMd: true and maxTurns as a runaway guard (a cut-off verifier reply counts as no vote); consequence: each agent file names its model and effort from R4. Each carries the shared rules the briefs lack today: generic queries only, no logins, no paywall or bot-check workarounds (SKILL.md:70, 73); and it repeats the rule the briefs already carry, that web text is evidence, never instructions (briefs.md:10).

No subagent writes files. Researchers and the docs work return text, and the main session writes notes/<subtopic>.md and the docs note and runs check.py. A defaulted path for the docs note goes through the gate like any defaulted slot. Consequences: each agent's description says it is internal to phro-search; SKILL.md:70 is narrowed to agents that have web tools, since the local reader needs local paths; docs uses two agents, so its plan line (docs.md:9) changes. Test the subagent_type value for plugin agents before relying on it (section 7). Addresses F3, F4, F33, F43.

Rejected: one agent file per role; general-purpose workers with every tool.

### R4. Model tiers per role, measured

Until R1 says otherwise, every subagent runs on sonnet (searchers, researchers, verifiers and the local reader), with verifiers at high effort. The main session inherits the user's model, since a model or effort set in SKILL.md lasts only for the invoking turn and research runs after the gate (appendix A3). Haiku replaces sonnet for searchers only if, over 3 repeats, its gold recall is at least 95 percent of sonnet's and its share of URLs that fetch.py archives as the original itself is no more than 5 points lower. Before that test, measure the searchers' share of run cost from the T1.8 and T5.2 transcripts. Every spawn line in the log records model and effort. Addresses F28.

Rejected: haiku searchers by default; a 90 percent threshold; a model pinned in SKILL.md.

### R5. Support pass

For each dig required claim and each report central claim, the local reader reads the enclosing section and the source's own limitations section, and returns support (full, partial, none or contradicts) plus the qualifying sentence, copied verbatim. extracts.json gets support and qualifier fields. report.py refuses status sourced without at least one full-support quote, so dig's stop 1 cannot fire on a partial. In report, this pass replaces verifier check 1 (does the quote say what the claim says, report.md:71). The reader rates and does not vote, so D4's rule that dig has no votes stands; D4's text gains the reader (section 6). Addresses F17.

### R6. Verifier design

- Every verifier keeps the remaining check list (checks 2 to 5 of report.md:71, since R5 takes over check 1) and varies only where it starts searching: counter-evidence; source standing and date; benchmark and marketing.
- "If you are unsure, the claim is refuted" (report.md:71) becomes "refuted needs a stated reason from the check list; could not check is no vote" only if the verifier set shows more than 10 percent false refutations of true claims.

Addresses F18.

Rejected: identical briefs; distinct roles that each check one lens, because a flaw that only one role checks gets one refutation and survives the 2-refutation rule (report.md:76).

### R7. Disconfirm searcher in dig

When a required claim asks how well a method works or where it fails, run one disconfirm searcher in round 1 (criticism, failed or partial replications, negative results, errata). It is judged by its own claims like a hypothesis branch and left out of the overlap count (dig.md:49; briefs.md:31). The searcher ceiling rises from 8 to 9 or 10 calls (dig.md:12). Addresses F19.

Rejected: a disconfirm searcher in every dig; none.

### R8. Round 0 with a bibliographic method

Add chain.py topic '<anchor terms>', an OpenAlex search sorted by citations.

In fields with papers, round 0 becomes one English web searcher plus the citation list, and saturation is counted between the two. A Korean searcher joins only for Korea-specific topics (R12). Fields without papers keep two web searchers (term search; surveys and textbooks). The switch waits for R1 and ships if the pair's gold recall is at least that of two web searchers.

Ships now, without the test: a canonical audit before delivery (each of the top 20 works for the confirmed terms is in the map, out of scope with a one-line reason, or missing and sent to Next leads; log "audit: k of 20" as the run's recall estimate), and seeding from earlier topics' Sources rows, shown as "from earlier topic X" and never applied unseen. Addresses F14.

Rejected: two web searchers with the citation list as an uncounted reference; no change.

### R9. Sources: PDF text, OpenAlex, provenance, Wayback

- PDF text: write pdftotext's reading-order output as <name>.txt, the file to grep and quote, and the -layout output as <name>.layout.txt for tables. For arXiv, try the HTML version first and fall back to the PDF on any failure (404, a conversion notice, too short). Before switching, measure on the earlier topics' PDFs: hyphen-split line ends, quotes that needed ellipses, table rows kept intact. Addresses F9, F16.
- OpenAlex: fix B4 by normalizing titles before title.search (consequence: commas and pipes become spaces, a leading ! is dropped, standalone AND, OR and NOT are lowercased, so the filter syntax cannot break) and flip tests/test_chain.py:170-172. Add type, venue, publication date, is_retracted and locations to FIELDS (consequence: a flags column). chain.py oa <DOI or W id> lists the legal open-access locations in order of preference. Given a DOI, fetch.py tries those copies before the publisher. cites gets --sort recent. An optional OPENALEX_API_KEY comes from the environment and is never printed. Addresses F8, F15.
- Provenance: fetch.py writes one row per source to sources/index.tsv with the URL, the dates (consequence: final URL, fetched_at, and the page's published and modified dates where it states them), the extraction path and the open-access version. It reuses a source already fetched from the same URL and refuses a taken name with a different URL (B8). Votes carry their check date. Addresses F20, F34.
- Wayback: snapshots only for dead public pages (404, 410, DNS, TLS, timeout), marked as archived copies with their date; never for 401, 403, 451 or wall pages.

Rejected: a hard pdftotext dependency; DOIs fetched only at the publisher.

### R10. One evidence base, one view per deliverable

The topic keeps one growing evidence base: sources/, sources/index.tsv and claims.json. Each deliverable gets its own view: dig keeps extracts.json and report.html; each report writes extracts-<stem>.json and evidence-<stem>.html, with the existing stem rule (the date, then -2 and on). Consequence: report.py <topic> [<stem>] checks quotes, locations and the 10-central cap only for the claims that view cites. Addresses F2.

Rejected: one folder per run (it breaks report.html's relative sources/ links and vote reuse); file names versioned by date only (same-day runs collide).

### R11. Standards

Families: robotics and mapping (OGC, ISO/TC 211 and TC 204, ASAM OpenDRIVE and OpenSCENARIO, ROS REPs), plus IETF and W3C. The reference names each family's own index (RFC obsoleted-by, W3C status, ISO edition and withdrawal), and edition and status are taken from it before quoting. A superseded or draft text never backs a central claim about current requirements. The owner has no institutional access to ISO, IEC or IEEE full texts (confirmed), so their catalog pages are cited for edition and status, and full texts go to the user's browser path. Addresses F21.

### R12. Korean sources

Korean community and academic sources are secondary and are used only for Korea-specific topics (national standards, market, regulation). intake.md:65 encodes this as a general rule (P18). No Korean-specific adapters; watch already finds feeds through typed alternate links (watch.py:207-225). For a Korea-specific pulse topic, a web supplement may be quoted once fetch.py has archived it and the quote is located in that copy; pulse.md:51 and check.py:16-18 change to allow it. Addresses F23.

Rejected: adapters for GeekNews, velog, Naver blog, KCI or RISS.

### R13. Coverage for model topics

Amend D3 (plan:656): add a keyless hf lane to pulse.py. It collects models created in the window, with likes, downloads and trending score as engagement, and daily papers with their upvotes. Wire it into the lane table (pulse.md:25-30), check.py NAMES and the coverage line. Keep it only if a replay of the T3.5 topic surfaces the model family that brief missed.

In models mode, add MTEB for embeddings and rerankers after a live route check. Add one measured board for current LLMs that passes three tests: keyless public data, terms that allow automated reads, and scores the board measures itself. Candidates to check: HELM, Epoch AI, LiveBench, LMArena. Addresses F22.

### R14. Report deliverable

For a choice between options, the template adds:
- a decision table with options as rows and the brief's criteria as columns (consequence: each cell a short value with its claim id, or "unknown" when no claim backs it, unverified cells marked, and check.py --kind report checks that every cell cites a claim or says unknown);
- "when another option wins": conditions, each citing claims;
- "what would change this answer": the central claims the pick rests on most, and the check the user can run.

The independent-viewpoint researcher (critics, failure reports, independent measurements) becomes the default for every choice, not only for questions already known to be contested (report.md:9), at the cost of one more agent call. Addresses F24.

### R15. Triggers and routing

Keep one router skill (D1, plan:654). Replace the 600-character test on the description (tests/test_plugin.py:133) with a cap of about 1,000 characters on description plus when_to_use. Add only the phrases that raise recall in R1's routing set while the near misses stay quiet; the candidate phrases are P9. Addresses F32.

Rejected: a separate docs skill (one more listing entry in every session and a competing trigger, while the router picked the right mode for 19 of 19 dig, report, pulse and watch prompts, plan:616); the full 1,536 characters.

### R16. Self-improvement loop

The answer to the feedback question on a delivered result is logged verbatim plus a normalized line (feedback: fit=yes|partly|no; missing=...), with no extra question to the user. Each missing item becomes a gold item in R1's sets, and references and defaults change only when an eval run passes its threshold. Knowledge accumulates through the sources index (R9), seeding and the canonical audit (R8). The intake reads the brief and feedback lines of related topics only (consequence: found through */map.md, as routing already does, SKILL.md:48). Addresses F25, F26.

Rejected: a cross-topic lessons ledger written by scripts, because it would replay remote text, store private terms, turn one transient error into a rule for a whole host, and reopen the settled "No new file" (plan:332); a host failure cache, to be reconsidered only if walls keep repeating after the retry policy (R18).

### R17. Egress policy

The hook fails closed only where a term list exists. With no list (no forbidden.txt under HOME or USERPROFILE, no .phro/project.json from the working folder upward) it exits 0 at once, without starting Python. With a list it tries py -3, python3 and python in turn and exits 2 when none runs (consequence: with a repair hint, and a test that runs the hooks.json command itself with no Python on PATH, with and without a list). No global onFailure. watch.py check re-checks the terms before each feed request (B3), restoring the plan's existing rule (plan:495). Ad hoc curl from the main session is accepted as a known gap; R3 closes the hole on the research path. Addresses F41, F42.

Two limits found after the grilling, both settled afterwards: a hook timeout would still let the call through, which P10 closes; and on Windows without Git Bash a POSIX wrapper cannot run and any failure blocks, which would cut web access for users with no list (F41). For the second, README requires Git Bash on Windows (R18), and one check on a machine without Git Bash confirms the inferred behavior and what its error message says.

Rejected: a global "onFailure": "block" (F41); scanning Bash and PowerShell commands in the hook, which would start a process on every Bash call in every session and block local commands that name a listed term, which tests/test_egress.py:94-99 lets through by design.

### R18. Scripts and install

- One retry policy in every HTTP helper: retry 429, 5xx and timeouts with the plan's 2, 4 and 8 s backoff (plan:541); GitHub's rate-limit 403 is not retried and a bot-check 403 stays a wall. Consequence: pulse.py keeps retrying arctic-shift's 422 "slow down" (pulse.py:143). Addresses F7.
- SKILL.md says python3 outside Windows; the references use the scripts path SKILL.md gives; docs takes a fast path that skips the earlier-topic grep and the ~/research lookup, since it keeps no topic (docs.md:47). Addresses F4, F6, F39.
- README: requirements, Git Bash among them on Windows because the hook runs through it (R17), per-OS install hints, how to create the term list, an example allow rule for the scripts, and the note on waits (R2). Addresses F38.

Rejected: a doctor.py preflight, a second copy of the requirements that drifts (the plan already left out last30days' doctor, plan:108).

## 4. Details accepted after the first version

The reviewer proposed these after the grilling, and the owner accepted all 18 on 2026-11-01. They refine the decisions in section 3.

- P1. Verifiers get the located paragraph instead of two lines either side (R5; report.md:68).
- P2. chain.py related <W id> for the neighbors move; a second chain.py topic call with --since for recent leaders; excluding paratext, erratum and editorial types from the topic list (R8).
- P3. Drop the column ellipsis rule (formats.md:92) if the PDF counts support it (R9).
- P4. cites --since; an OpenAlex source kind in watch for journals and proceedings that have no feed, which T5.2's baseline reached and the skill could only list (R9; plan:623).
- P5. A retracted work never backs a required or central claim; a preprint is marked, and the published version is quoted when one exists (R9).
- P6. A reused central vote older than the brief's recency need is verified again (report.md:76 still forbids reruns to rescue a claim); a report's BLUF names its as-of date (R9).
- P7. Each standards quote is marked normative or informative, and RFC errata are checked along with obsoleted-by (R11).
- P8. "What would change this answer" lists 1 to 3 claims; a landscape or standards report gets a table of entities by key questions (R14).
- P9. Trigger candidates for R1's routing set: English triggers per mode and situational phrasing in when_to_use; a docs trigger; narrowing "one-fact lookups" to facts that need no check against a primary source; separating "보고서로 정리해줘" from summarizing a document in hand; embedding phrasing once MTEB exists (R13, R15).
- P10. egress.py enforces its own deadline under the hook's 10 s timeout and exits 2 when it expires, so a slow start blocks instead of passing where a list exists (R17).
- P11. One run deadline across each script's requests (all five helpers already honor Retry-After only up to 60 s); a bot-check 503 treated as a wall like a bot-check 403 (R18).
- P12. A per-OS install hint inside each "missing tool" FAIL line, in addition to the README (R18).
- P13. Shared script code, if it is ever wanted: load it by path with importlib as tests/_load.py does, keep the egress guard standalone (an import failure exits 1, which does not block), and do it after the research fixes (F35).
- P14. Watch prints its numbered index above about 20 new items, the threshold watch.md:26 already uses; the Korean report prompt is rerun 3 times after the plan-line change (section 5, item 14).
- P15. Each backlog item lands with a failing test first.
- P16. Eval sizes: about 12 near misses in the routing set; 3 repeats per arm also for the two-web-searchers comparison (R1).
- P17. README also names CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1, which makes Claude always wait for subagents (appendix A6). It would also make Claude wait for docs mode's background agent, against docs.md:3 and docs.md:44, so README must say so (R2).
- P18. intake.md:65 encodes R12 as a general rule: the user's language joins the default scope only for topics specific to that language's region, for every user and not only Korean ones (R12).

## 5. Backlog

Ordered by effect on research outcomes. The owner confirmed this list in the second round; items without an R in section 3 rest on that confirmation, and section 4 adds the accepted details. Bug labels from the review: B1 quoted ~ paths, B2 PDFs without pdftotext, B3 watch check egress, B4 commas in chain find titles, B5 models.py deadline and tracebacks, B6 non-atomic writes, B7 pulse lane errors without messages, B8 fetch name reuse, B9 watch exit codes.

1. PDF reading-order text, layout copy, arXiv HTML first; closes B2 (R9; F9, F16).
2. OpenAlex: title normalization (B4), fields and flags, chain.py oa, DOI to open-access copies, recent cites, optional key (R9; F8, F15).
3. Evidence base: sources/index.tsv, URL reuse (B8), dates and versions, vote check dates, per-report views (R9, R10; F2, F20, F34).
4. Rounds that survive background subagents, and the re-read after compaction (R2; F1).
5. Support pass and verifier start points (R5, R6; F17, F18).
6. Agents for tool isolation, the main session writing every file, the docs gate and fast path, model and effort on every spawn line, and the searchers' cost share measured (R3, R4, R18; F3, F4, F28, F33, F43).
7. chain.py topic, the canonical audit, seeding (R8; F14).
8. One retry policy (R18; F7); pulse lane errors keep their message (B7, F12); a models.py deadline and FAIL lines instead of tracebacks (B5, F10).
9. Report template: decision table, flip conditions, critics by default (R14; F24).
10. Disconfirm searcher (R7; F19).
11. hf lane, MTEB, a measured board for current LLMs (R13; F22).
12. Standards section (R11; F21); Wayback for dead public pages (R9).
13. Safety: egress in watch check (B3, F42); the hook change with its own deadline (R17, P10, F41) and one check on Windows without Git Bash; ~ expansion at every entry point (B1, F37); quote lines normalize no-break spaces and soft hyphens instead of failing (F44).
14. Tokens: watch prints a numbered index, with the full lines in watch/<stamp>.md (F29); formats.md blocks for single modes move into their mode references (F30); the check loop works on a saved file and edits only the flagged spans (F31); the intake grep reads related topics only (F26); the plan line becomes a literal, language-neutral first line at the spawn step (F5).
15. The normalized feedback line, with missing items fed into the eval sets (R16; F25); quoting archived supplements in Korea-specific pulse topics, and the intake scope rule (R12, P18; F23).
16. Triggers (R15; F32), once the routing set exists.
17. Atomic writes in models.py (B6, F11); watch exit codes documented (B9, F13).
18. README, python3 and the references' scripts path (R18; F6, F38, F39).

The evals (R1) run alongside the backlog. Outcome sets have priority; the routing script is built early only because item 16 waits on it, and item 5's vote-rule switch waits on the verifier set (R6).

## 6. Plan amendments

Confirmed:
- D3 (plan:656): add the keyless hf lane (R13).
- D4 (plan:657): its text gains the support reader, which rates and does not vote; dig still has no votes (R5).
- B.1 principle 13 (plan:262) and B.7 (plan:461-466): tiers set per role and measured; agents grouped by tool set; no subagent writes (R3, R4).
- B.12 item 2 (plan:523): about 1,000 characters on description plus when_to_use (R15).

Consequential, following from the confirmed decisions:
- plan:253 (principle 4) and plan:527 (B.12 item 6): subagents no longer write files; the main session writes the notes (R3).
- plan:272 (the docs row of B.2): docs uses the web gatherer and the local reader instead of one background agent (R3).
- plan:386 (the extracts.json format): support and qualifier fields, and per-report extracts-<stem>.json (R5, R10).
- plan:396: python3 outside Windows (R18).
- plan:400 (the fetch.py row): reading-order text and a layout copy, arXiv HTML first, DOIs to open-access copies, sources/index.tsv and URL reuse (R9).
- plan:410 (the pulse lanes in v1): the hf lane (R13).
- plan:358: the description rule follows B.12 item 2 (R15).
- plan:297 and plan:332: the intake grep reads related topics only; "No new file" stays (R16).
- plan:370-371 and plan:402: per-report views, and report.py <topic> [<stem>] (R10).
- plan:401: chain.py gains topic and oa (R8, R9).
- plan:485: the report template gains the decision table and its two sections (R14).
- plan:400, plan:415 and plan:541: retry 429, 5xx and timeouts, not only 429 (R18).
- plan:495: the hook fails closed only where a term list exists (R17); the term check in watch check restores this line's existing rule.
- T5.3 (plan:626): rate the 5 real requests on the delivered result as well as the brief, and add interactive dig and report runs (R1).
- T5.6 (plan:646): README requirements and the note on waits before publishing (R2, R18).

## 7. Open items

- The subagent_type value for plugin agents is not documented; test it before R3 relies on it.
- Substitution of ${CLAUDE_PLUGIN_ROOT} in files read with Read is not documented (F6); backlog item 18 removes the dependence.
- report.md:80 says Claude Code refuses a subagent's write; this is unconfirmed, and R3 makes it moot.
- OpenAlex's keyless budget: plan:565 measured 1,000 credits a day per IP address, and one OpenAlex docs page suggests a different figure. Check it live when adding the optional key.
- The routes and terms of the measured-board candidates (R13) are not checked yet.
- T5.3's rating of 5 real requests is still open (plan:643).

## Appendix A. Platform facts relied on

Checked in the official Claude Code docs on 2026-11-01.

- A1. Hooks: a PreToolUse exit 2 blocks the call. Any other non-zero exit, and a timeout, let it through unless the hook sets "onFailure": "block" (Claude Code 2.1.295 or later), with two exceptions: on Windows without Git Bash, a shell-form command hook runs through PowerShell, and its failure blocks the call; and valid JSON on standard output can still decide. A plugin hook applies in every session where the plugin is enabled, unless managed settings restrict hooks, and fires for subagent tool calls too. https://code.claude.com/docs/en/hooks, https://code.claude.com/docs/en/plugins-reference
- A2. Skill listing: description plus when_to_use is truncated at 1,536 characters. https://code.claude.com/docs/en/skills
- A3. Skills: ${CLAUDE_PLUGIN_ROOT}, ${CLAUDE_SKILL_DIR} and ${CLAUDE_PLUGIN_DATA} are substituted in skill, command and agent content and in allowed-tools rules; ${CLAUDE_PLUGIN_ROOT} and ${CLAUDE_PLUGIN_DATA} are not present in the environment of Bash tool commands. Whether a file a skill loads with Read is substituted is not documented. allowed-tools, model and effort last only for the current turn. Hooks declared in a skill stay registered for the rest of the session. https://code.claude.com/docs/en/skills, https://code.claude.com/docs/en/plugins-reference, https://code.claude.com/docs/en/plugins/components
- A4. Plugin agents: tools is an enforced allowlist; model is a default that a model alias passed per call overrides; permissionMode, hooks and mcpServers are ignored; omitClaudeMd and maxTurns are supported. https://code.claude.com/docs/en/sub-agents, https://code.claude.com/docs/en/plugins/components
- A5. Background subagents keep Write, Bash, WebSearch and WebFetch, and their permission prompts surface in the main session. https://code.claude.com/docs/en/sub-agents
- A6. Fork mode is on by default (from 2.1.302, and in an interactive terminal session from 2.1.232). In interactive sessions subagents then run in the background, Claude does not block on them, and their results arrive as notifications in a later turn; in claude -p and the Agent SDK, Claude can wait. CLAUDE_CODE_FORK_SUBAGENT=0 lets Claude wait when asked, and CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 makes it wait for subagents before it continues. A plugin cannot set either: plugin settings accept only agent and subagentStatusLine. https://code.claude.com/docs/en/sub-agents, https://code.claude.com/docs/en/env-vars, https://code.claude.com/docs/en/plugins-reference
- A7. A plugin cannot ship permission allow rules. https://code.claude.com/docs/en/plugins-reference

## Appendix B. How the first-round recommendations changed

The first round leaned on robustness. Re-judged against research outcomes:
- Kept: one router skill, with new reasons (R15); the bug list, reordered by research impact (section 5).
- Revised: agent files are for tool isolation, not enforced tiers, because a per-call model overrides an agent file's model (R3, R4); the hook fails closed only where a term list exists, not globally (R17); no doctor, but PDF text became a research-quality fix (R9, R18); outcome evals take priority over routing evals, and routing runs outside claude plugin eval (R1); one evidence base with views per deliverable instead of per-run versions (R10); one retry policy first, shared code later if at all (R18, P13); watch prints an index instead of a capped list (section 5, item 14).
- Withdrawn: the cross-topic lessons ledger (R16); moving theory.md, which nothing loads at runtime.
- Corrected claims: "harness-enforced tiers" was wrong (A4); the 600-character cap is the owner's rule, not the platform's (A2); plan:628's Windows limit concerns the plugin-eval sandbox, not headless claude -p (F40); the hook's failure mode depends on the shell (F41, A1).
