# theory

Where each rule comes from and how far its source carries it. A source appears here only after its original was read, in the part named; the rest are under "Not read yet" and back no rule on their own. Pages are the original's printed pages unless marked otherwise. Entries are paraphrases: read the page before quoting it, and reread it before changing the rule.

## Intake

### Need levels set the depth (SKILL.md Intake step 2, intake.md section 1)

Taylor, R. S. (1968). Question-negotiation and information seeking in libraries. College & Research Libraries 29(3), 178-194. https://crl.acrl.org/index.php/crl/article/view/12027 (read from the scan at https://distantreader.org/stacks/journals/crl/crl-12027.pdf)
- p.178, p.182: a question passes four levels: the actual but unexpressed need (visceral), a conscious mental description (conscious), a formal statement (formalized), and the question as put to the system (compromised).
- p.182: the levels are convenient points on a continuum that shade into one another, not stages. The table picks the intake depth; it does not classify the user.
- p.183: recasting the need into what the files can deliver is the intermediary's work, and the first question an asker brings is often already compromised. Hence the use question before a request for a means is taken at face value.
- Limit: people asking a librarian; nothing measured.

### Offer options, recommend one (intake.md sections 4 and 6)

Zamani, H., Dumais, S., Craswell, N., Bennett, P., Lueck, G. (2020). Generating clarifying questions for information retrieval. The Web Conference 2020. https://www.microsoft.com/en-us/research/uploads/prod/2020/01/webconf-2020-camera-zamani-et-al.pdf (camera-ready, CC BY 4.0)
- PDF p.1, p.3: the clarifying pane shows a question with candidate answers to click; the user picks instead of phrasing.
- PDF p.4: in a one-week Bing experiment with 2.5 million users per arm, the question with candidate answers drew 48.57% more clickthrough than a static title over the same answers.
- PDF p.5, p.7: the candidates are the query's aspects or intents, mined from query reformulations, and the set should be diverse. Hence candidate briefs differ in object or deliverable, not in wording.
- Limit: a clickthrough gain on a web results page, not a gain in retrieval or answer quality.

### Which question to ask matters most (intake.md sections 5 and 6)

Aliannejadi, M., Zamani, H., Crestani, F., Croft, W. B. (2019). Asking clarifying questions in open-domain information-seeking conversations. SIGIR 2019. https://arxiv.org/abs/1907.06554 (v1 read)
- p.7: offline on Qulac (198 TREC Web Track topics, 762 facets), an oracle that picks the single best clarifying question lifts P@1 from 0.1933 to 0.4986 (+158%), about 2.5 times, and MRR by about 101%.
- p.8: a realistic selector (a query performance prediction baseline) gains about 31% in MRR, far below the oracle.
- The abstract states a larger gain than its own tables; cite the tables.
- Use: one well-chosen question is worth much and a poorly chosen one little. Hence questions are ordered by how much the answer changes the plan, and a slot whose every answer leads to the same plan is not asked.

### The grilling method (SKILL.md Intake steps 5 and 6)

mattpocock-skills 1.3.1, skill grilling, SKILL.md.
- Lines 6 and 26: decisions form a tree; after each round the open frontier is recomputed.
- Lines 8 and 24: number each question and give a recommended answer, worded so that "yes" accepts it.
- Line 28: facts the environment can give are looked up (a subagent may do it), never asked.
- Line 30: nothing is acted on until the user confirms the shared understanding; the session ends when the frontier is empty.
- What this skill adds for research: a probe so that questions can offer real options, candidate briefs, a depth set by the need level, and required claims as the done condition.

## dig

### The question moves; the six moves (dig.md intro and rounds 1 to 4)

