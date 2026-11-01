"""Collect what communities said and shipped about a topic in the last N days, from keyless lanes.

usage: pulse.py <topic_dir> --plan <file> [--days N] [--as-of YYYY-MM-DD] [--quick | --deep] [--deadline S]
lanes: hn (Hacker News stories through Algolia), reddit (arctic-shift, each reddit query in each subreddit),
       github (repository and issue search, and the repositories the plan names), arxiv (export API),
       youtube (yt-dlp, when installed)
The window is UTC: the N days that end with the as-of day (default today). Items outside it drop; undated ones stay.
output, tab-separated:
  # window <from> to <to> (UTC)
  LANE     <lane>  <status>  <note>
  CLUSTER  <id>  <score>  <lanes>  <n> items  <title>  <labels>      (over the floor, best first, up to 10)
  ITEM     <cluster id>  <lanes>  <date>  <engagement>  <url>  <title>   (up to 3 per cluster)
  WEAK     <id>  <score>  <lanes>  <title>  <url>                    (under the floor, up to 10)
  # <note>
  OK       <topic>/pulse/<stem>.json  <topic>/pulse/<stem>-evidence.md
  FAIL     <what>  <reason>
exit 0; 1 when no lane returned anything (each failed, was cut or was skipped); 2 for a bad plan or an egress hit.
"""
import argparse, html, json, math, os, re, shutil, socket, ssl, subprocess, sys, threading, time, unicodedata
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

VERSION = "0.4.0"

HN, ARCTIC = "https://hn.algolia.com/api/v1", "https://arctic-shift.photon-reddit.com/api"
GH, ARXIV = "https://api.github.com", "https://export.arxiv.org/api/query"
UA = f"Mozilla/5.0 (compatible; phro-search/{VERSION}; +https://github.com/ThatsHoon/phro-search)"
CAP = 10 * 1024 * 1024  # bytes per response
LANES = ("hn", "reddit", "github", "arxiv", "youtube")
NAMES = {"hn": "Hacker News", "reddit": "Reddit", "github": "GitHub", "arxiv": "arXiv", "youtube": "YouTube"}
DEPTH = {"quick": (20, 15), "default": (50, 40), "deep": (100, 60)}  # results per request, items clustered
DEADLINE = 90  # seconds for every lane together
BACKOFF = (2, 4, 8)  # seconds before each retry of a 429, a 5xx, a timeout or arctic-shift's 422 "slow down"
RETRY_AFTER_CAP = 60  # longest Retry-After (or X-RateLimit-Reset) honored, in seconds; a longer one gets the backoff
BOT_CHECK = (b"just a moment", b"checking your browser", b"captcha", b"verify you are human", b"are you a robot",
             b"attention required", b"challenge-platform", b"/cdn-cgi/challenge", b"ddos-guard")
W_REL, W_FRESH, W_ENG = 0.65, 0.25, 0.10
PHRASE_BONUS, GENERIC_CAP, FLOOR = 0.15, 0.25, 0.15
FRESH = {"strict": (1.0, 0), "balanced": (0.8, 10), "evergreen": (0.6, 40)}  # freshness = a * recency + b
DUP, JOIN = 0.7, 0.45  # title token Jaccard: near duplicates in one lane; joining a cluster's leader
LANE_BONUS, THIN, TOP_SHARE = 0.1, 0.4, 0.25
AUTHOR_CAP, LANE_PLACES, TOP_ITEMS, COMMENTS, YT_DETAILS = 3, 2, 3, 3, 5
SHOW_CLUSTERS, SHOW_ITEMS, SHOW_WEAK = 10, 3, 10
SNIP, COMMENT, BODY = 300, 280, 5000  # characters kept per snippet and per comment, and read for scoring
STOP = frozenset("a an and are as at be by can do for from has have how i in into is it its of on or that the this "
                 "to vs versus via was what when which who why will with without you your about using use".split())
GENERIC = frozenset("ai ml llm llms model models tool tools app apps open source data code library framework api "
                    "system systems project new best guide tutorial news update updates release releases".split())
TOKEN = re.compile(r"[^\W_]+")
SUBREDDIT = re.compile(r"[A-Za-z0-9_]{2,21}")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
YT_FILTER = ((1, "EgIIAg%253D%253D"), (7, "EgIIAw%253D%253D"), (31, "EgIIBA%253D%253D"), (366, "EgIIBQ%253D%253D"))  # uploaded today, this week, month, year
BOTS = re.compile(r"(?i)automoderator|.+-modteam")

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\U0000061c\U0000200b-\U0000200f\U0000202a-\U0000202e\U00002060-\U00002064\U00002066-\U00002069\U0000feff]")
_QUOTES = str.maketrans("\U00002018\U00002019\U0000201a\U0000201b\U00002032\U0000201c\U0000201d\U0000201e\U0000201f\U00002033\U0000ff02\U0000ff07", "'''''\"\"\"\"\"\"'")


def clean(s, cap=300):
    """One printable line: control, bidi and zero-width characters dropped, quote lookalikes made ASCII, whitespace collapsed."""
    return " ".join(_CTRL.sub("", str(s)).translate(_QUOTES).split())[:cap]


def egress_terms(cwd=None):
    """(term, source) pairs from ~/.claude/phro-search/forbidden.txt and the nearest .phro/project.json at or above cwd."""
    found = []
    path = Path.home() / ".claude" / "phro-search" / "forbidden.txt"
    if path.is_file():
        found += [(t.strip(), str(path)) for t in path.read_text(encoding="utf-8-sig").splitlines()
                  if t.strip() and not t.lstrip().startswith("#")]
    here = Path(cwd or os.getcwd()).resolve()
    for d in (here, *here.parents):
        p = d / ".phro" / "project.json"
        if p.is_file():
            try:
                terms = json.loads(p.read_text(encoding="utf-8-sig")).get("egress", {}).get("forbidden_terms", [])
            except (ValueError, AttributeError) as e:
                raise ValueError(f"{p}: {e}") from None
            if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
                raise ValueError(f"{p}: egress.forbidden_terms must be a list of strings")
            found += [(t.strip(), str(p)) for t in terms if t.strip()]
            break
    return [(t, s) for t, s in found if len(t) >= 2]


