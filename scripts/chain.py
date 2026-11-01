"""Walk citations and authors through the OpenAlex API: a topic's most cited works, references, citing works,
related works, an author's works, legal copies.

Usage:
  chain.py find <doi-or-title>          one work for a DOI or W id, else 5 title candidates by citations
  chain.py refs <id-or-doi> [-n 20]     works the given work references (backward, footnote chasing)
  chain.py cites <id-or-doi> [-n 20] [--sort cited|recent] [--since YEAR]
                                        works citing the given work (forward, citation searching)
  chain.py topic <anchor terms> [--since YEAR] [-n 20]
                                        works whose title or abstract has the terms, most cited first, without
                                        paratext, errata, editorials and retraction notices; --since adds a second
                                        list of the most cited works published in or after that year
  chain.py related <id-or-doi> [-n 20]  works OpenAlex lists as related to the given work, most cited first
  chain.py author <name-or-id> [-n 20]  an author's works, most cited first
  chain.py oa <id-or-doi>               the work's open-access copies, best first

An id is W123, https://openalex.org/W123, a bare DOI or a doi.org URL; an author id is A123.
No key is needed; OPENALEX_API_KEY from the environment is sent when set and never printed.
Requests are 1 s apart. A 429 or a 5xx is retried after 2, 4 and 8 s (after Retry-After when it asks 60 s or less);
a timeout (20 s without an answer) is retried once; any other status is not, nor a 403 or 503 from a bot check. All requests of one run share a deadline of
100 s: no request starts and no retry waits past it.

Rows, tab-separated: <year> <cited_by_count> <W id> <title> <doi or -> <free pdf url or -> <type or -> <venue or ->
  <flags or ->, flags from: retracted, preprint, erratum (also retraction notices), comment (letters, editorials,
  peer reviews, paratext), accepted-copy (an open-access accepted manuscript exists)
oa rows: <published|accepted|submitted|-> <repository|publisher|other> <pdf url or -> <landing url or -> <source or ->
  <license or ->, copies with a PDF link first, then landing pages; in each, published before accepted before
  submitted, and repository copies (arXiv included) first
Other lines, a label and then tab-separated fields:
  # work <W id> <year> <title> <flags or ->      first line of refs, cites, related and oa
  # topic <terms as sent> <N> matches           first line of topic
  # since <YEAR> <N> matches                    before topic's second list
  # author <A id> <name> <institution or -> <N> works
  # other matches <A id> <name> (<institution>)  one field; up to 3 lines after the author line
  # note: ...                                    zero results
  FAIL <reason>                                  an error; exit code 1
"""
import argparse
import http.client
import json
import os
import re
import socket
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "0.4.0"
API = "https://api.openalex.org"
UA = f"Mozilla/5.0 (compatible; phro-search/{VERSION}; +https://github.com/ThatsHoon/phro-search)"
CAP = 10 * 1024 * 1024  # bytes read per API page
BATCH = 50  # ids per openalex: filter
FIELDS = ("id,display_name,publication_year,cited_by_count,doi,best_oa_location,open_access,type,publication_date,"
          "is_retracted,primary_location,locations")
AUTHOR = "id,display_name,works_count,last_known_institutions"
RATE_LIMITED = ("rate limited: the OpenAlex daily budget ($1.000, about 1,000 credits) may be used up; try tomorrow, "
                "or set OPENALEX_API_KEY")
BACKOFF = (2, 4, 8)  # seconds before each retry of a 429 or a 5xx; a timeout is retried once
TIMEOUT = 20  # seconds one request may stall before it counts as a timeout
RETRY_AFTER_CAP = 60  # longest Retry-After honored, in seconds; a longer one gets the backoff
DEADLINE = 100  # seconds for all requests of one run together, under the Bash tool's default 2-minute timeout
BOT_CHECK = (b"just a moment", b"checking your browser", b"captcha", b"verify you are human", b"are you a robot",
             b"attention required", b"challenge-platform", b"/cdn-cgi/challenge", b"ddos-guard")
NOTE_NO_MATCH = "# note: no match; try the DOI, or a shorter title without the subtitle."
NOTE_NO_OA = ("# note: no open-access copy is listed; look for the author's or lab's page, a technical report or an "
              "institutional repository, or ask the user to open the publisher page in a browser.")
NOTE_NO_TOPIC = "# note: no match; try fewer or more general terms, or the field's own words."
NOTE_NO_RELATED = "# note: OpenAlex lists no related works for this one; try chain.py cites or refs."
NOTE_EMPTY = ("# note: 0 results. OpenAlex often lacks citation links for works under about a year old, so this means "
              "unknown, not none: grep the reference section of the downloaded text, or search for works citing the title.")

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
    """An error that ends the run with a FAIL line."""