Bates, M. J. (1989). The design of browsing and berrypicking techniques for the online search interface. Online Review 13(5), 407-424. https://www.pages.gseis.ucla.edu/faculty/bates/articles/berrypicking.pdf (a reprint paged 195-216; the pages below are the reprint's)
- p.198, p.214: the query keeps shifting as the searcher learns, and what is useful is gathered bit by bit along the way. Hence required claims may be rewritten mid-dig and logged as drift.
- p.201-202: six techniques: footnote chasing, citation searching, journal run, area scanning, subject searches in bibliographies and abstracting and indexing services, author searching. They are the six moves: backward, forward, venue, neighbors, re-search, author.
- p.201: footnote chasing, like the other citation methods, avoids describing the subject at all. Hence "chain when words fail". Only the first two techniques are chaining.

### Search behaviors (round 0, the moves, labels, watch, the evidence page)

Ellis, D. (1987). The derivation of a behavioural model for information retrieval system design. PhD thesis, University of Sheffield. https://etheses.whiterose.ac.uk/id/eprint/2975/1/DX093006.pdf (abstract and pp.71-72 read)
- Abstract, pp.71-72: six generic characteristics: starting, chaining, browsing, differentiating, monitoring, extracting. Round 0 is starting; the moves are chaining and browsing; source labels are differentiating; watch is monitoring; the evidence page is extracting.
- Limit: derived from interviews with academic social scientists.

### No summaries while exploring (dig.md "No summaries")

Kuhlthau, C. C. (1991). Inside the search process: information seeking from the user's perspective. Journal of the American Society for Information Science 42(5), 361-371. https://tefkos.rutgers-sci.domains/Courses/612/Articles/Kuhlthau_Inside_91.pdf
- p.364, p.370: uncertainty and confusion are natural in the early stages, not a sign of failure.
- p.366: in the exploration stage, before a focus forms, detailed note taking may thwart the process by seeking premature closure.
- p.368: once a focus exists (the collection stage), detailed notes on it are appropriate.
- Use: an agent's summary is an early detailed note that closes on the agent's view. The user reads the originals; extracts are written at the end, against claims already set.
- Limit: hedged ("may"); five studies of students and library users.

### Branch before committing (dig.md "Two plausible directions")

Zhou et al. (2026). Explore before committing: hypothesis-guided search for deep research agents. arXiv 2609.01294v1. https://arxiv.org/abs/2609.01294 (abstract and Figure 1 read)
- Abstract: lightweight hypotheses serve as soft hints, are explored in bounded independent branches, and the branches' evidence is compared before committing; reported 46.7 to 60.0 on BC-small with Qwen3.5-122B.
- Limit: a v1 preprint.

### Stop on evidence, not confidence (dig.md stop 1, intake.md section 7)

Roh, Han (2026). HALT: verification-aware stopping for retrieval-augmented search agents. arXiv 2608.02009v3. https://arxiv.org/abs/2608.02009 (abstract read)
- Abstract: stopping is framed as evidence coverage rather than generator confidence: stop once the gathered evidence supports each required claim. A small agent without such a rule ran to its search budget on 78 to 88% of questions.
- Abstract: the claim list must exist first, drafted from the question (deployable) or taken from gold annotations (an upper bound). Hence required claims are drafted in the brief, before round 0.
- Limit: multi-hop question answering benchmarks.

### Two errors (dig.md "Never stop before round 1")

Zhang et al. (2026). To search or not to search: aligning the decision boundary of deep search agents via causal intervention. arXiv 2602.03304v1. https://arxiv.org/abs/2602.03304 (abstract read)
- Abstract: over-search goes on searching when the knowledge is already sufficient; under-search stops early with a wrong answer; both come from a misaligned decision boundary. Hence a stop rule and a floor of one full round.

### Overlap as the fill signal (dig.md round 0 and stop 2)

Kastner, M., Straus, S., Goldsmith, C. H. (2007). Estimating the horizon of articles to decide when to stop searching in systematic reviews. AMIA Annual Symposium Proceedings 2007, 389-393. https://pmc.ncbi.nlm.nih.gov/articles/PMC2655834/
- Methods: capture-recapture estimates the total from the overlap of k independent samples, here searches of 4 bibliographic databases.
- Results and discussion: after all 4 databases the estimate was 1838 articles (95% CI 1749 to 1955) against 1246 found, so the review had captured about 68%. The test was retrospective, on one review.
- Discussion: how close to the estimate is close enough, and the use as a stopping rule, still need study.
- Use: the dig borrows the overlap idea for 2 searchers with different methods. Searchers are not independent samples and 70% is a working threshold, so saturation is a heuristic, logged with its numbers.

