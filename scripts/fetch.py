"""Download one original source into a research topic's sources/ folder; refuse anything that is not the real thing.

Usage:
  fetch.py <sources_dir> <name> <url-or-path>

  name         file stem matching ^[a-z0-9][a-z0-9.-]*$, for example bates-1989-berrypicking
  url-or-path  an http(s) URL, a DOI (bare, doi: or a doi.org URL), or a page or PDF saved from a
               browser (same checks)

Judged by content, not extension or status: walls, error pages, short bodies and HTML posing
as a PDF are refused. Readable copy: <name>.txt for a PDF (its text in reading order, so a
column's sentences stay together) and for plain text, <name>.layout.txt for a PDF's text in page
layout (table rows kept; none after OCR), <name>.md for HTML, Markdown, arXiv HTML and YouTube captions; a PDF is
kept as <name>.pdf. An arXiv link is read from its HTML version first and from the PDF when that
is missing, damaged or short. A DOI tries the open-access copies OpenAlex lists (PDF links before
landing pages; then published, accepted, submitted; repository copies first) before the publisher's page; the
lookup costs no OpenAlex credits, and OPENALEX_API_KEY is sent when set. Nothing is written on
FAIL, and an existing <name>.* is never overwritten.

A dead public page (http 404 or 410, a DNS or TLS failure, a timeout after its retries) is taken from the
Wayback Machine: its availability API names the closest snapshot, which is read with the id_ flag, so the
original bytes come back and get the same checks. Never for 401, 403, 451, a bot check or a wall page, nor for
a DOI's copies or publisher page. Every URL asked, the API's and the snapshot's included, and every redirect is
checked against the forbidden terms.

Requests: a 429, a 5xx or a timeout is retried after 2, 4 and 8 s (after Retry-After when it asks 60 s or less);
any other status is not, nor a 403 or 503 from a bot check, which is a wall. All requests of one run share a
deadline of 100 s: no request starts and no retry waits past it.

Every OK that downloads adds a row to <sources_dir>/index.tsv: name, url, final, fetched, published, modified,
extraction, version, marks, files. A source already fetched from the same URL, DOI or arXiv id is
reused: nothing is downloaded, and the OK line names the earlier file with the mark reused. A
taken name whose row holds another URL fails and names that URL. For an archived copy, final is the snapshot's
URL and published reads "archived <YYYY-MM-DD>", the snapshot's date, after the page's own date when it states one
("2019-05-01, archived 2020-03-04"): the copy shows the page as it stood on that day.

Output, one tab-separated line:
  OK <name> <file> <chars> <first line> [<marks>]
  FAIL <name> <reason>                                  exit code 1
A reason for a missing tool (pdftotext, pdftoppm, tesseract, yt-dlp) ends in a short install hint for this OS.
Marks, comma-separated: ocr, auto-captions, arxiv-html; published-copy, accepted-copy, submitted-copy
or copy (no version stated) for an open-access copy of a DOI, with landing-page when it came from a
landing page rather than a PDF link; archived-copy for a dead page read from its Wayback snapshot;
retracted when OpenAlex marks the work retracted; unchecked when OpenAlex could not be asked, so neither
copies nor a retraction were checked; reused for a source fetched before (a reuse adds no index row).
"""
import argparse, datetime, html.parser, http.client, json, os, re, shutil, socket, ssl, subprocess, sys, tempfile, time
import unicodedata, urllib.error, urllib.parse, urllib.request
from pathlib import Path

VERSION = "0.4.0"
ARXIV = "https://arxiv.org"
OPENALEX = "https://api.openalex.org"
DOI = "https://doi.org"
WAYBACK = "https://archive.org"  # the Wayback Machine's availability API
ARCHIVE = "https://web.archive.org"  # its snapshots
RAW = "https://raw.githubusercontent.com"
UA = f"Mozilla/5.0 (compatible; phro-search/{VERSION}; +https://github.com/ThatsHoon/phro-search)"
ACCEPT = "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.8,*/*;q=0.5"
CAP = 40 * 1024 * 1024  # bytes per source document
BACKOFF = (2, 4, 8)  # seconds before each retry of a 429, a 5xx or a timeout
RETRY_AFTER_CAP = 60  # longest Retry-After honored, in seconds; a longer one gets the backoff
DEADLINE = 100  # seconds for all requests of one run together, under the Bash tool's default 2-minute timeout
BOT_CHECK = (b"just a moment", b"checking your browser", b"captcha", b"verify you are human", b"are you a robot",
             b"attention required", b"challenge-platform", b"/cdn-cgi/challenge", b"ddos-guard")