def _edge(c):
    return c.isascii() and c.isalnum()


def egress_hit(text, terms):
    """First (term, source) whose term appears in text, or None: NFKC and case-insensitive, also after
    percent-decoding; a term that starts or ends with an ASCII letter or digit must not touch another one there."""
    hay = {unicodedata.normalize("NFKC", h).casefold() for h in (text, urllib.parse.unquote_plus(text))}
    for term, source in terms:
        t = unicodedata.normalize("NFKC", term).casefold()
        pat = ("(?<![a-z0-9])" if _edge(t[0]) else "") + re.escape(t) + ("(?![a-z0-9])" if _edge(t[-1]) else "")
        if any(re.search(pat, h) for h in hay):
            return term, source
    return None


class Fail(Exception):
    """A short reason; rate is True when the host refused for its rate limit."""

    def __init__(self, reason, rate=False):
        super().__init__(reason)
        self.rate = rate


class _Redirect(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only within the host asked, so the GitHub token never leaves api.github.com."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            raise urllib.error.URLError("redirect to another host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_Redirect)
RUN = subprocess.run
_last = {}  # host -> monotonic time of its last request; each host is asked by one lane only


def error_body(e, n=8192):
    """The first n bytes of an HTTP error's body, lowercased; empty when it is gone."""
    try:
        return (e.read(n) or b"").lower()
    except Exception:
        return b""


def fetch(url, headers=None, end=None):
    """Body of an https URL, at most CAP bytes, 1 s apart per host (arXiv 3 s); raises Fail with a short reason.
    A 429, a 5xx, a timeout or arctic-shift's 422 that asks to slow down is retried after 2, 4 and 8 s (a 429 or 5xx
    after its Retry-After, a 429 also after X-RateLimit-Reset, when it asks 60 s or less) unless the wait would pass
    end, the lanes' run deadline. Never retried: GitHub's rate-limit 403 (Fail.rate is set), a 403 or 503 from a bot
    check, and any other status."""
    host = urllib.parse.urlsplit(url).hostname or ""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for backoff in (*BACKOFF, None):
        wait = _last.get(host, float("-inf")) + (3 if host == "export.arxiv.org" else 1) - time.monotonic()
        if wait > 0:  # arXiv's API terms ask for 3 s
            time.sleep(wait)
        left = 30 if end is None else end - time.monotonic()
        if left <= 0:
            raise Fail("run deadline reached")
        _last[host] = time.monotonic()
        try:
            with OPENER.open(req, timeout=min(30, max(1, left))) as r:
                body = r.read(CAP + 1)
        except urllib.error.HTTPError as e:
            h, text = e.headers or {}, error_body(e)
            if e.code in (403, 503) and (str(h.get("cf-mitigated", "")).strip().casefold() == "challenge"
                                         or any(p in text for p in BOT_CHECK)):
                raise Fail(f"http {e.code}: bot check") from None
            busy = e.code == 422 and b"slow down" in text  # the docs say: try again
            limited = e.code == 429 or (e.code == 403 and str(h.get("X-RateLimit-Remaining", "")) == "0")
            ra = str(h.get("Retry-After") or (h.get("X-RateLimit-Reset") if e.code == 429 else "") or "").strip()
            wait = int(ra) if ra.isascii() and ra.isdigit() and int(ra) <= RETRY_AFTER_CAP else backoff
            again = e.code == 429 or 500 <= e.code < 600 or busy
            if not again or backoff is None or (end is not None and time.monotonic() + wait > end):
                raise Fail("busy (http 422)" if busy else f"http {e.code}", rate=limited) from None
            time.sleep(wait)
            continue
        except Exception as e:  # any other network error becomes a short reason, never a traceback
            e = e.reason if isinstance(e, urllib.error.URLError) else e
            kinds = ((socket.gaierror, "dns"), (ssl.SSLError, "tls"), (TimeoutError, "timeout"))
            why = next((w for t, w in kinds if isinstance(e, t)), None)
            if why != "timeout" or backoff is None or (end is not None and time.monotonic() + backoff > end):
                raise Fail(why or clean(e if isinstance(e, str) else type(e).__name__, 80)) from None
            time.sleep(backoff)
            continue
        if len(body) > CAP:
            raise Fail("too large")
        return body


def get(st, url, what, headers=None, parse=json.loads):
    """Parsed body of one lane request, or None after noting why it failed; a lane asks nothing more once rate-limited."""
    if st["limited"]:
        return None
    st["requests"] += 1
    try:
        return parse(fetch(url, headers, st["end"]))
    except Fail as e:
        st["errors"].append(str(e))
        st["limited"] = e.rate
    except (ValueError, ET.ParseError):
        st["errors"].append(f"unreadable response from {what}")
    return None


def atom(body):
    """An Atom feed's root element; a DOCTYPE or ENTITY is refused before parsing, so no entity is ever expanded."""
    if re.search(rb"<!(?:doctype|entity)", body, re.I):
        raise ValueError("DOCTYPE or ENTITY in the feed")
    return ET.fromstring(body)


def tokens(text):
    return TOKEN.findall(unicodedata.normalize("NFKC", text).casefold())


def content(text):
    """The distinct tokens of text that are not stopwords, in order."""
    return [t for t in dict.fromkeys(tokens(text)) if t not in STOP]


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def strip_html(s):
    return html.unescape(re.sub(r"<[^>]*>", " ", s or ""))