### Read unknown terms coarse to fine (briefs.md)

Yokoi, S. (2017). Examine the meaning of unknown terms. Slides, in Japanese. https://speakerdeck.com/eumesy/examine-the-meaning-of-unknown-terms (slide text read)
- Slide 5: sources by grain, coarse to fine: encyclopedia, special dictionary, textbook and lecture notes (OCW, MOOC), survey, original paper and its author's slides. The coarse end is for beginners and settled knowledge.
- Slide 6: knowing nothing, start at the encyclopedia.

## Not read yet

Add a source above only after reading it. Meanwhile the rules named here are working rules.
- Belkin, N. J. (1980). Anomalous states of knowledge as a basis for information retrieval. Canadian Journal of Information Science 5, 133-143. Would back: the asker cannot state what would close a gap in their own knowledge, so the intake offers options and candidate briefs. No reachable copy: the known mirror is deleted; the 1982 companion (doi 10.1108/eb026722) is paywalled.
- Dervin, B., Dewdney, P. (1986). Neutral questioning: a new approach to the reference interview. RQ 25(4), 506-513. Would back: situation, gap and use questions for a visceral need (intake.md section 1). The repository copy needs a login; a course copy is gone.
- Furnas, G. W., Landauer, T. K., Gomez, L. M., Dumais, S. T. (1987). The vocabulary problem in human-system communication. Communications of the ACM 30(11), 964-971. doi 10.1145/32206.32212. Would back: the probe and the vocabulary bridge. The free publisher copy is behind a bot check: open it in a browser, save it, and run `fetch.py` on the saved file. Search snippets put term agreement between two people under 20%; unchecked.
- Pirolli, P., Card, S. (1999). Information foraging. Psychological Review 106(4), 643-675. doi 10.1037/0033-295X.106.4.643. Would back: pick leads by information scent (dig.md rounds 1 to 4). Paywalled, no free copy found. An application to LLM agents, arXiv 2505.09316, is not read either.
- Marchionini, G. (2006). Exploratory search: from finding to understanding. Paywalled.
- Case, D. O., Given, L. M. (2016). Looking for information. A textbook of the field.
- Wilson, T. D. (1999). Models in information behaviour research.
- Booth, A. (2010). How much searching is enough?
- TARCiS (2024). Guidance on citation searching.

## Findings from trial runs (2026-10)

Trials on three topics: a field with many papers, a field with only personal posts, and research on searching itself; plus a watch trial on a web framework.
- Required claims of the form "X exists" were filled in one round, and the run stopped with the request's core unanswered. Hence one claim carries the request's exact condition and at least half need the originals (intake.md section 7).
- 5 of 11 URLs from search results were dead, behind a login, or HTML posing as a PDF. Hence `fetch.py` judges by content and only OK rows enter the sources table.
- Searcher reports rest on result snippets; a described method differed from its original. Hence (unverified) until read.
- OpenAlex full-text search ranks commentaries first; a title search sorted by citations ranks the original first, but a registered title may lack its subtitle. Hence DOI first, and candidates checked by year and title.
- Citation chaining worked on older papers, not on papers about a year old. Hence the OpenAlex lag rule.
- In the field with only personal posts there were no DOIs and nothing to chain. Standard search came back nearly empty and extended search found the posts at once; the key content sat behind logins (X, pixiv, Xiaohongshu). Hence standard search first, deeper search when a needed kind is empty, and walls go to the user.
- A Japanese article of 2,904 characters was real; a 3,000-character floor meant for English papers dropped it. Hence `fetch.py` weighs CJK characters.
- Searchers' "not searched" lists made good leads for the next round.
- Watch: two round-0 searchers took about 2 minutes and found about the venues that adding the obvious ones gave (watch.md section 1).