SPACING = 1.0  # seconds between requests to one host
MIN_WEIGHTED = 1500  # shortest body kept, in weighted characters
WALL_SCAN = 8000  # bodies under this many weighted characters are searched for wall phrases
TEXT_LAYER = 200  # fewer non-space characters than this means a PDF has no text layer
LAYOUT_CELL = 500  # a longer table cell with line breaks is page layout and stays as text, not a row cell
WALL_PHRASES = (
    "access denied", "just a moment", "checking your browser", "enable javascript and cookies",
    "verify you are human", "are you a robot", "captcha", "sign in to continue", "log in to continue",
    "please log in", "subscribe to continue reading", "page not found", "404 not found", "403 forbidden",
    "this page isn't available", "request blocked",
    "로그인이 필요", "로그인 후 이용", "페이지를 찾을 수 없", "접근이 거부", "권한이 없습니다",
    "ログインしてください", "ページが見つかりません", "アクセスが拒否", "お探しのページは見つかりませんでした",
)
# Phrases on an arXiv HTML page whose conversion failed or broke off; the PDF is used instead.
ARXIV_NOTICES = ("conversion to html had a fatal error", "html is not available for the source", "no html for")
HTTP_REASONS = {
    401: "http 401: login required",
    403: "http 403: open it in a browser and pass the saved file path",
    404: "http 404",
    429: "http 429: still rate limited after 3 retries",
    503: "http 503: still unavailable after 3 retries",
    451: "http 451: unavailable for legal reasons",
}
INDEX = "index.tsv"  # one row per source in sources/: what was fetched, from where, when and how
INDEX_HEAD = ("name", "url", "final", "fetched", "published", "modified", "extraction", "version", "marks", "files")
# Meta tag names that state when a page was published or last changed, most specific first.
META_PUBLISHED = ("citation_publication_date", "citation_date", "article:published_time", "og:published_time",
                  "datepublished", "dc.date.issued", "dcterms.issued", "dc.date", "dcterms.created", "citation_online_date", "date")
META_MODIFIED = ("article:modified_time", "og:updated_time", "datemodified", "dcterms.modified", "last-modified")
LOCAL_TYPES = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown"}
TEXT_TYPES = ("text/plain", "text/markdown", "text/x-markdown")
DROP = {"script", "style", "noscript", "svg", "template", "iframe", "form", "nav", "footer"}
BLOCK = {"div", "section", "article", "main", "header", "aside", "blockquote", "ul", "ol", "dl", "dt", "dd",
         "figure", "figcaption"}
HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
CJK = re.compile(r"[\U00001100-\U000011ff\U00003040-\U000030ff\U00003130-\U0000318f\U000031f0-\U000031ff"
                 r"\U00003400-\U00004dbf\U00004e00-\U00009fff\U0000ac00-\U0000d7a3\U0000f900-\U0000faff\U0000ff66-\U0000ff9f]")
CUE = re.compile(r"(?:(\d+):)?(\d\d):(\d\d)[.,]\d+\s+-->")

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
    """The reason on a FAIL line."""


class Dead(Fail):
    """A public page that is gone or out of reach (http 404 or 410, DNS, TLS, timeout): the Wayback Machine may hold it."""


def refused(url):
    """The FAIL reason for a host that is never fetched, else None."""
    host = (urllib.parse.urlsplit(url).hostname or "").rstrip(".")
    if any(host == d or host.endswith("." + d) for d in ("x.com", "twitter.com")):
        return "x.com is not fetched: login wall"
    if any(host == d or host.endswith("." + d) for d in ("reddit.com", "redd.it")):
        return "reddit.com is not fetched: robots rules"
    return None


class Handler(urllib.request.HTTPRedirectHandler):
    """Spaces requests per host, refuses redirects to refused hosts, follows 308 like 307 (urllib does from 3.11)."""
    last = {}

    def http_request(self, req):
        wait = self.last.get(req.host, float("-inf")) + SPACING - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last[req.host] = time.monotonic()
        return req

    https_request = http_request
    http_error_308 = urllib.request.HTTPRedirectHandler.http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if reason := refused(newurl):
            raise Fail(reason)
        egress(newurl)
        return super().redirect_request(req, fp, 307 if code == 308 else code, msg, headers, newurl)


OPENER = urllib.request.build_opener(Handler)
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


def uri(url):
    """The URL with non-ASCII characters and spaces percent-encoded and a non-ASCII host in IDNA form."""
    u = urllib.parse.urlsplit(url)
    netloc = u.netloc
    if not netloc.isascii():
        try:
            netloc = netloc.encode("idna").decode("ascii")
        except UnicodeError:
            raise Fail("bad host name") from None
    esc = lambda s: re.sub(r"[^\x21-\x7e]+", lambda m: urllib.parse.quote(m.group()), s)
    return urllib.parse.urlunsplit((u.scheme, netloc, esc(u.path), esc(u.query), esc(u.fragment)))