def num(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def when(v):
    """UTC datetime of a Unix time or an ISO 8601 string, else None."""
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return datetime.fromtimestamp(v, timezone.utc)
        if isinstance(v, str) and re.match(r"\d{4}-\d\d-\d\d", v):
            d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def entry(lane, key, url, title, author, date, counts, snippet="", link=None, exempt=False, **extra):
    """One item in the shared shape; fields starting with _ stay out of the JSON."""
    return {"id": f"{lane}:{key}", "lane": lane, "url": url, "links": {lane: link or url}, "title": clean(title),
            "author": clean(author or "", 80), "date": date, "engagement": {lane: counts}, "snippet": clean(snippet, SNIP),
            "_body": clean(snippet, BODY), "comments": [], "exempt": exempt, **extra}


def q(s):
    return urllib.parse.quote_plus(s)


# Lanes: <lane>_search(st, ctx) yields (subquery label, item); <lane>_comments(st, ctx, item) returns its top comments.

def hn_search(st, ctx):
    for sq in ctx.queries("hn"):
        d = get(st, f"{HN}/search?query={q(sq['search_query'])}&tags=story&numericFilters="
                    f"created_at_i%3E%3D{ctx.lo_ts},created_at_i%3C{ctx.hi_ts}&hitsPerPage={ctx.n}", "Hacker News")
        for h in d.get("hits") or [] if isinstance(d, dict) else []:
            if isinstance(h, dict) and str(h.get("objectID", "")).isdigit():
                thread = f"https://news.ycombinator.com/item?id={h['objectID']}"
                url = h["url"] if re.match(r"https?://", str(h.get("url"))) else thread
                yield sq["label"], entry("hn", h["objectID"], url, h.get("title") or "", h.get("author"), when(h.get("created_at_i")),
                                         {"points": num(h.get("points")), "comments": num(h.get("num_comments"))},
                                         strip_html(h.get("story_text")), thread)


def hn_comments(st, ctx, it):
    d = get(st, f"{HN}/items/{it['id'].split(':', 1)[1]}", "Hacker News")

    def kids(c):
        return [k for k in c.get("children") or [] if isinstance(k, dict)]

    def size(c):  # Algolia gives comments no score; the replies under one stand in for it
        return 1 + sum(size(k) for k in kids(c))
    top = sorted((c for c in kids(d) if c.get("text")), key=lambda c: -size(c)) if isinstance(d, dict) else []
    return [{"author": clean(c.get("author") or "", 80), "score": size(c) - 1, "text": clean(strip_html(c["text"]), COMMENT),
             "url": f"https://news.ycombinator.com/item?id={c.get('id')}"} for c in top[:COMMENTS]]


def reddit_search(st, ctx):
    """Each reddit query in each subreddit (arctic-shift's full-text search is slow and has to be asked sparingly),
    plus the newest posts of each dedicated subreddit."""
    base = (f"{ARCTIC}/posts/search?after={ctx.lo_ts}&before={ctx.hi_ts}&limit={min(ctx.n, 100)}&sort=desc"
            "&fields=id,title,selftext,url,author,created_utc,score,num_comments,subreddit")  # it has no permalink field
    dedicated = ctx.plan["dedicated_subreddits"]
    own = {s.casefold() for s in dedicated}
    jobs = [(s, rq) for rq in ctx.plan["reddit_queries"] for s in ctx.plan["subreddits"] + dedicated] + [(s, None) for s in dedicated]
    for sub, rq in jobs:
        d = get(st, f"{base}&subreddit={sub}" + (f"&query={q(rq)}" if rq else ""), "arctic-shift")
        if isinstance(d, dict) and d.get("error"):  # it sometimes answers 200 with an error and no data
            st["errors"].append(f"arctic-shift: {clean(d['error'], 60)}")
        for p in d.get("data") or [] if isinstance(d, dict) else []:
            if not (isinstance(p, dict) and re.fullmatch(r"[a-z0-9]{1,12}", str(p.get("id")))
                    and SUBREDDIT.fullmatch(str(p.get("subreddit")))):
                continue
            link, out = f"https://www.reddit.com/r/{p['subreddit']}/comments/{p['id']}/", str(p.get("url") or "")
            external = re.match(r"https?://", out) and not re.match(r"https?://([\w-]+\.)?(reddit\.com|redd\.it)/", out)
            body = p.get("selftext") if p.get("selftext") not in ("[deleted]", "[removed]") else ""
            yield ("reddit" if rq else "dedicated"), entry(
                "reddit", p["id"], out if external else link, p.get("title") or "", p.get("author"), when(p.get("created_utc")),
                {"score": num(p.get("score")), "comments": num(p.get("num_comments"))}, body or "", link,
                exempt=str(p.get("subreddit")).casefold() in own, subreddit=clean(p.get("subreddit") or "", 30))


def reddit_comments(st, ctx, it):
    d = get(st, f"{ARCTIC}/comments/search?link_id={it['id'].split(':', 1)[1]}&limit=100", "arctic-shift")
    rows = sorted((c for c in (d.get("data") or [] if isinstance(d, dict) else []) if isinstance(c, dict)
                   and c.get("body") not in (None, "", "[deleted]", "[removed]") and not BOTS.fullmatch(str(c.get("author")))),
                  key=lambda c: -num(c.get("score")))
    return [{"author": clean(c.get("author") or "", 80), "score": num(c.get("score")), "text": clean(c["body"], COMMENT),
             "url": it["links"]["reddit"] + f"comment/{c.get('id')}/"} for c in rows[:COMMENTS]]


def github_search(st, ctx):
    span, per = f"{ctx.lo:%Y-%m-%d}..{ctx.last:%Y-%m-%d}", min(ctx.n, 100)
    for sq in ctx.queries("github"):
        d = get(st, f"{GH}/search/repositories?q={q(sq['search_query'] + ' pushed:' + span)}&sort=stars&order=desc&per_page={per}",
                "GitHub", ctx.gh)
        for r in d.get("items") or [] if isinstance(d, dict) else []:
            if isinstance(r, dict) and REPO.fullmatch(str(r.get("full_name"))):
                yield sq["label"], repository(r)
        d = get(st, f"{GH}/search/issues?q={q(sq['search_query'] + ' created:' + span)}&sort=reactions&order=desc&per_page={per}",
                "GitHub", ctx.gh)
        yield from issues(d, sq["label"], False)
    for repo in ctx.plan["github_repos"]:  # the repository itself (its last push dates it), its issues and its releases
        r = get(st, f"{GH}/repos/{repo}", "GitHub", ctx.gh)
        if isinstance(r, dict) and REPO.fullmatch(str(r.get("full_name"))):
            yield "repo", repository(r, exempt=True)
        d = get(st, f"{GH}/search/issues?q={q('repo:' + repo + ' created:' + span)}&sort=reactions&order=desc&per_page={per}",
                "GitHub", ctx.gh)
        yield from issues(d, "repo", True)
        d = get(st, f"{GH}/repos/{repo}/releases?per_page=10", "GitHub", ctx.gh)
        for r in d if isinstance(d, list) else []:
            if isinstance(r, dict) and str(r.get("html_url")).startswith("https://github.com/"):
                yield "repo", entry("github", r["html_url"].lower(), r["html_url"], f"{repo} {r.get('name') or r.get('tag_name') or ''}",
                                    (r.get("author") or {}).get("login"), when(r.get("published_at")),
                                    {"reactions": num((r.get("reactions") or {}).get("total_count"))}, r.get("body") or "", exempt=True)


def repository(r, exempt=False):
    return entry("github", r["full_name"].lower(), f"https://github.com/{r['full_name']}", r["full_name"],
                 (r.get("owner") or {}).get("login"), when(r.get("pushed_at")), {"stars": num(r.get("stargazers_count"))},
                 r.get("description") or "", exempt=exempt)


def issues(d, label, named):
    """Issues and pull requests of one search; only an API comments URL on api.github.com is kept for reading comments."""
    for i in d.get("items") or [] if isinstance(d, dict) else []:
        url = str(i.get("html_url")) if isinstance(i, dict) else ""
        if url.startswith("https://github.com/"):
            api = str(i.get("comments_url"))
            yield label, entry("github", url.lower(), url, i.get("title") or "", (i.get("user") or {}).get("login"),
                               when(i.get("created_at")), {"reactions": num((i.get("reactions") or {}).get("total_count")),
                                                           "comments": num(i.get("comments"))},
                               i.get("body") or "", exempt=named, _api=api if api.startswith(GH + "/repos/") else "")


def github_comments(st, ctx, it):
    d = get(st, it["_api"] + "?per_page=30", "GitHub", ctx.gh) if it.get("_api") else None
    rows = sorted((c for c in d if isinstance(c, dict) and c.get("body")),
                  key=lambda c: -num((c.get("reactions") or {}).get("total_count"))) if isinstance(d, list) else []
    return [{"author": clean((c.get("user") or {}).get("login") or "", 80), "score": num((c.get("reactions") or {}).get("total_count")),
             "text": clean(c["body"], COMMENT), "url": str(c.get("html_url") or "")} for c in rows[:COMMENTS]]


def arxiv_search(st, ctx):
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for sq in ctx.queries("arxiv"):
        words = [t for t in content(sq["search_query"]) if t.isascii()][:6]
        if not words:
            continue
        expr = urllib.parse.quote_plus(" AND ".join(f"all:{w}" for w in words), safe=":")
        root = get(st, f"{ARXIV}?search_query={expr}&sortBy=submittedDate&sortOrder=descending&max_results={min(ctx.n, 100)}",
                   "arXiv", parse=atom)
        for e in root.findall("a:entry", ns) if root is not None else []:
            m = re.match(r"https?://arxiv\.org/abs/(\S+?)(?:v\d+)?$", (e.findtext("a:id", "", ns) or "").strip())
            if m:
                yield sq["label"], entry("arxiv", m[1], f"https://arxiv.org/abs/{m[1]}", e.findtext("a:title", "", ns),
                                         e.findtext("a:author/a:name", "", ns), when(e.findtext("a:published", "", ns)), {},
                                         e.findtext("a:summary", "", ns))


def youtube_search(st, ctx):
    exe = shutil.which("yt-dlp") or "yt-dlp"
    queries = {sq["search_query"]: sq["label"] for sq in ctx.queries("youtube")}
    queries.update({y: "youtube" for y in ctx.plan["youtube_queries"] if y not in queries})
    sp = next((code for days, code in YT_FILTER if ctx.days <= days), "")
    found = {}
    for query, label in queries.items():
        out = ytdlp(st, ctx, [exe, "--flat-playlist", "-J", "--no-warnings", "--playlist-end", str(min(ctx.n, 50)),
                              f"https://www.youtube.com/results?search_query={q(query)}" + (f"&sp={sp}" if sp else "")])
        try:
            rows = (json.loads(out).get("entries") or []) if out else []
        except (ValueError, AttributeError):
            st["errors"].append("not a yt-dlp search result")
            continue
        for v in rows:
            if isinstance(v, dict) and re.fullmatch(r"[\w-]{6,20}", str(v.get("id"))) and v["id"] not in found:
                found[v["id"]] = (label, entry("youtube", v["id"], f"https://www.youtube.com/watch?v={v['id']}", v.get("title") or "",
                                               v.get("channel") or v.get("uploader"), None, {"views": num(v.get("view_count"))},
                                               v.get("description") or ""))
    top = sorted(found.values(), key=lambda x: -x[1]["engagement"]["youtube"]["views"])[:YT_DETAILS]
    if top:  # search results carry no upload date; one more call reads it, with likes and comments, for the most viewed
        out = ytdlp(st, ctx, [exe, "--skip-download", "--no-warnings", "--print",
                              "%(id)s\t%(upload_date)s\t%(view_count)s\t%(like_count)s\t%(comment_count)s", *(it["url"] for _, it in top)])
        for line in (out or b"").decode("utf-8", "replace").splitlines():
            vid, day, *counts = (line.split("\t") + [""] * 5)[:5]
            if vid in found and re.fullmatch(r"\d{8}", day):
                it = found[vid][1]
                it["date"] = datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
                it["engagement"]["youtube"] = {k: int(v) if v.isdigit() else 0 for k, v in zip(("views", "likes", "comments"), counts)}
    yield from found.values()


def reason_of(e):
    """An exception as a short reason: its type and, when it has one, its message."""
    msg = clean(e, 120)
    return clean(type(e).__name__, 40) + (f": {msg}" if msg else "")


def ytdlp(st, ctx, cmd):
    """Standard output of one yt-dlp call, cut at the lanes' deadline; None after noting why it gave nothing."""
    st["requests"] += 1
    try:
        r = RUN(cmd, capture_output=True, timeout=max(1.0, ctx.end - time.monotonic()))
    except subprocess.TimeoutExpired:
        st["errors"].append("yt-dlp timeout")
        return None
    except OSError as e:
        st["errors"].append(f"yt-dlp: {reason_of(e)}")
        return None
    if r.returncode != 0:
        st["errors"].append(f"yt-dlp exit {r.returncode}")
    return r.stdout or None


SEARCH = {"hn": (hn_search, hn_comments), "reddit": (reddit_search, reddit_comments),
          "github": (github_search, github_comments), "arxiv": (arxiv_search, None), "youtube": (youtube_search, None)}


def run_lane(name, st, ctx):
    """Search, then read the comments of the lane's best items that have any; results land in st as they come."""
    search, comments = SEARCH[name]
    try:
        for found in search(st, ctx):
            st["raw"].append(found)
        if comments:
            best = [i for i in score(prepare(list(st["raw"]), ctx), ctx) if i["_on"] and i["engagement"][name].get("comments")]
            for i in best[:TOP_ITEMS]:
                st["comments"][i["id"]] = comments(st, ctx, i)
    except Exception as e:  # a bug or an odd response fails this lane only
        st["errors"].append(f"error: {reason_of(e)}")
    st["done"] = True


def run_lanes(names, ctx):
    """Each lane in a daemon thread against one monotonic deadline; a lane still running then is left behind, not awaited."""
    states = {n: {"raw": [], "comments": {}, "requests": 0, "errors": [], "limited": False, "done": False, "end": ctx.end}
              for n in names}
    threads = [threading.Thread(target=run_lane, args=(n, states[n], ctx), daemon=True) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, ctx.end - time.monotonic()))
    return states


