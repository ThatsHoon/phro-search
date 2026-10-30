"""Watch a topic's venues through their feeds and list what is new since the last check.

usage:
  watch.py add <topic_dir> <url> [name]            find the venue's feed, verify it, append it to watch.tsv
  watch.py list <topic_dir>                        print the feeds in watch.tsv
  watch.py check <topic_dir> [--days N] [--fresh]  print what is new, write watch/<UTC time>.md

output, one tab-separated line per result:
  ADDED   kind  name  feed  <n> items, latest <YYYY-MM-DD or ->
  EXISTS  name  feed
  kind    name  feed  source                    (list)
  NEW     date  name  title  url  first line    (check, newest first; the original's first line, no summary)
  LATEST  date  name  title  url                (check, the latest item of a feed with nothing new)
  FAIL    url or name  reason
  # note
"""
import argparse, email.utils, html, html.parser, json, os, re, socket, ssl, string, sys, time, unicodedata
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "0.4.0"

ARCTIC = "https://arctic-shift.photon-reddit.com"
YOUTUBE = "https://www.youtube.com/feeds/videos.xml"
UA = f"Mozilla/5.0 (compatible; phro-search/{VERSION}; +https://github.com/ThatsHoon/phro-search)"
CAP, KEEP = 10 * 1024 * 1024, 500  # bytes per response; seen item URLs kept per feed
FALLBACKS = ("/feed", "/rss", "/atom.xml", "/feed.xml", "/index.xml", "/rss.xml")
NO_FEED = re.compile(r"(^|\.)(x\.com|twitter\.com|pixiv\.net|reddit\.com|redd\.it)$")  # hosts never requested
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

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
    """A short reason for a FAIL line."""


class _Redirect(urllib.request.HTTPRedirectHandler):
    """Follows 308 like 307 (urllib does so only from Python 3.11) and never into a NO_FEED host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if NO_FEED.search(urllib.parse.urlsplit(newurl).hostname or ""):
            raise urllib.error.URLError("no public feed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_302(req, fp, 307, msg, headers)


OPENER = urllib.request.build_opener(_Redirect)
_last = {}  # host -> monotonic time of its last request


def fetch(url):
    """Body of an http(s) URL, at most CAP bytes; raises Fail with a short reason."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if not re.match(r"https?://", url, re.I):
        raise Fail("not an http(s) URL")
    if NO_FEED.search(host):
        raise Fail("no public feed")
    req = urllib.request.Request(urllib.parse.quote(url, safe=string.punctuation), headers={"User-Agent": UA})
    for backoff in (2, 4, 8, None):
        wait = _last.get(host, float("-inf")) + (3 if host == "export.arxiv.org" else 1) - time.monotonic()
        if wait > 0:  # 1 s between requests to one host; arXiv's API terms ask for 3 s
            time.sleep(wait)
        _last[host] = time.monotonic()
        try:
            with OPENER.open(req, timeout=30) as r:
                body = r.read(CAP + 1)
        except urllib.error.HTTPError as e:
            if e.code != 429 or backoff is None:
                raise Fail(f"http {e.code}") from None
            ra = str(e.headers.get("Retry-After") or "").strip()
            time.sleep(int(ra) if ra.isascii() and ra.isdigit() and int(ra) <= 60 else backoff)
            continue
        except Exception as e:  # any other network error becomes a short reason, never a traceback
            e = e.reason if isinstance(e, urllib.error.URLError) else e
            kinds = ((socket.gaierror, "dns"), (ssl.SSLError, "tls"), (TimeoutError, "timeout"))
            why = next((w for t, w in kinds if isinstance(e, t)), None)
            raise Fail(why or clean(e if isinstance(e, str) else type(e).__name__, 80)) from None
        if len(body) > CAP:
            raise Fail("too large")
        return body


def to_utc(s):
    """UTC datetime of an ISO 8601 or RFC 822 date, or None."""
    m = re.match(r"\s*(\d{4}-\d\d-\d\d)(?:[T ](\d\d:\d\d(?::\d\d)?)[.,]?\d*)?\s*(?:[Zz]|([+-]\d\d):?(\d\d))?\s*$", s)
    try:
        d = (datetime.fromisoformat(f"{m[1]}T{m[2] or '00:00'}{m[3] or '+00'}:{m[4] or '00'}") if m
             else email.utils.parsedate_to_datetime(s))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    return d.replace(tzinfo=d.tzinfo or timezone.utc).astimezone(timezone.utc)