def get(url):
    """(body, content type, final URL) of one GET; every failure raised as Fail with a short reason."""
    req = urllib.request.Request(uri(url), headers={"User-Agent": UA, "Accept": ACCEPT})
    for backoff in (*BACKOFF, None):
        if left() <= 0:
            raise Fail("run deadline reached")
        try:
            with OPENER.open(req, timeout=min(30, max(1, left()))) as r:
                body = r.read(CAP + 1)
                if len(body) > CAP:
                    raise Fail("too large: over 40 MB")
                return body, r.headers.get("Content-Type", ""), r.geturl()
        except urllib.error.HTTPError as e:
            if bot_check(e):
                raise Fail(f"http {e.code}: bot check; open it in a browser and pass the saved file path") from None
            if not (e.code == 429 or 500 <= e.code < 600) or backoff is None:
                raise (Dead if e.code in (404, 410) else Fail)(HTTP_REASONS.get(e.code, f"http {e.code}")) from None
            short, wait = f"http {e.code}", retry_wait(e, backoff)
        except (OSError, http.client.HTTPException) as e:
            why = e.reason if isinstance(e, urllib.error.URLError) else e
            short = ("dns" if isinstance(why, socket.gaierror) else "tls" if isinstance(why, ssl.SSLError)
                     else "timeout" if isinstance(why, TimeoutError) else f"network: {why}")
            if short != "timeout" or backoff is None:
                raise (Dead if short in ("dns", "tls", "timeout") else Fail)(short) from None
            wait = backoff
        if wait > left():
            raise Fail(f"{short}; run deadline reached")
        time.sleep(wait)


def run(cmd):
    """Stdout of an external tool as text; Fail when it times out or exits non-zero."""
    tool = Path(cmd[0]).stem
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=900)
    except subprocess.TimeoutExpired:
        raise Fail(f"{tool} timed out") from None
    if r.returncode:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise Fail(f"{tool} failed: {err[-1] if err else r.returncode}")
    return r.stdout.decode("utf-8", "replace")