class _Redirect(urllib.request.HTTPRedirectHandler):
    """Follow 308 like 307 (urllib handles 308 only from Python 3.11)."""
    http_error_308 = urllib.request.HTTPRedirectHandler.http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, 307 if code == 308 else code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirect)
_last = 0.0  # when the previous request ended; one host only, so one timestamp is enough
_end = None  # monotonic time when this run's requests stop; set by main


def left():
    """Seconds until the run deadline; infinite outside a run."""
    return float("inf") if _end is None else _end - time.monotonic()


def bot_check(e):
    """True for a 403 or 503 from a bot check (a wall that no retry passes)."""
    if e.code not in (403, 503):
        return False
    if str((e.headers or {}).get("cf-mitigated", "")).strip().casefold() == "challenge":
        return True
    try:
        body = (e.read(8192) or b"").lower()
    except Exception:  # the error body may be gone or cut; then it is no proof of a wall
        body = b""
    return any(p in body for p in BOT_CHECK)


def retry_wait(e, backoff):
    """Seconds before retrying HTTPError e: its Retry-After when it asks RETRY_AFTER_CAP or less, else backoff."""
    ra = str((e.headers or {}).get("Retry-After") or "").strip()
    return int(ra) if ra.isascii() and ra.isdigit() and int(ra) <= RETRY_AFTER_CAP else backoff


def egress(text):
    """Fail when text holds a forbidden term, or when the term sources cannot be read (fail closed)."""
    try:
        hit = egress_hit(text, egress_terms())
    except Exception as e:
        raise Fail(clean(f"egress: cannot read the forbidden terms: {e}")) from None
    if hit:
        raise Fail(clean(f"egress: '{hit[0]}' is listed in {hit[1]}; use a generic problem statement"))


def get(path, params, missing=None):
    """JSON from the API under the retry policy in the module docstring; every failure raised as Fail."""
    global _last
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        params = {**params, "api_key": key}
    req = urllib.request.Request(f"{API}{path}?{urllib.parse.urlencode(params)}", headers={"User-Agent": UA})
    delay = 0
    timeouts = 0
    for backoff in (*BACKOFF, None):
        wait = max(delay, _last + 1 - time.monotonic())
        if wait > 0:
            time.sleep(wait)
        if left() <= 0:
            raise Fail("run deadline reached")
        try:
            with _opener.open(req, timeout=min(TIMEOUT, max(1, left()))) as r:
                body = r.read(CAP + 1)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404 and missing:
                raise Fail(f"not in OpenAlex: {missing}") from None
            if bot_check(e):
                raise Fail(f"http {e.code}: bot check") from None
            if not (e.code == 429 or 500 <= e.code < 600) or backoff is None:
                raise Fail(RATE_LIMITED if e.code == 429 else f"http {e.code}") from None
            short, delay = f"http {e.code}", retry_wait(e, backoff)
        except (OSError, http.client.HTTPException) as e:
            why = e.reason if isinstance(e, urllib.error.URLError) else e  # ssl.SSLError has a str .reason too
            short = ("dns" if isinstance(why, socket.gaierror) else "timeout" if isinstance(why, TimeoutError)
                     else "tls" if isinstance(why, ssl.SSLError) else clean(why, 80))
            timeouts += short == "timeout"
            if short != "timeout" or backoff is None or timeouts > 1:
                raise Fail(short) from None
            delay = backoff
        finally:
            _last = time.monotonic()
        if delay > left():
            raise Fail(f"{short}; run deadline reached")
    if len(body) > CAP:
        raise Fail("too large")
    try:
        return json.loads(body)
    except ValueError:
        raise Fail("not json") from None


def cell(v, cap=500):
    """A printable field, or - when empty."""
    return clean("" if v is None else v, cap) or "-"


def short(url):
    """The id at the end of an OpenAlex URL."""
    return str(url or "").rsplit("/", 1)[-1]


OA_RANKS = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2}


def oa_kind(loc):
    """repository (arXiv included), publisher or other, for one OpenAlex location."""
    src = loc.get("source") or {}
    urls = f"{loc.get('pdf_url') or ''} {loc.get('landing_page_url') or ''}"
    if src.get("type") == "repository" or re.search(r"//(?:[\w-]+\.)*arxiv\.org/", urls):
        return "repository"
    return "publisher" if src.get("type") in ("journal", "conference", "book series", "ebook platform") else "other"


def oa_order(w):
    """The open-access locations of an OpenAlex work, best first: those with a PDF link before those with only a
    landing page (often a record or abstract page); within each, published, accepted, submitted, then unknown
    versions, and repository copies (arXiv included) before other hosts and publisher pages, which often bot-check."""
    kinds = {"repository": 0, "other": 1, "publisher": 2}
    locs = [loc for loc in w.get("locations") or [] if isinstance(loc, dict) and loc.get("is_oa")
            and (loc.get("pdf_url") or loc.get("landing_page_url"))]
    return sorted(locs, key=lambda loc: (not loc.get("pdf_url"), OA_RANKS.get(loc.get("version"), 3), kinds[oa_kind(loc)]))