def engval(i):
    return sum(math.log1p(v) for counts in i["engagement"].values() for v in counts.values())


def prepare(raw, ctx):
    """One lane's items: copies found by several subqueries joined, the window applied, near duplicates dropped
    (the more engaged stays), engagement scaled to 0 to 100 within the lane."""
    by = {}
    for label, it in raw:
        if it["id"] in by:
            by[it["id"]]["_found"].add(label)
            by[it["id"]]["exempt"] |= it["exempt"]  # a named repository found by a search too stays exempt
        else:
            by[it["id"]] = dict(it, _found={label})
    kept = []
    for i in sorted(by.values(), key=lambda i: (-engval(i), i["id"])):
        if i["date"] is not None and not ctx.lo <= i["date"] < ctx.hi:
            continue
        i["_tok"], i["_engval"] = set(content(i["title"])), engval(i)
        if not any(jaccard(i["_tok"], k["_tok"]) >= DUP for k in kept):
            kept.append(i)
    lo, hi = min((i["_engval"] for i in kept), default=0), max((i["_engval"] for i in kept), default=0)
    for i in kept:
        i["_eng"] = 100 * (i["_engval"] - lo) / (hi - lo) if hi > lo else (50.0 if i["_engval"] > 0 else 0.0)
    return kept


def relevance(text, sq):
    """Share of the ranking query's content tokens found in text, plus PHRASE_BONUS when the search query appears
    whole; at most GENERIC_CAP when every token found is generic."""
    want, seq = content(sq["ranking_query"]), tokens(text)
    have = set(seq)
    hit = [t for t in want if t in have]
    r = len(hit) / len(want) if want else 0.0
    phrase = " ".join(tokens(sq["search_query"]))
    if phrase and f" {phrase} " in f" {' '.join(seq)} ":
        r += PHRASE_BONUS
    if hit and all(t in GENERIC for t in hit):
        r = min(r, GENERIC_CAP)
    return min(r, 1.0)


