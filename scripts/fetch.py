"""Download one original source into a research topic's sources/ folder; refuse anything that is not the real thing.

Usage:
  fetch.py <sources_dir> <name> <url-or-path>

  name         file stem matching ^[a-z0-9][a-z0-9.-]*$, for example bates-1989-berrypicking
  url-or-path  an http(s) URL, or a page or PDF saved from a browser (same checks)

Judged by content, not extension or status: walls, error pages, short bodies and HTML posing
as a PDF are refused. Readable copy: <name>.txt for PDF and plain text, <name>.md for HTML,
Markdown and YouTube captions; a PDF is kept as <name>.pdf. Nothing is written on FAIL, and
an existing <name>.* is never overwritten.

Output, one tab-separated line:
  OK <name> <file> <chars> <first line> [ocr|auto-captions|arxiv-html]
  FAIL <name> <reason>                                  exit code 1
"""
import argparse, html.parser, http.client, json, os, re, shutil, socket, ssl, subprocess, sys, tempfile, time
import unicodedata, urllib.error, urllib.parse, urllib.request
from pathlib import Path

VERSION = "0.2.0"
ARXIV = "https://arxiv.org"
RAW = "https://raw.githubusercontent.com"
UA = f"Mozilla/5.0 (compatible; phro-search/{VERSION}; +https://github.com/ThatsHoon/phro-search)"
ACCEPT = "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.8,*/*;q=0.5"
CAP = 40 * 1024 * 1024  # bytes per source document
BACKOFF = (2, 4, 8)  # seconds between retries on HTTP 429
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
HTTP_REASONS = {
    401: "http 401: login required",
    403: "http 403: open it in a browser and pass the saved file path",
    404: "http 404",
    429: "http 429: still rate limited after 3 retries",
    451: "http 451: unavailable for legal reasons",
}
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
        return super().redirect_request(req, fp, 307 if code == 308 else code, msg, headers, newurl)


OPENER = urllib.request.build_opener(Handler)


def get(url):
    """(body, content type, final URL) of one GET; every failure raised as Fail with a short reason."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": ACCEPT})
    for backoff in (*BACKOFF, None):
        try:
            with OPENER.open(req, timeout=30) as r:
                body = r.read(CAP + 1)
                if len(body) > CAP:
                    raise Fail("too large: over 40 MB")
                return body, r.headers.get("Content-Type", ""), r.geturl()
        except urllib.error.HTTPError as e:
            if e.code != 429 or backoff is None:
                raise Fail(HTTP_REASONS.get(e.code, f"http {e.code}")) from None
            after = (e.headers.get("Retry-After") or "").strip()
            time.sleep(int(after) if after.isdecimal() and int(after) <= 60 else backoff)
        except (OSError, http.client.HTTPException) as e:
            why = e.reason if isinstance(e, urllib.error.URLError) else e
            raise Fail("dns" if isinstance(why, socket.gaierror) else "tls" if isinstance(why, ssl.SSLError)
                       else "timeout" if isinstance(why, TimeoutError) else f"network: {why}") from None


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


def pdf_text(work, data):
    """Text layer of a PDF through pdftotext, form feeds between pages."""
    exe = shutil.which("pdftotext")
    if not exe:
        raise Fail("missing tool: pdftotext (poppler or Xpdf)")
    (work / "in.pdf").write_bytes(data)
    run([exe, "-layout", "-enc", "UTF-8", str(work / "in.pdf"), str(work / "out.txt")])
    return (work / "out.txt").read_text(encoding="utf-8", errors="replace") if (work / "out.txt").is_file() else ""


def ocr(work):
    """OCR text of work/in.pdf, pages joined by form feeds."""
    # ponytail: renders every page before OCR, so temp space grows with page count; render page ranges if books matter
    run([shutil.which("pdftoppm"), "-r", "300", "-png", str(work / "in.pdf"), str(work / "page")])
    tess = shutil.which("tesseract")
    have = run([tess, "--list-langs"]).split()
    langs = "+".join(["eng"] + [x for x in ("kor", "jpn") if x in have])
    pages = sorted(work.glob("page-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    return "\f".join(run([tess, str(p), "stdout", "-l", langs]) for p in pages)


def convert(work, data, ctype, base, paths, arxiv=None):
    """(files by suffix, readable text, mark) of downloaded bytes, after the checks."""
    mime = ctype.split(";")[0].strip().lower()
    if b"%PDF-" in data[:1024]:
        text, mark = pdf_text(work, data), ""
        if len("".join(text.split())) < TEXT_LAYER:
            if arxiv:
                files, text, _ = convert(work, *get(f"{ARXIV}/html/{arxiv}"), [])
                return {".pdf": data, **files}, text, "arxiv-html"
            if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
                raise Fail("no text layer, and OCR needs pdftoppm and tesseract")
            text, mark = ocr(work), "ocr"
        check("", text)
        return {".pdf": data, ".txt": text}, text, mark
    if re.search(rb"<!doctype html|<(?:html|head|body)\b", data[:4096], re.I):
        title, text = html_md(data, ctype, base)
        if arxiv or "pdf" in mime or any(p.endswith(".pdf") for p in paths):
            raise Fail(f"expected PDF, got an HTML page: {title or 'no title'}")
        check(title, text)
        return {".md": text}, text, ""
    if mime in TEXT_TYPES:
        text = decode(data, ctype)
        check("", text)
        md = "markdown" in mime or any(p.endswith((".md", ".markdown")) for p in paths)
        return {".md" if md else ".txt": text}, text, ""
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
    """(files, text, mark) of a YouTube video's captions through yt-dlp, without downloading the video."""
    exe = shutil.which("yt-dlp")
    if not exe:
        raise Fail("missing tool: yt-dlp")
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
    return {".md": text}, text, "auto-captions" if auto else ""


