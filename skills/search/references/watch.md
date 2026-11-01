# watch

New posts from the venues a topic already knows (monitoring, Ellis 1987). Feeds, not search: no cost, and the results do not drift. Run only when the user asks; this mode never schedules itself.

## 1. Is there a map?

When `~/research/<topic>/map.md` is missing (for example "what is new in <framework>"):
- In a hurry, the default: add the obvious venues directly (the official blog or release feed, the main tags, well-known personal blogs) and write a minimal map (Brief, Venues, People) to grow later.
- No idea where the field posts: run dig round 0 only to find the venues (`references/dig.md`), then watch.

## 2. Add feeds

Pick venues from the map's Venues and People and add each with `watch.py add <topic_dir> <url> [name]`. It finds the feed and checks that it parses: Qiita tags and users, Zenn topics and users, note users, subreddits (through the arctic-shift API; reddit.com itself is never fetched), YouTube channels and playlists, GitHub releases, blogs with RSS or Atom, and arXiv API queries such as `http://export.arxiv.org/api/query?search_query=all:%22clarifying%20questions%22&sortBy=submittedDate&sortOrder=descending`.
- A journal or proceedings without a feed: `watch.py add <topic_dir> openalex:<source name or S id>` resolves its OpenAlex source; a name that matches several sources fails and lists their S ids, so add the right one by its S id. `check` then lists the works published since the last check, newest first, with the DOI (else the landing page) and the abstract's first sentence as the first line.
- X and pixiv publish no feeds: say in the reply that they cannot be watched.
- Whether a venue has a feed is decided by `watch.py add`, not by a searcher's word: searchers guess feed URLs and have called a working feed missing. A searcher's "no longer updated" is checked against the latest item that `check` prints.

## 3. Check

`watch.py check <topic_dir>` lists what is new since the last check. A feed's first check shows the last 14 days (`--days N` changes that). Each run is saved as `watch/<date-time>.md`; earlier runs are never overwritten.
- Over 20 new items, `check` prints a numbered index instead (`INDEX` lines: number, date, feed, short title). Pick the items the request needs by number, then read only those from the run's file with the Grep tool (pattern `^- <n>\. `, two lines each: the link and the original's first line).
- A quiet feed still shows its latest item whatever its date, so a big post just outside the window stays visible.
- A first check records the items outside its window as seen; to widen the window afterwards, run `watch.py check <topic_dir> --days 30 --fresh`.
- Exit codes: exit 0 when some feeds failed and others answered or were quiet, so read the `FAIL` lines, not only the code; exit 1 when every feed failed. A failed feed was already retried on a 429, a 5xx or a timeout; check it again later rather than at once.

## 4. Deliver

In the user's language, per item: title, date, venue, and the original's first line as a `>` quote. No agent summary and no score: the writer's own first line is the reader's cue.
- Over 20 new items: deliver the ones picked from the index, and say what was left out and where the full list is (`watch/<file>.md`). Picking selects; it never summarizes.
- Quiet feeds' latest items go last, briefly. Failed feeds are listed with their reason; a failed feed is never reported as quiet.
- Download only what the user picks, or what bears on a required claim: `fetch.py <topic>/sources <name> <url>`, then add it to the sources table with its label.
- Run `check.py` on the exact reply after its last edit, then send that text unchanged.

## 5. Back to dig

People, venues or terms that are not in the map but recur among the new items go to Next leads; ask whether to add them as feeds. That is the way back from watching to digging.

## Files

- `watch.tsv`: a header line, then one feed per line: kind, name, feed URL, venue URL, tab-separated.
- `watch-state.json`: the item URLs already seen, per feed.
- `watch/<YYYY-MM-DD-HHMM>.md`: one file per check: the new items numbered newest first (`- <n>. <date> <feed>: [<title>](<url>)`, then the first line as a `>` quote), the quiet feeds' latest items and the failed feeds.