def score(items, ctx):
    """Scores each item on the subquery that found it best (every subquery for items found without one), best first;
    _on marks items at or over the relevance floor, or exempt from it."""
    a, b = FRESH[ctx.plan["freshness"]]
    span = (ctx.hi - ctx.lo).total_seconds()
    for i in items:
        rec = 0.0 if i["date"] is None else 100 * min(1.0, max(0.0, (i["date"] - ctx.lo).total_seconds() / span))
        lead = " ".join([i["title"], i["snippet"]] + [c["text"] for c in i["comments"][:1]])
        # a post or an abstract may name the topic late: a word found only there counts half; GitHub bodies are mostly
        # templates and logs, so an issue counts on its lead alone
        full = lead if i["lane"] == "github" else f"{lead} {i['_body']}"
        w_rel, w_eng = (W_REL + W_ENG, 0.0) if i["lane"] == "arxiv" else (W_REL, W_ENG)
        best = (-1.0, 0.0, "")
        for sq in [s for s in ctx.plan["subqueries"] if s["label"] in i["_found"]] or ctx.plan["subqueries"]:
            rel = (relevance(lead, sq) + relevance(full, sq)) / 2
            s = 100 * sq["weight"] * (w_rel * rel + W_FRESH * (a * rec + b) / 100 + w_eng * i["_eng"] / 100)
            best = max(best, (s, rel, sq["label"]))
        i["score"], i["relevance"], i["subquery"] = round(best[0], 1), round(best[1], 2), best[2]
        i["_on"] = best[1] >= FLOOR or i["exempt"]
    items.sort(key=lambda i: (-i["score"], i["id"]))
    return items