def flags(w):
    """What the reader must know before relying on a work, or -."""
    kind = w.get("type")
    out = ["retracted"] * bool(w.get("is_retracted")) + ["preprint"] * (kind == "preprint")
    out += ["erratum"] * (kind in ("erratum", "retraction")) + ["comment"] * (kind in ("letter", "editorial", "peer-review", "paratext"))
    out += ["accepted-copy"] * any(loc.get("version") == "acceptedVersion" for loc in oa_order(w))
    return ",".join(out) or "-"


def row(w):
    """One result row for a work."""
    pdf = (w.get("best_oa_location") or {}).get("pdf_url") or (w.get("open_access") or {}).get("oa_url")
    doi = str(w.get("doi") or "").removeprefix("https://doi.org/")
    venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
    return "\t".join((cell(w.get("publication_year")), cell(w.get("cited_by_count")), cell(short(w.get("id"))),
                      cell(w.get("display_name"), 200), cell(doi), cell(pdf), cell(w.get("type")), cell(venue, 120), flags(w)))


def show(rows, note):
    for w in rows:
        print(row(w))
    if not rows:
        print(note)


def inst(a):
    """Last known institution of an author record, or -."""
    return cell(((a.get("last_known_institutions") or [{}])[0]).get("display_name"))


def work_key(s):
    """'W123' or the bare DOI when s is a work id, an openalex.org URL, a DOI (doi: prefix allowed) or a doi.org URL; else None."""
    s = s.strip()
    if re.match(r"https?://", s, re.I):
        s = urllib.parse.unquote(s)  # a doi.org link may carry its DOI percent-encoded
    m = re.fullmatch(r"(?:https?://openalex\.org/)?(W\d+)", s, re.I)
    if m:
        return m.group(1).upper()
    m = re.fullmatch(r"(?:https?://(?:dx\.)?doi\.org/|doi:)?(10\.\d{4,9}/\S+)", s, re.I)
    return m and m.group(1)


def work(key):
    """The work for a W id or DOI, with its reference list and related works."""
    path = "/works/" + urllib.parse.quote(key if key[0] == "W" else "doi:" + key, safe="/:")
    return get(path, {"select": FIELDS + ",referenced_works,related_works"}, missing=key)


def works(flt, n, sort="cited_by_count:desc"):
    """The first n works that match a filter, most cited first unless sort says otherwise."""
    reply = get("/works", {"filter": flt, "sort": sort, "per-page": n, "select": FIELDS})
    return reply.get("results") or []


def title_query(q):
    """A title made safe for the title.search filter: commas and | (filter syntax) become spaces, a leading !
    (negation) is dropped, and upper-case AND, OR and NOT (boolean operators) are lowercased."""
    q = re.sub(r"[,|]", " ", q).strip().lstrip("!")
    return " ".join(re.sub(r"\b(AND|OR|NOT)\b", lambda m: m.group(1).lower(), q).split())


def find(q):
    egress(q)
    egress(title_query(q))  # cleaning turns commas and pipes into spaces, which can form a listed term
    key = work_key(q)
    show([work(key)] if key else works("title.search:" + title_query(q), 5), NOTE_NO_MATCH)


SKIP_TYPES = ("paratext", "erratum", "editorial", "retraction")  # not works a field cites as its canon


def topic(terms, n, since=None):
    egress(terms)
    q = title_query(terms)
    egress(q)  # cleaning turns commas and pipes into spaces, which can form a listed term
    base = "title_and_abstract.search:" + q + "".join(",type:!" + k for k in SKIP_TYPES)
    lists = [("# topic\t" + cell(q, 200), base)]
    if since:
        lists.append(("# since\t" + since, base + f",from_publication_date:{since}-01-01"))
    for label, flt in lists:
        reply = get("/works", {"filter": flt, "sort": "cited_by_count:desc", "per-page": n, "select": FIELDS})
        print(f"{label}\t{cell((reply.get('meta') or {}).get('count'))} matches")
        show([w for w in reply.get("results") or [] if w.get("type") not in SKIP_TYPES], NOTE_NO_TOPIC)


def header(w):
    print(f"# work\t{cell(short(w.get('id')))}\t{cell(w.get('publication_year'))}\t{cell(w.get('display_name'), 200)}\t{flags(w)}")


