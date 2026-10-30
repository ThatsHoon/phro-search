"""Walk citations and authors through the OpenAlex API (keyless): references, citing works, an author's works.

Usage:
  chain.py find <doi-or-title>          one work for a DOI or W id, else 5 title candidates by citations
  chain.py refs <id-or-doi> [-n 20]     works the given work references (backward, footnote chasing)
  chain.py cites <id-or-doi> [-n 20]    works citing the given work (forward, citation searching)
  chain.py author <name-or-id> [-n 20]  an author's works, most cited first

An id is W123, https://openalex.org/W123, a bare DOI or a doi.org URL; an author id is A123.

Rows, tab-separated: <year> <cited_by_count> <W id> <title> <doi or -> <free pdf url or ->
Other lines, a label and then tab-separated fields:
  # work <W id> <year> <title>                   first line of refs and cites
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
FIELDS = "id,display_name,publication_year,cited_by_count,doi,best_oa_location,open_access"
AUTHOR = "id,display_name,works_count,last_known_institutions"
RATE_LIMITED = "rate limited: the OpenAlex free daily budget may be used up; try tomorrow"
NOTE_NO_MATCH = "# note: no match; try the DOI, or a shorter title without the subtitle."
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


def egress(text):
    """Fail when text holds a forbidden term, or when the term sources cannot be read (fail closed)."""
    try:
        hit = egress_hit(text, egress_terms())
    except Exception as e:
        raise Fail(clean(f"egress: cannot read the forbidden terms: {e}")) from None
    if hit:
        raise Fail(clean(f"egress: '{hit[0]}' is listed in {hit[1]}; use a generic problem statement"))


def get(path, params, missing=None):
    """JSON from the API: 1 s between requests, 2/4/8 s backoff on 429, every failure raised as Fail."""
    global _last
    req = urllib.request.Request(f"{API}{path}?{urllib.parse.urlencode(params)}", headers={"User-Agent": UA})
    delay = 0
    for backoff in (2, 4, 8, None):
        wait = max(delay, _last + 1 - time.monotonic())
        if wait > 0:
            time.sleep(wait)
        try:
            with _opener.open(req, timeout=30) as r:
                body = r.read(CAP + 1)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404 and missing:
                raise Fail(f"not in OpenAlex: {missing}") from None
            if e.code != 429:
                raise Fail(f"http {e.code}") from None
            if backoff is None:
                raise Fail(RATE_LIMITED) from None
            after = e.headers.get("Retry-After") or ""
            delay = int(after) if after.isdecimal() and int(after) <= 60 else backoff
        except (OSError, http.client.HTTPException) as e:
            why = e.reason if isinstance(e, urllib.error.URLError) else e  # ssl.SSLError has a str .reason too
            raise Fail("dns" if isinstance(why, socket.gaierror) else "timeout" if isinstance(why, TimeoutError)
                       else "tls" if isinstance(why, ssl.SSLError) else clean(why, 80)) from None
        finally:
            _last = time.monotonic()
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


def row(w):
    """One result row for a work."""
    pdf = (w.get("best_oa_location") or {}).get("pdf_url") or (w.get("open_access") or {}).get("oa_url")
    doi = str(w.get("doi") or "").removeprefix("https://doi.org/")
    return "\t".join((cell(w.get("publication_year")), cell(w.get("cited_by_count")), cell(short(w.get("id"))),
                      cell(w.get("display_name"), 200), cell(doi), cell(pdf)))


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
    m = re.fullmatch(r"(?:https?://openalex\.org/)?(W\d+)", s, re.I)
    if m:
        return m.group(1).upper()
    m = re.fullmatch(r"(?:https?://(?:dx\.)?doi\.org/|doi:)?(10\.\d{4,9}/\S+)", s, re.I)
    return m and m.group(1)


def work(key):
    """The work for a W id or DOI, with its reference list."""
    path = "/works/" + urllib.parse.quote(key if key[0] == "W" else "doi:" + key, safe="/:")
    return get(path, {"select": FIELDS + ",referenced_works"}, missing=key)


def works(flt, n):
    """The n most cited works that match a filter."""
    reply = get("/works", {"filter": flt, "sort": "cited_by_count:desc", "per-page": n, "select": FIELDS})
    return reply.get("results") or []


def find(q):
    egress(q)
    key = work_key(q)
    show([work(key)] if key else works("title.search:" + q, 5), NOTE_NO_MATCH)


def chain(kind, key, n):
    egress(key)
    w = work(key)
    wid = short(w.get("id"))
    print(f"# work\t{cell(wid)}\t{cell(w.get('publication_year'))}\t{cell(w.get('display_name'), 200)}")
    if kind == "cites":
        rows = works("cites:" + wid, n)
    else:
        ids = [short(u) for u in w.get("referenced_works") or []]
        rows = [r for i in range(0, len(ids), BATCH) for r in works("openalex:" + "|".join(ids[i:i + BATCH]), BATCH)]
        rows = sorted(rows, key=lambda r: -(r.get("cited_by_count") or 0))[:n]
    show(rows, NOTE_EMPTY)


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
    for name, what in (("refs", "works the given work references"), ("cites", "works citing the given work")):
        p = sub.add_parser(name, parents=[limit], help=what + ", most cited first")
        p.add_argument("work", type=work_arg, help="W id, openalex.org URL, DOI or doi.org URL")
    p = sub.add_parser("author", parents=[limit], help="an author's works, most cited first")
    p.add_argument("name", nargs="+", help="author name, or an A id or openalex.org author URL")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "find":
            find(" ".join(args.query))
        elif args.cmd == "author":
            author(" ".join(args.name), args.n)
        else:
            chain(args.cmd, args.work, args.n)
    except Fail as e:
        print(f"FAIL\t{clean(e)}")
        return 1
    except (KeyError, TypeError, AttributeError):  # a reply of an unexpected shape
        print("FAIL\tunexpected reply from the API")
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