def top_quarter(items):
    """Marks _top on the items in the top quarter of one lane's engagement; an item with none is never marked."""
    vals = sorted((i["_engval"] for i in items), reverse=True)
    cut = vals[max(0, math.ceil(len(vals) * TOP_SHARE) - 1)] if vals else 0
    for i in items:
        i["_top"] = i["_engval"] > 0 and i["_engval"] >= cut


def norm_url(u):
    """A URL as compared across lanes: no scheme, www, trailing slash, fragment or tracking parameters;
    arXiv and YouTube links reduced to the paper or the video."""
    s = urllib.parse.urlsplit(u.strip())
    host = re.sub(r"^(www|m|old)\.", "", (s.hostname or "").lower())
    path = s.path.rstrip("/")
    query = "&".join(sorted(p for p in s.query.split("&") if p and not re.match(r"(?i)(utm_\w+|ref|ref_src|source|si)=", p)))
    if host == "youtu.be":
        host, path, query = "youtube.com", "/watch", "v=" + path.strip("/")
    elif host == "youtube.com" and path == "/watch":
        query = "&".join(p for p in query.split("&") if p.startswith("v="))
    elif host == "arxiv.org":
        path = re.sub(r"^/(?:abs|pdf)/(.+?)(?:v\d+)?(?:\.pdf)?$", r"/abs/\1", path)
    elif host == "github.com":
        path = path.lower()
    return host + path + ("?" + query if query else "")


def link_key(u):
    """What two items must share to be one story: the repository for a GitHub link to its root, code or releases,
    else the normalized URL."""
    n = norm_url(u)
    m = re.match(r"(github\.com/[^/?]+/[^/?]+)(?:/(?:tree|blob|releases)(?:/.*)?)?$", n)
    return m[1] if m else n


def merge(items):
    """All lanes' items keyed on the normalized URL, best first; the best copy stays and takes the other copies'
    engagement, links and comments."""
    by = {}
    for i in sorted(items, key=lambda i: (-i["score"], i["id"])):
        k = norm_url(i["url"])
        if k not in by:
            by[k] = dict(i, lanes=[i["lane"]], engagement=dict(i["engagement"]), links=dict(i["links"]), comments=list(i["comments"]))
            continue
        m = by[k]
        for lane, counts in i["engagement"].items():
            m["engagement"].setdefault(lane, counts)
        for lane, link in i["links"].items():
            m["links"].setdefault(lane, link)
        m["comments"] += i["comments"]
        m["lanes"] = sorted(set(m["lanes"]) | {i["lane"]})
        m["_top"] = m["_top"] or i["_top"]
        m["exempt"] = m["exempt"] or i["exempt"]
    return list(by.values())


def pick_pool(items, size):
    """The items clustered: each lane's best LANE_PLACES first, then the rest by score; at most AUTHOR_CAP per author in a lane."""
    pool, ids, per = [], set(), {}

    def take(i):
        who = (i["lane"], i["author"].casefold())
        if i["id"] in ids or (who[1] and per.get(who, 0) >= AUTHOR_CAP):
            return False
        per[who] = per.get(who, 0) + 1
        ids.add(i["id"])
        pool.append(i)
        return True
    for lane in LANES:
        n = 0
        for i in items:
            if n < LANE_PLACES and i["lane"] == lane and take(i):
                n += 1
    for i in items:
        if len(pool) >= size:
            break
        take(i)
    return sorted(pool, key=lambda i: (-i["score"], i["id"]))


def cluster(pool):
    """Greedy clusters over the pool, best item first: an item joins the first cluster whose leader has its link key
    or a title token Jaccard of JOIN or more; otherwise it leads a new one."""
    out = []
    for i in pool:
        key = link_key(i["url"])
        c = next((c for c in out if c["_key"] == key or jaccard(i["_tok"], c["_items"][0]["_tok"]) >= JOIN), None)
        if c:
            c["_items"].append(i)
        else:
            out.append({"_key": key, "_items": [i]})
    for c in out:
        lead, lanes = c["_items"][0], sorted({x for i in c["_items"] for x in i["lanes"]})
        c.update(title=lead["title"], score=round(lead["score"] * (1 + LANE_BONUS * (len(lanes) - 1)), 1), lanes=lanes,
                 items=[i["id"] for i in c["_items"]], _solid=len(lanes) >= 2 or lead["_top"],
                 labels=(["single-lane"] if len(lanes) == 1 else []) + (["thin"] if max(i["relevance"] for i in c["_items"]) < THIN else []))
    out.sort(key=lambda c: (-c["score"], c["items"][0]))
    for n, c in enumerate(out, 1):
        c["id"] = f"k{n}"
    return out


def status(st, fetched, on_topic, name):
    """(status, note) of a lane that ran."""
    errs = list(dict.fromkeys(st["errors"]))
    why = "; ".join(errs[:3])
    hint = "; set GH_TOKEN for more searches" if name == "github" else ""
    if not st["done"]:
        return "timeout", f"cut at the deadline after {st['requests']} requests; {fetched} fetched, {on_topic} on topic"
    if errs and st["requests"] <= len(st["errors"]):
        return ("rate-limited", why + hint) if st["limited"] else (f"failed: {errs[0]}", why)
    note = f"{fetched} fetched, {on_topic} on topic" + (f"; {why}" if why else "")
    if st["limited"]:
        return "rate-limited", note + hint
    if errs:
        return "partial", note
    return ("ok", note) if on_topic else ("no-results", f"{fetched} fetched, none on topic")


def engagement_text(e):
    """Counts as text, such as '412 points, 230 comments; 1,204 stars'."""
    return "; ".join(", ".join(f"{v:,} {k}" for k, v in c.items()) for c in e.values() if c) or "-"