def chain(kind, key, n, sort="cited", since=None):
    egress(key)
    w = work(key)
    wid = short(w.get("id"))
    header(w)
    if kind == "cites":
        flt = "cites:" + wid + (f",from_publication_date:{since}-01-01" if since else "")
        rows = works(flt, n, "publication_date:desc" if sort == "recent" else "cited_by_count:desc")
    else:
        ids = [short(u) for u in w.get("referenced_works" if kind == "refs" else "related_works") or []]
        rows = [r for i in range(0, len(ids), BATCH) for r in works("openalex:" + "|".join(ids[i:i + BATCH]), BATCH)]
        rows = sorted(rows, key=lambda r: -(r.get("cited_by_count") or 0))[:n]
    show(rows, NOTE_EMPTY if kind != "related" else NOTE_NO_RELATED)


def oa(key):
    egress(key)
    w = work(key)
    header(w)
    names = {"publishedVersion": "published", "acceptedVersion": "accepted", "submittedVersion": "submitted"}
    locs = oa_order(w)
    for loc in locs:
        print("\t".join((names.get(loc.get("version"), "-"), oa_kind(loc), cell(loc.get("pdf_url")),
                         cell(loc.get("landing_page_url")), cell((loc.get("source") or {}).get("display_name"), 120),
                         cell(loc.get("license")))))
    if not locs:
        print(NOTE_NO_OA)


def author(name, n):
    egress(name)
    m = re.fullmatch(r"(?:https?://openalex\.org/)?(A\d+)", name.strip(), re.I)
    if m:
        aid = m.group(1).upper()
        found = [get("/authors/" + aid, {"select": AUTHOR}, missing=aid)]
    else:
        found = get("/authors", {"search": name, "per-page": 4, "select": AUTHOR}).get("results") or []
    if not found:
        print("# note: no author matches; check the spelling, or pass an A id.")
        return
    a = found[0]
    aid = short(a.get("id"))
    print("\t".join(("# author", cell(aid), cell(a.get("display_name")), inst(a), cell(a.get("works_count")) + " works")))
    for o in found[1:4]:
        print(f"# other matches\t{cell(short(o.get('id')))} {cell(o.get('display_name'))} ({inst(o)})")
    show(works("author.id:" + aid, n), "# note: no works listed for that author.")


def count(s):
    if not s.isdecimal() or not 1 <= int(s) <= 200:
        raise argparse.ArgumentTypeError("must be a number from 1 to 200")
    return int(s)


def year(s):
    if not re.fullmatch(r"[12]\d{3}", s):
        raise argparse.ArgumentTypeError("must be a four-digit year")
    return s


def work_arg(s):
    key = work_key(s)
    if not key:
        raise argparse.ArgumentTypeError("not an OpenAlex work id or DOI (use find for a title)")
    return key


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    limit = argparse.ArgumentParser(add_help=False)
    limit.add_argument("-n", type=count, default=20, metavar="N", help="rows to print, 1 to 200 (default 20)")
    p = sub.add_parser("find", help="resolve a DOI or W id, or list 5 title candidates")
    p.add_argument("query", nargs="+", help="a DOI, a doi.org URL, a W id, or the words of a title")
    p = sub.add_parser("topic", parents=[limit], help="the most cited works whose title or abstract has the terms")
    p.add_argument("terms", nargs="+", help="anchor terms of the field")
    p.add_argument("--since", type=year, metavar="YEAR", help="add a list of the most cited works published in or after this year")
    for name, what in (("refs", "works the given work references"), ("cites", "works citing the given work"),
                       ("related", "works OpenAlex lists as related to the given work")):
        p = sub.add_parser(name, parents=[limit], help=what + ", most cited first")
        p.add_argument("work", type=work_arg, help="W id, openalex.org URL, DOI or doi.org URL")
        if name == "cites":
            p.add_argument("--sort", choices=("cited", "recent"), default="cited",
                           help="cited: most cited first (default); recent: newest first")
            p.add_argument("--since", type=year, metavar="YEAR", help="only works published in or after this year")
    p = sub.add_parser("oa", help="the work's open-access copies, best first")
    p.add_argument("work", type=work_arg, help="W id, openalex.org URL, DOI or doi.org URL")
    p = sub.add_parser("author", parents=[limit], help="an author's works, most cited first")
    p.add_argument("name", nargs="+", help="author name, or an A id or openalex.org author URL")
    args = ap.parse_args(argv)
    global _end
    _end = time.monotonic() + DEADLINE
    try:
        if args.cmd == "find":
            find(" ".join(args.query))
        elif args.cmd == "author":
            author(" ".join(args.name), args.n)
        elif args.cmd == "topic":
            topic(" ".join(args.terms), args.n, args.since)
        elif args.cmd == "oa":
            oa(args.work)
        else:
            chain(args.cmd, args.work, args.n, getattr(args, "sort", "cited"), getattr(args, "since", None))
    except Fail as e:
        print(f"FAIL\t{clean(e)}")
        return 1
    except (KeyError, TypeError, AttributeError):  # a reply of an unexpected shape
        print("FAIL\tunexpected reply from the API")
        return 1
    finally:
        _end = None
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