def _day(d):
    return d.strftime("%Y-%m-%d") if d else "-"


def _key(item):
    return item["date"] or EPOCH


def first_line(s):
    """First non-empty line of a text or HTML body: tags stripped, entities unescaped, cleaned."""
    s = re.sub(r"(?i)<br\s*/?>|</(?:p|div|li|h[1-6]|tr|pre|blockquote)\s*>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]*>", "", s))
    return next((c for c in (clean(line, 200) for line in s.splitlines()) if c), "")


def _local(el):
    return el.tag.rsplit("}", 1)[-1]


def _text(el, name, deep=False):
    """Text of el's first child (with deep, first descendant) with this local name, else ""."""
    c = next((c for c in (el.iter() if deep else el) if c is not el and _local(c) == name), None)
    return "" if c is None else "".join(c.itertext()).strip()


def _posts(body):
    """Items of an arctic-shift posts response, {"data": [post, ...]}."""
    try:
        return [{"title": str(p.get("title") or ""), "url": "https://www.reddit.com" + p["permalink"],
                 "date": datetime.fromtimestamp(p["created_utc"], timezone.utc) if p.get("created_utc") else None,
                 "first": first_line(str(p.get("selftext") or p.get("url") or ""))}
                for p in json.loads(body)["data"] if p.get("permalink")]
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, OSError):
        raise Fail("not an arctic-shift response") from None


def parse(body, kind=None):
    """(format, feed title, items) of a feed body; an item has title, url, date (UTC or None) and first."""
    if kind == "reddit":
        return "reddit", "", _posts(body)
    if re.search(rb"<!(?:doctype|entity)", body.replace(b"\0", b""), re.I):  # NULs dropped: UTF-16 cannot hide it
        raise Fail("refused: DOCTYPE or ENTITY in feed")
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError, LookupError) as e:
        raise Fail(f"not a feed: {clean(e, 80)}") from None
    fmt = {"rss": "rss", "RDF": "rss", "feed": "atom"}.get(_local(root))
    if not fmt:
        raise Fail("not a feed")
    items = []
    for e in root.iter():
        if _local(e) not in ("item", "entry"):
            continue
        url = next((ln.get("href") or "".join(ln.itertext()).strip() for ln in e
                    if _local(ln) == "link" and ln.get("rel", "alternate") == "alternate"), "")
        url = url or _text(e, "guid") or _text(e, "id")
        dates = (to_utc(_text(e, n)) for n in ("published", "pubDate", "date", "updated"))
        texts = (_text(e, n, True) for n in ("description", "summary", "content", "encoded"))
        if url:
            items.append({"title": _text(e, "title"), "url": url, "date": next((d for d in dates if d), None),
                          "first": first_line(next((t for t in texts if t), ""))})
    return fmt, _text(root, "title", True), items


class _Links(html.parser.HTMLParser):
    """Collects the hrefs of <link rel="alternate"> tags whose type is RSS or Atom."""

    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "").strip() for k, v in attrs}
        if (tag == "link" and "alternate" in a.get("rel", "").lower().split() and a.get("href")
                and a.get("type", "").lower() in ("application/rss+xml", "application/atom+xml")):
            self.hrefs.append(a["href"])


def alternate(text, base):
    """First RSS or Atom alternate link of an HTML page as an absolute URL, else None."""
    p = _Links()
    p.feed(text)
    return urllib.parse.urljoin(base, p.hrefs[0]) if p.hrefs else None