def load_plan(path, days):
    """The plan file with defaults filled in; raises ValueError naming the first problem."""
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError:
        raise ValueError(f"cannot read {path}") from None
    except ValueError as e:
        raise ValueError(f"not valid JSON: {e}") from None
    if not isinstance(plan, dict):
        raise ValueError("the plan must be a JSON object")
    subs = plan.get("subqueries")
    if not isinstance(subs, list) or not 1 <= len(subs) <= 4:
        raise ValueError("subqueries must be a list of 1 to 4 objects")
    labels = set()
    for n, sq in enumerate(subs, 1):
        if not isinstance(sq, dict) or not isinstance(sq.get("search_query"), str) or not sq["search_query"].strip():
            raise ValueError(f"subquery {n}: search_query must be a non-empty string")
        sq["label"] = clean(sq.get("label") or f"q{n}", 40)
        sq.setdefault("ranking_query", sq["search_query"])
        sq.setdefault("lanes", list(LANES))
        sq.setdefault("weight", 1.0)
        w = sq["weight"]
        if not isinstance(sq["ranking_query"], str) or not sq["ranking_query"].strip():
            raise ValueError(f"subquery {n}: ranking_query must be a non-empty string")
        if not isinstance(sq["lanes"], list) or not sq["lanes"] or any(x not in LANES for x in sq["lanes"]):
            raise ValueError(f"subquery {n}: lanes must be a non-empty list from {', '.join(LANES)}")
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not 0 < w <= 1:
            raise ValueError(f"subquery {n}: weight must be over 0 and at most 1")
        if sq["label"] in labels | {"dedicated", "reddit", "repo", "youtube"}:
            raise ValueError(f"subquery {n}: the label {sq['label']} is taken")
        labels.add(sq["label"])
    plan.setdefault("freshness", "balanced")
    if plan["freshness"] not in FRESH:
        raise ValueError(f"freshness must be one of {', '.join(FRESH)}")
    plan["days"] = plan.get("days", 30) if days is None else days
    if isinstance(plan["days"], bool) or not isinstance(plan["days"], int) or not 1 <= plan["days"] <= 365:
        raise ValueError("days must be a whole number from 1 to 365")
    for key, rx, like in (("subreddits", SUBREDDIT, "LocalLLaMA"), ("dedicated_subreddits", SUBREDDIT, "LocalLLaMA"),
                          ("github_repos", REPO, "owner/name")):
        vals = plan.setdefault(key, [])
        if not isinstance(vals, list) or not all(isinstance(v, str) and rx.fullmatch(v.removeprefix("r/")) for v in vals):
            raise ValueError(f"{key} must be a list of names like {like}")
        plan[key] = [v.removeprefix("r/") for v in vals]
    yq = plan.setdefault("youtube_queries", [])
    if not isinstance(yq, list) or not all(isinstance(v, str) and v.strip() for v in yq):
        raise ValueError("youtube_queries must be a list of search phrases")
    if not isinstance(plan.setdefault("entity", ""), str):
        raise ValueError("entity must be a string")
    rq = plan.setdefault("reddit_queries", [])
    if not isinstance(rq, list) or len(rq) > 3 or not all(isinstance(v, str) and v.strip() for v in rq):
        raise ValueError("reddit_queries must be a list of up to 3 search phrases")
    plan["reddit_queries"] = rq or [plan["entity"].strip() or next((s["search_query"] for s in subs if "reddit" in s["lanes"]),
                                                                    subs[0]["search_query"])]
    return plan


def item_lines(i):
    out = [f"- {i['title']} <{i['url']}>",
           f"  {', '.join(NAMES[x] for x in i['lanes'])}; {i['date'] or 'undated'}; {engagement_text(i['engagement'])}; "
           f"by {i['author'] or 'unknown'}; score {i['score']}"]
    out += [f"  {NAMES[k]} thread: <{v}>" for k, v in i["links"].items() if v != i["url"]]
    if i["snippet"]:
        out.append(f"  snippet: {i['snippet']}")
    out += [f"  comment by {c['author']} ({c['score']}) <{c['url']}>: {c['text']}" for c in i["comments"]]
    return out


