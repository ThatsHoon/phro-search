# pulse

What communities said, shipped or argued about in the last N days (default 30). `pulse.py` collects keyless lanes (Hacker News, Reddit through arctic-shift, GitHub, arXiv, YouTube through yt-dlp), then scores, merges and clusters the items; this session plans the run, judges the clusters and writes the brief. Engagement shows attention, not truth: a pulse measures opinion, so whatever the brief leans on gets its primary link (repository, paper, release, official post).

## 1. Pre-flight

Check the topic for keyword traps before the first request. Reframe it, or ask one question when the reframing would change what the user gets.
- Numbers that collide: a model size ("4B"), a version ("v2") or a year matches unrelated posts. Pair it with the name it belongs to ("Qwen3 4B"), or keep it in the ranking query only.
- Tutorial phrasing: "how to use X" finds tutorials, not news. Search for X itself and keep the intent in the ranking query.
- A single generic noun ("agents", "memory", "skills"): add the anchor that pins the sense ("Claude Code skills"), or ask which sense.
- A topic not in English: the lanes are English-speaking communities. Search the field's English terms; when the topic lives in another language's communities, say so, run the web supplements in that language, and name the gap.

## 2. Resolve

- Entity: the thing every item must be about, head word first ("DuckDB", "Claude Code"). Items without the head word stay in the results but out of clusters. Leave it out for a field-wide topic.
- Anchors: every subquery carries the term that disambiguates it, as a phrase in `search_query` and in words in `ranking_query`.
- Subreddits: dedicated ones belong to the entity itself; their newest posts in the window are pulled without a query and kept without the relevance floor. Broad ones are where the topic comes up, 2 to 5 of them, including 2 or 3 peer communities of its category. Reddit runs only on the subreddits named.
- `reddit_queries`: 1 to 3, each searched in each subreddit, one slow request apiece. arctic-shift needs every word of a query in the title or body and has no OR or phrases, so each is one or two words that every on-topic post contains (the entity, `mlflow`; the field's key term, `multilingual`), never a whole subquery. Default: the entity, else the first subquery.
- GitHub: the entity's own repositories go in `github_repos` (their issues and releases in the window, kept without the floor); repository and issue search covers the rest.
- YouTube: `youtube_queries` when spoken phrasing differs from the search query (talks, tutorials, reviews); otherwise the subqueries are used.
- When an ambiguity survives (two things share the name, the community is unknown), show the resolved entity, subreddits, repositories and anchors in one round before running.

## 3. Lanes

| Topic | Lanes |
|---|---|
| a tool, library or model release | hn, reddit, github, youtube |
| a research direction | arxiv, hn, reddit, github |
| a product or company | hn, reddit, youtube |
| a practice or workflow | hn, reddit, youtube, github |

Each subquery names its lanes; a lane that no subquery names does not run. TikTok, Instagram and X have no keyless access: when a topic lives there (consumer products, creators), say so in the gaps instead of guessing.

## 4. Plan and run

Write `<topic>/pulse/plan.json` (format in `references/formats.md`; each result keeps a copy, so a rerun may overwrite the plan):
- 1 to 4 subqueries, the first one the topic itself. `search_query` is keywords, with no dates and no meta words ("news", "update", "latest"). `ranking_query` says in words what an on-topic item is about. `weight`: 1.0 for the primary subquery, 0.6 to 0.8 secondary, 0.3 to 0.5 peripheral.
- `freshness`: `strict` for breaking news, `balanced` by default, `evergreen` for slow fields where a month-old post still matters.

Plan line: "pulse: <lanes>, <N> days, up to 90 s, 2 or 3 web supplements".

Run `python -I ${CLAUDE_PLUGIN_ROOT}/scripts/pulse.py <topic_dir> --plan <topic_dir>/pulse/plan.json`. `--days N` overrides the plan's window; `--quick` and `--deep` cluster 15 or 60 items instead of 40. It prints a LANE line per lane, the clusters over the floor with their best items, the weak signals, then the result and evidence paths. Lane statuses:
- `ok`; `no-results` (fetched, none on topic); `partial` (some requests failed);
- `rate-limited` (GitHub allows 10 searches a minute without `GH_TOKEN`); `timeout` (cut at the deadline, what came in is kept);
- `failed: <reason>`; `skipped` (no subreddits named, or yt-dlp missing).

Exit 1 means no lane returned anything: say so, with each lane's reason, and stop.

## 5. Web supplements

2 or 3 standard web searches for what the lanes miss: release notes, official blogs, documentation changes, news in the window (not Reddit or X). Generic queries with the anchor. They give context and primary links, cited as links and never quoted: the brief quotes only what `pulse.py` collected.

## 6. Judge

Read the clusters in the evidence file (`grep -n "^### \|^- \|comment by" <topic>/pulse/<stem>-evidence.md`), then what the brief needs in full.
- One story split over two clusters: treat them as one. A cluster mixing stories: split it. A cluster about another sense of the name: drop it, and say so when it was large.
- Strength: the lanes it spans, its engagement against its lane, how recent it is, and whether a primary link stands behind it. A `single-lane` or `thin` cluster is reported as such.
- 3 to 6 clusters make the brief. "Nothing solid came up in the window" is a valid answer; the weak signals then become a short list.
- An absence is scoped to what was searched: "the lanes showed no new model under 2B", never "no model shipped"; the lanes see only posts that use the query's words.

## 7. Brief

Write `<topic>/pulse/<stem>.md` (the stem of the result, such as `2026-10-30`) in the user's language, headings and labels included; quotes stay in their own language.

```
# <topic>: <N> days to <as-of date>
<one-line takeaway>

<coverage line: every lane the run listed, by name (Hacker News, Reddit, GitHub, arXiv, YouTube), with what it returned: a count, or its status and reason>

## <a heading that states what changed>
<what changed and how strong: lanes, engagement, dates; the primary link>

> <a title, snippet or comment from the evidence file, copied exactly>

<author, lane: the link to that item or comment>

## <gaps>
<lanes that failed or were skipped, communities the lanes cannot see, what the web supplements found that the communities did not>

## <next>
<a drill into one cluster, or the dig or report that would answer what the pulse cannot>
```

- At least one quote per cluster, copied exactly (whitespace may differ; "..." joins pieces kept in order). Its author, lane and link go on the line after it, with a translation when the quote is not in the user's language.
- A failed, partial, rate-limited or skipped lane is named on the coverage line with its reason; it is never reported as silence.
- Prose, no tool narration; numbers as the lanes gave them ("412 points, 230 comments").
- Run `check.py --kind pulse <topic>/pulse/<stem>.md` and rewrite only the flagged spots until it prints OK.

## 8. Deliver

In the user's language, with no lead-in: the takeaway, each cluster's heading with its strength in a few words, the coverage line, the web supplements' links, the brief path and the feedback question. Write that whole reply, run `check.py -` on it and send exactly the text that printed OK; a change after the check needs a new check. Log the run and the answer verbatim (`references/formats.md`).

## Drill and hand-off

- "Drill into <cluster>": a new pulse on that cluster alone, its terms as subqueries, its subreddits and repositories named, with `--deep`. Each run gets its own stem; earlier runs are never overwritten.
- To dig: when the user wants the originals behind a cluster or the field's background, hand the brief to dig with the cluster's primary links (repositories, papers, releases) as the first sources, and ask only what changes.
- To report: when the user must decide between options the pulse surfaced.