def locate(url):
    """(kind or None, feed URL, feed body or None) for a venue URL; raises Fail."""
    u = urllib.parse.urlsplit(url)
    host, q = re.sub(r"^(www|m|old|new)\.", "", u.hostname or ""), urllib.parse.parse_qs(u.query)
    one, two = ([s for s in u.path.split("/") if s] + ["", ""])[:2]
    if host == "qiita.com" and one == "tags" and two:
        return "qiita-tag", f"https://qiita.com/tags/{two}/feed", None
    if host == "qiita.com" and one:
        return "qiita-user", f"https://qiita.com/{one}/feed", None
    if host == "zenn.dev" and one == "topics" and two:
        return "zenn-topic", f"https://zenn.dev/topics/{two}/feed", None
    if host == "zenn.dev" and one:
        return "zenn-user", f"https://zenn.dev/{one}/feed", None
    if host == "note.com" and one:
        return "note", f"https://note.com/{one}/rss", None
    if host == "github.com" and two:
        return "github-releases", f"https://github.com/{one}/{two.removesuffix('.git')}/releases.atom", None
    if host == "youtube.com" and one == "channel" and two:
        return "youtube", f"{YOUTUBE}?channel_id={two}", None
    if host == "youtube.com" and one == "playlist" and q.get("list"):
        return "youtube", f"{YOUTUBE}?playlist_id={q['list'][0]}", None
    if host == "youtube.com" and one.startswith("@"):
        page = f"https://www.youtube.com/{one}"
        text = fetch(page).decode("utf-8", "replace")
        m = re.search(r'"channelId":"(UC[\w-]+)"', text)
        feed = alternate(text, page) or (m and f"{YOUTUBE}?channel_id={m[1]}")
        if not feed:
            raise Fail("no channel id found")
        return "youtube", feed, None
    if host == "export.arxiv.org" and u.path.startswith("/api/query"):
        extra = "&".join(f"{k}={v}" for k, v in (("sortBy", "submittedDate"), ("sortOrder", "descending")) if k not in q)
        return "arxiv", url + ("&" if u.query else "?") + extra if extra else url, None
    if host == "reddit.com" and one == "r" and two:
        return "reddit", f"{ARCTIC}/api/posts/search?subreddit={two}&sort=desc&limit=100", None
    body = fetch(url)  # the URL is a feed itself, or a page that names or hides one
    try:
        parse(body)
        return None, url, body
    except Fail:
        if not re.search(rb"<html", body[:65536], re.I):
            raise
    feed = alternate(body.decode("utf-8", "replace"), url)
    if feed:
        return None, feed, None
    for path in FALLBACKS:
        try:
            body = fetch(f"{u.scheme}://{u.netloc}{path}")
            parse(body)
            return None, f"{u.scheme}://{u.netloc}{path}", body
        except Fail:
            pass
    raise Fail("no feed found")


def read_feeds(top):
    """Rows of watch.tsv as dicts with kind, name, feed and source."""
    p = top / "watch.tsv"
    lines = p.read_text(encoding="utf-8").splitlines()[1:] if p.is_file() else []
    return [dict(zip(("kind", "name", "feed", "source"), ln.split("\t"))) for ln in lines if ln.count("\t") >= 2]


def fail(what, reason):
    print(f"FAIL\t{clean(what)}\t{clean(reason)}")
    return 1


def cmd_add(a):
    top, url = Path(a.topic_dir).expanduser(), a.url.strip()
    if not re.fullmatch(r"https?://\S+", url, re.I):
        return fail(url, "not an http(s) URL")
    try:
        hit = egress_hit(url, egress_terms())
    except Exception as e:  # fail closed: a term list that cannot be read blocks the request
        return fail(url, f"egress: cannot read the term list: {e}")
    if hit:
        return fail(url, f"egress: '{hit[0]}' is listed in {hit[1]}; use a generic problem statement")
    try:
        kind, feed, body = locate(url)
        feed = urllib.parse.quote(feed, safe=string.punctuation)  # one ASCII field in watch.tsv
        known = {f["feed"]: f["name"] for f in read_feeds(top)}
        if feed in known:
            print(f"EXISTS\t{clean(known[feed])}\t{clean(feed)}")
            return 0
        fmt, title, items = parse(fetch(feed) if body is None else body, kind)
    except Fail as e:
        return fail(url, str(e))
    kind, u = kind or fmt, urllib.parse.urlsplit(url)
    derived = re.sub(r"^(www|m|old|new)\.", "", u.netloc.lower()) + u.path.rstrip("/")
    name = clean(a.name or "", 60) or clean(title, 60) or clean(derived, 60)
    top.mkdir(parents=True, exist_ok=True)
    p = top / "watch.tsv"
    text = p.read_text(encoding="utf-8") if p.is_file() else "kind\tname\tfeed\tsource\n"
    text += ("" if text.endswith("\n") else "\n") + "\t".join((kind, name, feed, url)) + "\n"
    p.write_text(text, encoding="utf-8")
    dated = [i["date"] for i in items if i["date"]]
    print(f"ADDED\t{kind}\t{name}\t{clean(feed)}\t{len(items)} items, latest {_day(max(dated) if dated else None)}")
    return 0