def evidence(result, by):
    """The evidence Markdown the brief is written from: lanes, clusters over the floor with their items, weak signals."""
    md = [f"# Pulse: {result['topic']} ({result['as_of']})", "", f"Window (UTC): {result['window']['from']} to {result['window']['to']}",
          "", "## Lanes", ""]
    md += [f"- {NAMES[n]}: {v['status']}; {v['note']}" for n, v in result["lanes"].items()]
    md += ["", "## Clusters", ""]
    for c in result["clusters"]:
        md += [f"### {c['id']}: {c['title']}", "",
               f"score {c['score']}; {', '.join(NAMES[x] for x in c['lanes'])}; {len(c['items'])} items"
               + (f"; {', '.join(c['labels'])}" if c["labels"] else ""), ""]
        for iid in c["items"]:
            md += item_lines(by[iid])
        md.append("")
    if not result["clusters"]:
        md += ["Nothing solid in the window: no cluster spans 2 lanes or leads its lane's engagement.", ""]
    md += ["## Weak signals", ""]
    for c in result["weak"]:
        md += item_lines(by[c["items"][0]])
    return "\n".join(md) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(prog="pulse.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("topic_dir", help="topic folder, such as ~/research/<topic>")
    p.add_argument("--plan", required=True, help="plan JSON written by the host (format in references/formats.md)")
    p.add_argument("--days", type=int, metavar="N", help="window length in days, 1 to 365 (default: the plan's, else 30)")
    p.add_argument("--as-of", metavar="YYYY-MM-DD", help="the window's last day in UTC, for replays (default: today)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--quick", action="store_true", help="20 results per request, 15 items clustered")
    g.add_argument("--deep", action="store_true", help="100 results per request, 60 items clustered")
    p.add_argument("--deadline", type=float, default=DEADLINE, metavar="S", help=f"seconds for all lanes together (default {DEADLINE})")
    a = p.parse_args(argv)
    try:
        plan = load_plan(os.path.expanduser(a.plan), a.days)  # a quoted ~ reaches the script unexpanded
    except ValueError as e:
        print(f"FAIL\tplan\t{clean(e)}")
        return 2
    try:
        as_of = datetime.strptime(a.as_of, "%Y-%m-%d").date() if a.as_of else datetime.now(timezone.utc).date()
    except ValueError:
        print("FAIL\t--as-of\tuse YYYY-MM-DD")
        return 2
    try:
        terms = egress_terms()
    except Exception as e:  # fail closed: a term list that cannot be read blocks every request
        print(f"FAIL\tegress\tcannot read the term list: {clean(e)}")
        return 2
    sent = [sq["search_query"] for sq in plan["subqueries"]] + plan["subreddits"] + plan["dedicated_subreddits"]
    for text in sent + plan["reddit_queries"] + plan["github_repos"] + plan["youtube_queries"]:
        hit = egress_hit(text, terms)
        if hit:
            print(f"FAIL\t{clean(text, 80)}\tegress: '{hit[0]}' is listed in {hit[1]}; use a generic problem statement")
            return 2
    hi = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc) + timedelta(days=1)
    lo = hi - timedelta(days=plan["days"])
    n, size = DEPTH["quick" if a.quick else "deep" if a.deep else "default"]
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    ctx = SimpleNamespace(plan=plan, lo=lo, hi=hi, last=as_of, lo_ts=int(lo.timestamp()), hi_ts=int(hi.timestamp()), n=n,
                          days=plan["days"], end=time.monotonic() + max(a.deadline, 0.1),
                          gh={"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})},
                          queries=lambda lane: [sq for sq in plan["subqueries"] if lane in sq["lanes"]])
    wanted = {lane for sq in plan["subqueries"] for lane in sq["lanes"]}
    wanted |= {lane for lane, key in (("reddit", "dedicated_subreddits"), ("github", "github_repos"), ("youtube", "youtube_queries"))
               if plan[key]}
    skip = {}
    if not plan["subreddits"] and not plan["dedicated_subreddits"]:
        skip["reddit"] = "no subreddits in the plan; arctic-shift searches one subreddit at a time"
    if not shutil.which("yt-dlp"):
        skip["youtube"] = "yt-dlp is not installed"
    states = run_lanes([x for x in LANES if x in wanted and x not in skip], ctx)
    lanes, items, gave = {}, [], False
    for name in (x for x in LANES if x in wanted):  # lanes the plan leaves out are not listed
        if name not in states:
            lanes[name] = {"status": "skipped", "count": 0, "note": skip[name]}
            continue
        st = states[name]
        got = prepare(list(st["raw"]), ctx)
        for i in got:
            i["comments"] = st["comments"].get(i["id"], [])
        on = [i for i in score(got, ctx) if i["_on"]]
        top_quarter(on)
        state, note = status(st, len(got), len(on), name)
        lanes[name] = {"status": state, "count": len(on), "note": note}
        gave = gave or bool(got) or state in ("ok", "no-results", "partial")
        items += on
    head = next(iter(content(plan["entity"])), None)
    merged = merge(items)
    for i in merged:
        i["grounded"] = head is None or head in tokens(" ".join([i["title"], i["_body"]] + [c["text"] for c in i["comments"]]))
        i["date"] = i["date"].strftime("%Y-%m-%d") if i["date"] else None
    pool = pick_pool([i for i in merged if i["grounded"]], size)
    ids = {i["id"] for i in pool}
    for i in merged:
        i["pool"] = i["id"] in ids
    clusters = cluster(pool)

    def public(d):
        return {k: v for k, v in d.items() if not k.startswith("_")}
    result = {"topic": Path(a.topic_dir).expanduser().resolve().name, "as_of": as_of.isoformat(),
              "window": {"from": lo.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": hi.strftime("%Y-%m-%dT%H:%M:%SZ")},
              "days": plan["days"], "freshness": plan["freshness"], "plan": plan, "lanes": lanes,
              "items": [public(i) for i in merged], "clusters": [public(c) for c in clusters if c["_solid"]],
              "weak": [public(c) for c in clusters if not c["_solid"]]}
    folder = Path(a.topic_dir).expanduser() / "pulse"
    folder.mkdir(parents=True, exist_ok=True)
    k = 1
    while True:  # never overwrite an earlier run
        stem = as_of.isoformat() + (f"-{k}" if k > 1 else "")
        try:
            with (folder / f"{stem}.json").open("x", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
            break
        except FileExistsError:
            k += 1
    by = {i["id"]: i for i in merged}
    (folder / f"{stem}-evidence.md").write_text(evidence(result, by), encoding="utf-8")
    print(f"# window {result['window']['from']} to {result['window']['to']} (UTC)")
    for name, v in lanes.items():
        print(f"LANE\t{name}\t{v['status']}\t{clean(v['note'])}")
    for c in result["clusters"][:SHOW_CLUSTERS]:
        print(f"CLUSTER\t{c['id']}\t{c['score']}\t{','.join(c['lanes'])}\t{len(c['items'])} items\t{c['title']}\t{','.join(c['labels'])}")
        for iid in c["items"][:SHOW_ITEMS]:
            i = by[iid]
            print(f"ITEM\t{c['id']}\t{','.join(i['lanes'])}\t{i['date'] or 'undated'}\t{engagement_text(i['engagement'])}\t"
                  f"{clean(i['url'])}\t{i['title']}")
    for c in result["weak"][:SHOW_WEAK]:
        print(f"WEAK\t{c['id']}\t{c['score']}\t{','.join(c['lanes'])}\t{c['title']}\t{clean(by[c['items'][0]]['url'])}")
    if not result["clusters"]:
        print("# nothing solid in the window: no cluster spans 2 lanes or leads its lane's engagement")
    hidden = max(0, len(result["clusters"]) - SHOW_CLUSTERS) + max(0, len(result["weak"]) - SHOW_WEAK)
    if hidden:
        print(f"# {hidden} more clusters in the evidence file")
    print(f"OK\t{folder / (stem + '.json')}\t{folder / (stem + '-evidence.md')}")
    return 0 if gave else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