def load(work, src):
    """(files by suffix, readable text, mark) for a URL or a local file."""
    if not re.match(r"https?://", src, re.I):
        p = Path(src).expanduser()
        if not p.is_file():
            raise Fail(f"not found: {src}")
        if p.stat().st_size > CAP:
            raise Fail("too large: over 40 MB")
        suffix = p.suffix.lower()
        return convert(work, p.read_bytes(), LOCAL_TYPES.get(suffix, f"local {suffix or 'file'}"), "", [suffix])
    try:
        hit = egress_hit(src, egress_terms())
    except Exception as e:  # a term source that cannot be read or parsed blocks the request
        raise Fail(f"egress: cannot read the forbidden terms: {e}") from None
    if hit:
        raise Fail(f"egress: '{hit[0]}' is listed in {hit[1]}; use a generic problem statement")
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
    abs_pdf = re.fullmatch(r"/(?:abs|pdf)/(.+?)(?:\.pdf)?/?", u.path)
    arxiv = abs_pdf[1] if abs_pdf and (host == "arxiv.org" or host.endswith(".arxiv.org")) else None
    if arxiv:
        src = f"{ARXIV}/pdf/{arxiv}"
    data, ctype, final = get(src)
    paths = [urllib.parse.urlsplit(x).path.lower() for x in (src, final)]
    return convert(work, data, ctype, final, paths, arxiv)


def fetch(sources, name, src):
    """The OK line for one source; raises Fail before anything is written to sources."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", name):
        raise Fail("bad name")
    old = [p.name for p in sorted(sources.glob(f"{name}.*")) if p.stem.lower() == name]
    if old:
        raise Fail(f"exists: {old[0]}")
    sources.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        files, text, mark = load(Path(tmp), src)
        staged = Path(tmp) / "save"
        staged.mkdir()
        for suffix, body in files.items():
            if isinstance(body, str):
                (staged / f"{name}{suffix}").write_text(body, encoding="utf-8", newline="")
            else:
                (staged / f"{name}{suffix}").write_bytes(body)
        for f in sorted(staged.iterdir()):
            shutil.move(str(f), str(sources / f.name))
    readable = next(f"{name}{s}" for s, body in files.items() if isinstance(body, str))
    first = next((line for line in text.splitlines() if line.strip()), "")
    return "\t".join(["OK", name, readable, str(len(text)), clean(first, 120)] + [mark] * bool(mark))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources_dir", type=Path, help="the topic's sources folder; created when missing")
    ap.add_argument("name", help="file stem: lowercase letters, digits, dots and hyphens")
    ap.add_argument("source", metavar="url-or-path", help="an http(s) URL, or the path of a local page or PDF")
    a = ap.parse_args(argv)
    try:
        print(fetch(a.sources_dir, a.name, a.source))
        return 0
    except (Fail, OSError, ValueError) as e:
        print(f"FAIL\t{clean(a.name, 120)}\t{clean(e)}")
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