def decode(data, ctype, meta=False):
    """Text in the charset from Content-Type, else from <meta> when meta is set, else UTF-8."""
    m = re.search(r"charset=[\"']?([\w.:-]+)", ctype, re.I) or (
        meta and re.search(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", data[:8192], re.I))
    charset = m.group(1) if m else "utf-8"
    try:
        return data.decode(charset.decode() if isinstance(charset, bytes) else charset)
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="replace")


def weighted(text):
    """Non-whitespace characters, with Hangul, kana and CJK ideographs counting 3 each."""
    return len("".join(text.split())) + 2 * len(CJK.findall(text))


def check(title, text, length=True):
    """Fail on a wall phrase in the title or in a short body, then (unless length is False) on a short body."""
    w = weighted(text)
    hays = [" ".join(s.translate(_QUOTES).split()).casefold() for s in (title, text if w < WALL_SCAN else "")]
    hit = next((p for p in WALL_PHRASES for h in hays if p in h), None)
    if hit:
        raise Fail(f"wall: {hit}")
    if length and w < MIN_WEIGHTED:
        raise Fail(f"too short: {w} weighted characters (minimum {MIN_WEIGHTED})")


class Markdown(html.parser.HTMLParser):
    """Markdown of the root elements (article, main or body; None for the whole page) and the page title."""

    def __init__(self, base, root):
        super().__init__()
        self.base, self.root, self.out, self.title = base, root, [], ""
        self.depth = 0 if root else 1  # open root elements
        self.ctx = 0  # open article or main elements, whose <header> is content
        self.skip = None  # [tag, depth] of the dropped element being skipped
        self.pre = self.intitle = 0
        self.link = None  # (index in out, href) of the open link
        self.tables = []  # per open table: [cells of the open row, index in out where the open cell starts]

    def handle_starttag(self, tag, attrs):
        if self.skip:
            self.skip[1] += tag == self.skip[0]
            return
        # the whole-page pass keeps <form>: some sites wrap the entire body in one form
        if tag in DROP and (self.root or tag != "form") or tag == "header" and not self.ctx:
            self.skip = [tag, 1]
            return
        self.ctx += tag in ("article", "main")
        self.depth += tag == self.root
        self.intitle |= tag == "title"
        if not self.depth:
            return
        out, tables = self.out, self.tables
        if tag in HEADINGS:
            out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            out.append("\n- ")
        elif tag == "pre":
            out.append("\n\n```\n")
            self.pre += 1
        elif tag == "code" and not self.pre:
            out.append("`")
        elif tag == "a" and self.link is None and not self.pre and dict(attrs).get("href"):
            self.link = (len(out), dict(attrs)["href"])
        elif tag == "table":
            tables.append([None, None])
        elif tag == "tr" and tables:
            self.end_row()
            tables[-1][0] = []
        elif tag in ("td", "th") and tables and tables[-1][0] is not None:
            self.end_cell()
            tables[-1][1] = len(out)
        elif tag == "p":
            out.append("\n\n")
        elif tag in BLOCK or tag == "br":
            out.append("\n")

    def handle_endtag(self, tag):
        if self.skip:
            self.skip[1] -= tag == self.skip[0]
            if not self.skip[1]:
                self.skip = None
            return
        if tag == "title":
            self.intitle = 0
        if self.depth:
            if tag in HEADINGS or tag == "p":
                self.out.append("\n\n")
            elif tag == "pre" and self.pre:
                self.out.append("\n```\n\n"["".join(self.out[-1:]).endswith("\n"):])
                self.pre -= 1
            elif tag == "code" and not self.pre:
                self.out.append("`")
            elif tag == "a" and self.link:
                self.end_link()
            elif tag in ("td", "th"):
                self.end_cell()
            elif tag == "tr":
                self.end_row()
            elif tag == "table" and self.tables:
                self.end_row()
                self.tables.pop()
                self.out.append("\n")
            elif tag in BLOCK:
                self.out.append("\n")
        if tag == self.root and self.depth:
            self.depth -= 1
        if tag in ("article", "main") and self.ctx:
            self.ctx -= 1

    def handle_data(self, data):
        if self.skip:
            return
        if self.intitle:
            self.title += data
        elif self.depth:
            self.out.append(data if self.pre else re.sub(r"\s+", " ", data))

    def end_link(self):
        (start, href), self.link = self.link, None
        text = "".join(self.out[start:])
        url = urllib.parse.urljoin(self.base, href.strip())
        if text.strip() and "\n" not in text and url.startswith(("http://", "https://")):
            self.out[start:] = [" " * text.startswith(" ") + f"[{text.strip()}]({url})" + " " * text.endswith(" ")]

    def end_cell(self):
        if self.tables and self.tables[-1][1] is not None:
            row = self.tables[-1]
            text = "".join(self.out[row[1]:])
            if "\n" not in text.strip() or len(text) <= LAYOUT_CELL:
                row[0].append(" ".join(text.split()))
                del self.out[row[1]:]
            row[1] = None

    def end_row(self):
        self.end_cell()
        if self.tables and any(self.tables[-1][0] or ()):
            self.out.append("\n| " + " | ".join(self.tables[-1][0]) + " |")
        if self.tables:
            self.tables[-1][0] = None


def tidy(md):
    """Lines stripped outside code fences, a lone list marker joined to its text, blank runs cut to one."""
    out, fence = [], False
    for line in md.split("\n"):
        if line.strip() == "```":
            fence = not fence
        line = line.rstrip() if fence else line.strip()
        if out and out[-1] == "-" and line and not fence:
            out[-1] = "- " + line
        elif line or out and out[-1] not in ("", "-"):
            out.append(line)
    return "\n".join(out).strip() + "\n"


def html_md(data, ctype, base):
    """(title, Markdown) of a page: its article, else main, else body, the first one long enough to keep."""
    page = decode(data, ctype, meta=True)
    for root in ("article", "main", "body", None):
        p = Markdown(base, root)
        p.feed(page)
        p.close()
        md = tidy("".join(p.out))
        if weighted(md) >= MIN_WEIGHTED:
            break
    return " ".join(p.title.split()), md


INSTALL = {  # tool: (Windows, macOS, Linux) command; Linux names the Debian and Ubuntu package
    "poppler": ("scoop install poppler", "brew install poppler", "sudo apt install poppler-utils"),
    "tesseract": ("winget install UB-Mannheim.TesseractOCR", "brew install tesseract", "sudo apt install tesseract-ocr"),
    "yt-dlp": ("winget install yt-dlp.yt-dlp", "brew install yt-dlp", "pipx install yt-dlp"),
}


def install_hint(*tools):
    """A short hint to install the tools on this OS, for a missing-tool FAIL line or note."""
    os_ = 0 if sys.platform.startswith(("win", "cygwin", "msys")) else 1 if sys.platform == "darwin" else 2
    cmds = [INSTALL[t][os_] for t in tools]
    if os_ == 1:  # one brew call takes several formulae
        cmds = ["brew install " + " ".join(c.split()[-1] for c in cmds)]
    return "install: " + "; ".join(cmds)


def pdf_text(work, data):
    """(reading-order text, layout text) of a PDF's text layer through pdftotext, form feeds between pages.
    Reading order keeps each column's sentences together, so quotes and grep use it; the layout copy keeps table rows."""
    exe = shutil.which("pdftotext")
    if not exe:
        raise Fail("missing tool: pdftotext (poppler or Xpdf); " + install_hint("poppler"))
    (work / "in.pdf").write_bytes(data)
    out = []
    for flags, name in (([], "out.txt"), (["-layout"], "layout.txt")):
        (work / name).unlink(missing_ok=True)  # never read an earlier copy's text
        run([exe, *flags, "-enc", "UTF-8", str(work / "in.pdf"), str(work / name)])
        out.append((work / name).read_text(encoding="utf-8", errors="replace") if (work / name).is_file() else "")
    return tuple(out)


def ocr(work):
    """OCR text of work/in.pdf, pages joined by form feeds."""
    # ponytail: renders every page before OCR, so temp space grows with page count; render page ranges if books matter
    for old in work.glob("page-*.png"):
        old.unlink()
    run([shutil.which("pdftoppm"), "-r", "300", "-png", str(work / "in.pdf"), str(work / "page")])
    tess = shutil.which("tesseract")
    have = run([tess, "--list-langs"]).split()
    langs = "+".join(["eng"] + [x for x in ("kor", "jpn") if x in have])
    pages = sorted(work.glob("page-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    return "\f".join(run([tess, str(p), "stdout", "-l", langs]) for p in pages)


def got(files, text, extraction, marks=(), **info):
    """What reading one source gives: files by suffix, readable text, how the text was made, marks and provenance."""
    return {"files": files, "text": text, "extraction": extraction, "marks": [m for m in marks if m],
            **{k: info.get(k) or "-" for k in ("final", "published", "modified", "version")}}


def day(s):
    """YYYY-MM-DD, YYYY-MM or YYYY from the start of a stated date, or ''."""
    m = re.match(r"(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?", str(s).strip())
    if not m or not 1900 <= int(m[1]) <= 2100:
        return ""
    return "-".join([m[1]] + [f"{int(x):02d}" for x in m.groups()[1:] if x])


def html_dates(data, ctype):
    """(published, modified) as a page states them: meta tags, then JSON-LD, then a <time> element; '' when absent."""
    page = decode(data[:400000], ctype, meta=True)
    meta = {}
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        attrs = {k.lower(): a or b or c for k, a, b, c in re.findall(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", tag)}
        key = (attrs.get("name") or attrs.get("property") or attrs.get("itemprop") or "").lower()
        if key and attrs.get("content"):
            meta.setdefault(key, attrs["content"])
    found = []
    for keys, ld in ((META_PUBLISHED, "datePublished"), (META_MODIFIED, "dateModified")):
        stated = [meta.get(k) for k in keys] + re.findall(rf'"{ld}"\s*:\s*"([^"]+)"', page)
        if ld == "datePublished":
            stated += re.findall(r"<time\b[^>]*\bdatetime\s*=\s*[\"']?([^\"'\s>]+)", page, re.I)[:1]
        found.append(next((d for d in map(day, filter(None, stated)) if d), ""))
    return tuple(found)


def pdf_dates(data):
    """(created, modified) from a PDF's info dictionary or XMP metadata, as YYYY-MM-DD; '' when absent."""
    found = []
    for info, xmp in ((rb"/CreationDate\s*\(\s*D:(\d{4})(\d{2})?(\d{2})?", rb"xmp:CreateDate[>=\"'\s]+(\d{4})-?(\d{2})?-?(\d{2})?"),
                      (rb"/ModDate\s*\(\s*D:(\d{4})(\d{2})?(\d{2})?", rb"xmp:ModifyDate[>=\"'\s]+(\d{4})-?(\d{2})?-?(\d{2})?")):
        hits = list(re.finditer(info, data)) or list(re.finditer(xmp, data))  # an incremental update appends its info last
        found.append(day("-".join(x.decode() for x in hits[-1].groups() if x)) if hits else "")
    return tuple(found)


def convert(work, data, ctype, base, paths, want_pdf=False):
    """What a downloaded body gives (see got), after the checks; an HTML body fails when a PDF was asked for."""
    mime = ctype.split(";")[0].strip().lower()
    if b"%PDF-" in data[:1024]:
        created, modified = pdf_dates(data)
        text, layout = pdf_text(work, data)
        if len("".join(text.split())) < TEXT_LAYER:
            lack = [t for t, exe in (("poppler", "pdftoppm"), ("tesseract", "tesseract")) if not shutil.which(exe)]
            if lack:
                raise Fail("no text layer, and OCR needs pdftoppm and tesseract; " + install_hint(*lack))
            text = ocr(work)
            check("", text)
            return got({".pdf": data, ".txt": text}, text, "ocr", ["ocr"], final=base, published=created, modified=modified)
        check("", text)
        return got({".pdf": data, ".txt": text, ".layout.txt": layout}, text, "pdftotext",
                   final=base, published=created, modified=modified)
    if re.search(rb"<!doctype html|<(?:html|head|body)\b", data[:4096], re.I):
        title, text = html_md(data, ctype, base)
        if want_pdf or "pdf" in mime or any(p.endswith(".pdf") for p in paths):
            raise Fail(f"expected PDF, got an HTML page: {title or 'no title'}")
        check(title, text)
        published, modified = html_dates(data, ctype)
        return got({".md": text}, text, "html", final=base, published=published, modified=modified)
    if mime in TEXT_TYPES:
        text = decode(data, ctype)
        check("", text)
        md = "markdown" in mime or any(p.endswith((".md", ".markdown")) for p in paths)
        return got({".md" if md else ".txt": text}, text, "text", final=base)
    raise Fail(f"unknown content: {mime or 'no content type'}")


def pick(info):
    """(language, automatic) of the caption track to fetch: manual over automatic, the original language first."""
    manual = [k for k in info.get("subtitles") or {} if k != "live_chat"]
    asr = [k for k in info.get("automatic_captions") or {} if k.endswith("-orig")]  # untranslated speech tracks
    orig = (info.get("language") or "".join(asr[:1])).split("-")[0]
    tracks = manual or asr
    return next((k for k in tracks if k.split("-")[0] == orig), "".join(tracks[:1]) or None), not manual


def vtt_lines(vtt):
    """WebVTT as '[mm:ss] text' lines ([h:mm:ss] past an hour), tags stripped, rolling repeats dropped."""
    out, prev, cur, stamp = [], [], [], None
    for line in vtt.splitlines() + [""]:
        m = CUE.match(line.strip())
        if stamp and (m or not line):
            out += [f"{stamp} {x}" for x in cur if x not in prev]
            prev, cur, stamp = cur, [], None
        if m:
            t = int(m[1] or 0) * 3600 + int(m[2]) * 60 + int(m[3])
            stamp = f"[{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}]" if t >= 3600 else f"[{t // 60:02d}:{t % 60:02d}]"
        elif stamp:
            x = " ".join(html.unescape(re.sub(r"<[^>]*>", "", line)).split())
            if x:
                cur.append(x)
    return out


def captions(work, url):
    """What a YouTube video's captions give, through yt-dlp, without downloading the video."""
    exe = shutil.which("yt-dlp")
    if not exe:
        raise Fail("missing tool: yt-dlp; " + install_hint("yt-dlp"))
    base = [exe, "--ignore-config", "--no-playlist", "--no-warnings", "--skip-download"]
    info = json.loads(run(base + ["-J", url]))
    lang, auto = pick(info)
    if lang:
        run(base + ["--write-auto-subs" if auto else "--write-subs", "--sub-langs", re.escape(lang),
                    "--sub-format", "vtt", "-P", str(work), "-o", "cap.%(ext)s", url])
    vtt = next(work.glob("cap*.vtt"), None)
    lines = vtt_lines(vtt.read_text(encoding="utf-8", errors="replace")) if vtt else []
    if not lines:
        raise Fail("no captions")
    title = " ".join(str(info.get("title") or "").split())
    text = (f"# {title}\n\n" if title else "") + "\n".join(lines) + "\n"
    check(title, text, length=False)
    uploaded = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", str(info.get("upload_date") or ""))
    return got({".md": text}, text, "captions", ["auto-captions" if auto else ""], final=url,
               published="-".join(uploaded.groups()) if uploaded else "")


def egress(text):
    """Fail when text holds a forbidden term, or when the term sources cannot be read (fail closed)."""
    try:
        hit = egress_hit(text, egress_terms())
    except Exception as e:  # a term source that cannot be read or parsed blocks the request
        raise Fail(f"egress: cannot read the forbidden terms: {e}") from None
    if hit:
        raise Fail(f"egress: '{hit[0]}' is listed in {hit[1]}; use a generic problem statement")


def doi_of(src):
    """The DOI in a doi.org URL (percent-decoded), a doi: name or a bare DOI, else None."""
    s = src.strip()
    if re.match(r"https?://", s, re.I):
        s = urllib.parse.unquote(s)
    m = re.fullmatch(r"(?:https?://(?:dx\.)?doi\.org/|doi:)?(10\.\d{4,9}/\S+)", s, re.I)
    return m.group(1) if m else None


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


def openalex_work(doi):
    """A DOI's OpenAlex record (a lookup by id costs no credits); {} when OpenAlex does not know the DOI,
    None when it could not be asked (an error, a rate limit, a reply that is not JSON)."""
    params = {"select": "id,type,is_retracted,locations"}
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    path = urllib.parse.quote("doi:" + doi.lower(), safe="/:")  # DOIs are case-insensitive
    try:
        w = json.loads(get(f"{OPENALEX}/works/{path}?{urllib.parse.urlencode(params)}")[0])
    except Fail as e:
        return {} if str(e) == HTTP_REASONS[404] else None
    except ValueError:
        return None
    return w if isinstance(w, dict) else None


def load_doi(work, doi):
    """A DOI: its open-access copies first (published, accepted, then submitted versions), then the publisher's page."""
    w = openalex_work(doi)
    late = ["unchecked"] if w is None else ["retracted"] * bool(w.get("is_retracted"))
    names = {"publishedVersion": "published", "acceptedVersion": "accepted", "submittedVersion": "submitted"}
    failed = 0
    for n, loc in enumerate(oa_order(w or {})):
        sub = work / f"copy{n}"  # each copy gets its own folder, so no tool output carries over
        sub.mkdir()
        try:
            r = load_url(sub, loc.get("pdf_url") or loc.get("landing_page_url"), want_pdf=bool(loc.get("pdf_url")))
        except (Fail, ValueError):  # a malformed URL from OpenAlex counts as a copy that failed
            failed += 1
            continue
        version = names.get(loc.get("version"), "")
        r["marks"] += [f"{version}-copy" if version else "copy"] + ["landing-page"] * (not loc.get("pdf_url")) + late
        r["version"] = version or r["version"]
        return r
    try:
        r = load_url(work, f"{DOI}/{urllib.parse.quote(doi, safe='/:;()')}")
    except Fail as e:
        tried = f" ({failed} open-access cop{'y' if failed == 1 else 'ies'} failed too)" if failed else ""
        raise Fail(f"{e}{tried}") from None
    r["marks"] += late
    return r


def load(work, src):
    """What a URL, a DOI or a local file gives (see got)."""
    doi = doi_of(src)
    if doi and (re.match(r"https?://", src, re.I) or not Path(src).expanduser().exists()):
        egress(src)
        return load_doi(work, doi)
    if not re.match(r"https?://", src, re.I):
        p = Path(src).expanduser()
        if not p.is_file():
            raise Fail(f"not found: {src}")
        if p.stat().st_size > CAP:
            raise Fail("too large: over 40 MB")
        suffix = p.suffix.lower()
        return convert(work, p.read_bytes(), LOCAL_TYPES.get(suffix, f"local {suffix or 'file'}"), "", [suffix])
    return load_url(work, src, archive=True)


def load_url(work, src, want_pdf=False, archive=False):
    """What one URL gives, after the egress and host checks; want_pdf refuses an HTML answer; archive takes a dead
    page from the Wayback Machine."""
    egress(src)
    asked = src
    if not re.match(r"https?://[^/?#\s]", src, re.I):
        raise Fail("not an http(s) URL")
    if reason := refused(src):
        raise Fail(reason)
    u = urllib.parse.urlsplit(src)
    host = (u.hostname or "").rstrip(".")
    if (host == "youtu.be" and len(u.path) > 1) or (host == "youtube.com" or host.endswith(".youtube.com")) and (
            u.path == "/watch" and "v" in urllib.parse.parse_qs(u.query) or u.path.startswith("/shorts/")):
        return captions(work, src)
    blob = re.fullmatch(r"/([^/]+)/([^/]+)/blob/(.+)", u.path)
    if host in ("github.com", "www.github.com") and blob:
        src = f"{RAW}/{blob[1]}/{blob[2]}/{blob[3]}"
    abs_pdf = re.fullmatch(r"/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?", u.path)
    if abs_pdf and (host == "arxiv.org" or host.endswith(".arxiv.org")):
        return load_arxiv(work, abs_pdf[1])
    try:
        data, ctype, final = get(src)
    except Dead as e:
        if not archive:
            raise
        return wayback(work, asked, str(e), want_pdf)
    paths = [urllib.parse.urlsplit(x).path.lower() for x in (src, final)]
    return convert(work, data, ctype, final, paths, want_pdf)


def wayback(work, url, why, want_pdf=False):
    """What the Wayback Machine's closest snapshot of a dead public page gives: the original bytes (the id_ flag),
    the same checks, the mark archived-copy, and "archived <snapshot date>" added to the published date."""
    ask = f"{WAYBACK}/wayback/available?{urllib.parse.urlencode({'url': url})}"
    try:
        egress(ask)
        snap = json.loads(get(ask)[0])["archived_snapshots"].get("closest")
    except Fail as e:
        raise Fail(f"{why}; Wayback: {e}") from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Fail(f"{why}; Wayback: not a JSON reply") from None
    ts = str(snap.get("timestamp") or "") if isinstance(snap, dict) else ""
    if not (re.fullmatch(r"\d{14}", ts) and snap.get("available") is True and str(snap.get("status")) == "200"):
        raise Fail(f"{why}; no archived copy")
    try:
        snapshot = f"{ARCHIVE}/web/{ts}id_/{url}"
        egress(snapshot)
        data, ctype, final = get(snapshot)
        paths = [urllib.parse.urlsplit(x).path.lower() for x in (url, final)]
        r = convert(work, data, ctype, final, paths, want_pdf)
    except Fail as e:
        raise Fail(f"{why}; archived copy: {e}") from None
    taken = re.search(r"/web/(\d{4})(\d\d)(\d\d)\d*id_/", final) or re.match(r"(\d{4})(\d\d)(\d\d)", ts)
    r["marks"].append("archived-copy")
    r["published"] = ", ".join(d for d in (r["published"], "archived " + "-".join(taken.groups())) if d != "-")
    return r


def arxiv_version(url):
    """arXiv vN from an arXiv URL that names a version, else arXiv."""
    m = re.search(r"/(?:abs|pdf|html)/(?:[\w.-]+/)?[^/?#]*?(v\d+)(?:\.pdf)?/?(?:[?#]|$)", url)
    return f"arXiv {m[1]}" if m else "arXiv"


def arxiv_html(work, arxiv):
    """What a paper's arXiv HTML version gives; it keeps reading order and real tables."""
    data, ctype, final = get(f"{ARXIV}/html/{arxiv}")
    if not re.search(rb"<!doctype html|<(?:html|head|body)\b", data[:4096], re.I):
        raise Fail("not an HTML page")
    title, text = html_md(data, ctype, final)
    head = " ".join(f"{title} {text[:WALL_SCAN]}".split()).casefold()
    notice = next((n for n in ARXIV_NOTICES if n in head), None)
    if notice:
        raise Fail(f"conversion notice: {notice}")
    check("", text)  # a paper's title may read like a wall phrase; the body checks still apply
    published, modified = html_dates(data, ctype)
    return got({".md": text}, text, "arxiv-html", ["arxiv-html"], final=final, published=published, modified=modified,
               version=arxiv_version(final))


def load_arxiv(work, arxiv):
    """An arXiv paper: the HTML version first, the PDF when the HTML version is missing, damaged or short."""
    try:
        return arxiv_html(work, arxiv)
    except Fail as e:
        html_why = e
    try:
        data, ctype, final = get(f"{ARXIV}/pdf/{arxiv}")
        r = convert(work, data, ctype, final, [urllib.parse.urlsplit(final).path.lower()], True)
    except Fail as e:
        raise Fail(f"arXiv HTML: {html_why}; PDF: {e}") from None
    r["version"] = arxiv_version(final)
    return r


def source_key(url):
    """What makes two requests the same source: the DOI, the arXiv id, or the URL without its fragment; None for files."""
    doi = doi_of(url)
    if doi:
        return "doi:" + doi.lower()
    if not re.match(r"https?://", url, re.I):
        return None
    u = urllib.parse.urlsplit(url.strip())
    host = (u.hostname or "").rstrip(".").lower()
    arxiv = re.fullmatch(r"/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?", u.path)
    if arxiv and (host == "arxiv.org" or host.endswith(".arxiv.org")):
        return "arxiv:" + arxiv[1].lower()
    return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path or "/", u.query, ""))


def read_index(sources):
    """The rows of sources/index.tsv as dicts, oldest first; rows of the wrong width are skipped."""
    path = sources / INDEX
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[1:]
    return [dict(zip(INDEX_HEAD, cells)) for cells in (line.split("\t") for line in lines) if len(cells) == len(INDEX_HEAD)]


def ok_line(name, readable, text, marks):
    first = next((line for line in text.splitlines() if line.strip()), "")
    return "\t".join(["OK", name, readable, str(len(text)), clean(first, 120)] + [",".join(marks)] * bool(marks))


def fetch(sources, name, src):
    """The OK line for one source; raises Fail before anything is written to sources."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", name):
        raise Fail("bad name")
    local = not re.match(r"https?://", src, re.I) and not (doi_of(src) and not Path(src).expanduser().exists())
    rows, key = read_index(sources), None if local else source_key(src)
    newest = list({row["name"]: row for row in rows}.values())  # a name fetched again replaces its older rows
    for row in reversed(newest):
        files = row["files"].split(",")
        readable = next((f for f in files if f in (row["name"] + ".md", row["name"] + ".txt")), None)
        if key and readable and source_key(row["url"]) == key and (sources / readable).is_file():
            text = (sources / readable).read_text(encoding="utf-8", errors="replace")
            return ok_line(row["name"], readable, text, [m for m in row["marks"].split(",") if m not in ("", "-")] + ["reused"])
    old = [p.name for p in sorted(sources.glob(f"{name}.*"))
           if p.stem.lower() == name or p.name.lower() == f"{name}.layout.txt"]
    if old:
        holder = next((row for row in reversed(rows) if row["name"] == name), None)
        raise Fail(f"exists: {old[0]}" + (f", fetched from {holder['url']}" if holder else ""))
    sources.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        r = load(Path(tmp), src)
        staged = Path(tmp) / "save"
        staged.mkdir()
        for suffix, body in r["files"].items():
            if isinstance(body, str):
                (staged / f"{name}{suffix}").write_text(body, encoding="utf-8", newline="")
            else:
                (staged / f"{name}{suffix}").write_bytes(body)
        doi = doi_of(src)
        url = f"local:{Path(src).name}" if local else f"https://doi.org/{doi}" if doi else src
        fetched = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cells = [name, url, r["final"], fetched, r["published"], r["modified"], r["extraction"], r["version"],
                 ",".join(r["marks"]), ",".join(f"{name}{s}" for s in sorted(r["files"]))]
        index = sources / INDEX
        head = "" if index.is_file() else "\t".join(INDEX_HEAD) + "\n"
        with index.open("a", encoding="utf-8", newline="") as out:  # opened first: an index that cannot be written stops the fetch here
            for f in sorted(staged.iterdir()):
                shutil.move(str(f), str(sources / f.name))
            out.write(head + "\t".join(clean(c, None if i in (1, 2) else 500) or "-" for i, c in enumerate(cells)) + "\n")
    readable = next(f"{name}{s}" for s, body in r["files"].items() if isinstance(body, str))
    return ok_line(name, readable, r["text"], r["marks"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources_dir", type=Path, help="the topic's sources folder; created when missing")
    ap.add_argument("name", help="file stem: lowercase letters, digits, dots and hyphens")
    ap.add_argument("source", metavar="url-or-path", help="an http(s) URL, or the path of a local page or PDF")
    a = ap.parse_args(argv)
    a.sources_dir = a.sources_dir.expanduser()  # a quoted ~ reaches the script unexpanded
    global _end
    _end = time.monotonic() + DEADLINE
    try:
        print(fetch(a.sources_dir, a.name, a.source))
        return 0
    except (Fail, OSError, ValueError) as e:
        print(f"FAIL\t{clean(a.name, 120)}\t{clean(e)}")
        return 1
    finally:
        _end = None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