def cmd_list(a):
    feeds = read_feeds(Path(a.topic_dir).expanduser())
    for f in feeds:
        print("\t".join(clean(f.get(k, "")) for k in ("kind", "name", "feed", "source")))
    if not feeds:
        print("# no feeds yet: watch.py add <topic_dir> <url>")
    return 0


def cmd_check(a):
    top = Path(a.topic_dir).expanduser()
    feeds, sp = read_feeds(top), top / "watch-state.json"
    if not feeds:
        print("# no feeds yet: watch.py add <topic_dir> <url>")
        return 0
    try:
        state = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
    except ValueError:
        state = None
    if not isinstance(state, dict):
        return fail(sp, "not a valid state file; fix or remove it")
    now = datetime.now(timezone.utc)
    new, quiet, failed, busy = [], [], [], 0
    for f in feeds:
        try:
            items = parse(fetch(f["feed"]), f["kind"])[2]
        except Fail as e:
            failed.append((f["name"], str(e)))
            continue
        old = state.get(f["feed"])
        if old is None or a.fresh:
            picked = [i for i in items if i["date"] and i["date"] >= now - timedelta(days=a.days)]
        else:
            seen = set(old.get("seen", []))
            picked = [i for i in items if i["url"] not in seen]
        if picked:
            busy += 1
            new += [(i, f["name"]) for i in picked]
        else:
            quiet.append((max(items, key=_key) if items else {"title": "-", "url": "-", "date": None}, f["name"]))
        urls = dict.fromkeys(i["url"] for i in sorted(items, key=_key))  # newest last
        kept = [s for s in (old or {}).get("seen", []) if s not in urls]
        state[f["feed"]] = {"seen": (kept + list(urls))[-KEEP:], "checked": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    new.sort(key=lambda r: _key(r[0]), reverse=True)
    md = [f"# watch {top.resolve().name} {now:%Y-%m-%d %H:%M} UTC", "", "## New", ""]
    for i, name in new:
        d, n, t, u = _day(i["date"]), clean(name), clean(i["title"]), clean(i["url"])
        print(f"NEW\t{d}\t{n}\t{t}\t{u}\t{i['first']}")
        md += [f"- {d} {n}: [{t}]({u})"] + ([f"  > {i['first']}"] if i["first"] else [])
    md += ["", "## Quiet feeds, latest item", ""]
    for i, name in quiet:
        d, n, t, u = _day(i["date"]), clean(name), clean(i["title"]), clean(i["url"])
        print(f"LATEST\t{d}\t{n}\t{t}\t{u}")
        md.append(f"- {d} {n}: [{t}]({u})")
    md += ["", "## Failed", ""]
    for name, why in failed:
        print(f"FAIL\t{clean(name)}\t{clean(why)}")
        md.append(f"- {clean(name)}: {clean(why)}")
    (top / "watch").mkdir(parents=True, exist_ok=True)
    stem, n = now.strftime("%Y-%m-%d-%H%M"), 1
    while True:  # never overwrite an earlier check
        path = top / "watch" / (f"{stem}-{n}.md" if n > 1 else f"{stem}.md")
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write("\n".join(md) + "\n")
            break
        except FileExistsError:
            n += 1
    tmp = sp.with_name(sp.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, sp)
    print(f"# {len(new)} new from {busy} feeds, {len(quiet)} quiet, {len(failed)} failed: watch/{path.name}")
    return 1 if failed and not (new or quiet) else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="watch.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add", help="find a venue's feed, verify that it parses, append it to watch.tsv")
    s.add_argument("topic_dir", help="topic folder, such as ~/research/<topic>")
    s.add_argument("url", help="venue URL: tag, user, channel, playlist, blog, repository, arXiv API query or subreddit")
    s.add_argument("name", nargs="?", help="feed name (default: the feed's title)")
    s.set_defaults(func=cmd_add)
    s = sub.add_parser("list", help="print the feeds in watch.tsv")
    s.add_argument("topic_dir", help="topic folder")
    s.set_defaults(func=cmd_list)
    s = sub.add_parser("check", help="print what is new in every feed and write watch/<UTC time>.md")
    s.add_argument("topic_dir", help="topic folder")
    s.add_argument("--days", type=int, default=14, metavar="N",
                   help="on a feed's first check and with --fresh, keep items dated within the last N days (default 14)")
    s.add_argument("--fresh", action="store_true", help="ignore seen items and select by the date window only")
    s.set_defaults(func=cmd_check)
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
