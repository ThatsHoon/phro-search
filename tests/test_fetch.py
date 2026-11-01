import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests._load import load

m = load("scripts/fetch.py")
FIX = Path(__file__).resolve().parent / "fixtures" / "fetch"
HTML = {"Content-Type": "text/html; charset=utf-8"}
PDF = b"%PDF-1.4\n%synthetic test document\n"
LONG = "<p>" + "evidence " * 200 + "</p>"  # 1600 weighted characters
VTT = ("WEBVTT\nKind: captions\nLanguage: en\n\n"
       "00:00:00.160 --> 00:00:02.869 align:start position:0%\n \n"
       "hi<00:00:00.480><c> everyone</c><00:00:00.880><c> welcome</c>\n\n"
       "00:00:02.869 --> 00:00:02.879 align:start position:0%\nhi everyone welcome\n \n\n"
       "00:00:02.879 --> 00:00:05.430 align:start position:0%\nhi everyone welcome\n"
       "to<00:00:03.360><c> the</c><00:00:03.679><c> channel</c>\n\n"
       "00:00:05.430 --> 00:00:05.440 align:start position:0%\nto the channel\n \n\n"
       "01:02:03.000 --> 01:02:05.000\n<c.colorE5E5E5>late &amp; last</c>\n")
VTT_LINES = ["[00:00] hi everyone welcome", "[00:02] to the channel", "[1:02:03] late & last"]


def page(body, title="Test page"):
    return f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>".encode()


class Server:
    """Loopback HTTP server; a route maps a path to (status, headers, body), or to a list of them served in turn."""

    def __init__(self, routes):
        seen, agents = self.seen, self.agents = [], []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                agents.append(self.headers.get("User-Agent"))
                key = self.path if self.path in routes else self.path.split("?", 1)[0]
                answer = routes.get(key, (404, {}, b"not found"))
                if isinstance(answer, list):
                    answer = answer.pop(0) if len(answer) > 1 else answer[0]
                status, headers, body = answer
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FetchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = self.tmp / "sources"
        self.patch(m, "egress_terms", lambda: [])
        self.patch(m, "SPACING", 0)
        self.patch(m, "BACKOFF", (0, 0, 0))
        self.patch(m.shutil, "which", lambda name: None)
        self.patch(m.subprocess, "run", mock.Mock(side_effect=AssertionError("unexpected tool run")))

    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def serve(self, routes):
        server = Server(routes)
        self.addCleanup(server.close)
        return server

    def tools(self, **handlers):
        """Pretend these tools are on PATH; a handler takes the command and returns its stdout or None."""
        self.patch(m.shutil, "which", lambda name: f"/fake/bin/{name}" if name.replace("-", "_") in handlers else None)

        def run(cmd, **kwargs):
            out = handlers[Path(cmd[0]).name.replace("-", "_")](cmd)
            return subprocess.CompletedProcess(cmd, 0, out.encode() if isinstance(out, str) else b"", b"")
        self.patch(m.subprocess, "run", run)

    def fetch(self, name, source):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = m.main([str(self.src), name, str(source)])
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1, lines)
        return code, lines[0].split("\t")

    def read(self, name):
        return (self.src / name).read_text(encoding="utf-8")

    def test_wall_phrase_fails(self):
        mention = "<article><p>A long post that says sign in to continue once. " + "word " * 2000 + "</p></article>"
        s = self.serve({"/cf": (200, HTML, page("<p>Checking</p>", title="Just a moment...")),
                        "/ko": (200, HTML, page("<main><p>이 글을 보려면 로그인이 필요합니다.</p></main>")),
                        "/long": (200, HTML, page(mention))})
        self.assertEqual(self.fetch("cf", s.url + "/cf"), (1, ["FAIL", "cf", "wall: just a moment"]))
        self.assertEqual(self.fetch("ko", s.url + "/ko"), (1, ["FAIL", "ko", "wall: 로그인이 필요"]))
        self.assertEqual(self.fetch("long", s.url + "/long")[0], 0)  # a phrase in passing in a long body is no wall

    def test_short_body_fails_with_count(self):
        s = self.serve({"/short": (200, HTML, page("<article><p>" + "word " * 100 + "</p></article>"))})
        self.assertEqual(self.fetch("short", s.url + "/short"),
                         (1, ["FAIL", "short", "too short: 400 weighted characters (minimum 1500)"]))

    def test_short_korean_article_passes(self):
        text = (FIX / "korean-article.html").read_text(encoding="utf-8")
        euckr = text.replace('charset="utf-8"', 'charset="euc-kr"').encode("euc-kr")
        s = self.serve({"/utf8": (200, {"Content-Type": "text/html"}, text.encode()),
                        "/euckr": (200, {"Content-Type": "text/html"}, euckr)})
        code, f = self.fetch("ko-utf8", s.url + "/utf8")
        self.assertEqual((code, f[2], f[4]), (0, "ko-utf8.md", "# 동네 텃밭을 가꾸며 배운 것들"))
        saved = self.read("ko-utf8.md")
        self.assertGreater(len(re.findall("[가-힣]", saved)), 650)
        self.assertLess(len("".join(saved.split())), m.MIN_WEIGHTED)  # too short if each character counted once
        self.assertEqual(self.fetch("ko-euckr", s.url + "/euckr")[0], 0)  # charset from <meta>
        self.assertEqual(self.read("ko-euckr.md"), saved)

    def test_pdf_without_pdftotext_fails(self):
        s = self.serve({"/paper.pdf": (200, {"Content-Type": "application/pdf"}, PDF)})
        self.assertEqual(self.fetch("paper", s.url + "/paper.pdf"),
                         (1, ["FAIL", "paper", "missing tool: pdftotext (poppler or Xpdf)"]))

    def test_html_becomes_markdown(self):
        body = ("<header>Site menu</header><nav><a href='/'>Home</a></nav>"
                "<article><h2>Method</h2><ul><li>first step</li><li>second <code>run()</code></li></ul>"
                "<p>See <a href='/docs/guide?x=1'>the guide</a>.</p>"
                "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>"
                "<script>var leak = 'script text';</script><img src='x.png' alt='picture'>" + LONG + "</article>"
                "<footer>footer text</footer>")
        s = self.serve({"/post/1": (200, HTML, page(body))})
        code, f = self.fetch("post", s.url + "/post/1")
        self.assertEqual((code, f[2], f[4]), (0, "post.md", "## Method"))
        md = self.read("post.md")
        self.assertEqual(f[3], str(len(md)))
        for want in ("## Method", "- first step", "- second `run()`", f"See [the guide]({s.url}/docs/guide?x=1).",
                     "| a | b |\n| 1 | 2 |"):
            self.assertIn(want, md)
        for gone in ("script text", "Site menu", "Home", "footer text", "picture", "x.png"):
            self.assertNotIn(gone, md)

    def test_page_layouts(self):
        essay = "<br><br>".join(["paragraph " + "word " * 70] * 6)
        s = self.serve({"/form": (200, HTML, page(f"<form action='/x'><div><h1>Notice</h1>{LONG}</div></form>")),
                        "/layout": (200, HTML, page(f"<table><tr><td><img src='a.gif'></td><td>{essay}</td></tr></table>"))})
        self.assertEqual(self.fetch("form", s.url + "/form")[0], 0)  # a form wrapping the whole page is kept
        self.assertIn("# Notice", self.read("form.md"))
        self.assertEqual(self.fetch("layout", s.url + "/layout")[0], 0)  # a layout cell stays as lines of text
        lines = self.read("layout.md").splitlines()
        self.assertEqual(sum(line.startswith("paragraph") for line in lines), 6)
        self.assertFalse(any(line.startswith("|") for line in lines))

    def test_expected_pdf_got_html(self):
        login = page("<p>Please sign in</p>", title="Sign in | Publisher")
        s = self.serve({"/paper.pdf": (200, HTML, login),
                        "/download": (200, {"Content-Type": "application/pdf"}, login)})
        for name, path in (("a", "/paper.pdf"), ("b", "/download")):
            self.assertEqual(self.fetch(name, s.url + path),
                             (1, ["FAIL", name, "expected PDF, got an HTML page: Sign in | Publisher"]))

    def saved(self):
        """The files in sources/, the index left out."""
        return sorted(p.name for p in self.src.iterdir() if p.name != "index.tsv")

    def test_arxiv_html_comes_first(self):
        # No pdftotext on PATH: the HTML version is enough, so arXiv works without poppler.
        s = self.serve({"/html/2508.00001": (200, HTML, page("<article><h1>Paper title</h1>" + LONG + "</article>"))})
        self.patch(m, "ARXIV", s.url)
        code, f = self.fetch("arxiv-2508.00001-x", "https://arxiv.org/pdf/2508.00001.pdf")
        self.assertEqual((code, f[2], f[4], f[5]), (0, "arxiv-2508.00001-x.md", "# Paper title", "arxiv-html"))
        self.assertEqual(s.seen, ["/html/2508.00001"])
        self.assertEqual(self.saved(), ["arxiv-2508.00001-x.md"])

    def test_arxiv_falls_back_to_the_pdf(self):
        fatal = page("<article><p>Conversion to HTML had a Fatal error and exited abruptly. This document may be "
                     "truncated or damaged.</p>" + LONG + "</article>")
        s = self.serve({"/html/2508.00001": (404, HTML, page("<p>No HTML for this paper</p>")),
                        "/html/2508.00003": (200, HTML, fatal),
                        "/pdf/2508.00001": (200, {"Content-Type": "application/pdf"}, PDF),
                        "/pdf/2508.00003": (200, {"Content-Type": "application/pdf"}, PDF)})
        self.patch(m, "ARXIV", s.url)
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text("Paper title\n" + "word " * 400, encoding="utf-8"))
        for n in ("1", "3"):
            code, f = self.fetch(f"p{n}", f"https://arxiv.org/abs/2508.0000{n}")
            self.assertEqual((code, f[2]), (0, f"p{n}.txt"))
        self.assertEqual(s.seen, ["/html/2508.00001", "/pdf/2508.00001", "/html/2508.00003", "/pdf/2508.00003"])

    def test_nothing_is_written_after_a_fail(self):
        s = self.serve({"/pdf/2508.00002": (200, {"Content-Type": "application/pdf"}, PDF)})  # no HTML version
        self.patch(m, "ARXIV", s.url)
        self.assertEqual(self.fetch("p", "https://arxiv.org/pdf/2508.00002.pdf"),
                         (1, ["FAIL", "p", "arXiv HTML: http 404; PDF: missing tool: pdftotext (poppler or Xpdf)"]))
        self.assertEqual(s.seen, ["/html/2508.00002", "/pdf/2508.00002"])
        self.assertFalse(self.src.exists() and self.saved())

    def test_pdf_text_in_reading_order_with_a_layout_copy(self):
        reading = "Left column first sentence.\nLeft column second sentence.\nRight column text.\n" + "word " * 400
        layout = "Left column first sentence.      Right column text.\nLeft column second sentence.\n" + "word " * 400

        def pdftotext(cmd):
            Path(cmd[-1]).write_text(layout if "-layout" in cmd else reading, encoding="utf-8")
        self.tools(pdftotext=pdftotext)
        pdf = self.tmp / "two-column.pdf"
        pdf.write_bytes(PDF)
        code, f = self.fetch("cols", pdf)
        self.assertEqual((code, f[2], f[3], f[4]), (0, "cols.txt", str(len(reading)), "Left column first sentence."))
        self.assertEqual((self.read("cols.txt"), self.read("cols.layout.txt")), (reading, layout))
        self.assertEqual(self.saved(), ["cols.layout.txt", "cols.pdf", "cols.txt"])

    # DOIs: open-access copies first

    def doi_server(self, work=None, **routes):
        """A loopback server for the OpenAlex lookup, the copies and the publisher; fetch.py pointed at it."""
        table = {}
        s = self.serve(table)
        if work is not None:
            text = json.dumps(work).replace("{u}", s.url)
            table["/works/doi:10.1234/abc"] = (200, {"Content-Type": "application/json"}, text.encode())
        table.update(routes)
        self.patch(m, "OPENALEX", s.url)
        self.patch(m, "DOI", s.url)
        return s

    def paths(self, s):
        return [p.split("?", 1)[0] for p in s.seen]

    def test_doi_tries_open_access_copies_first(self):
        work = {"id": "https://openalex.org/W1", "type": "article", "is_retracted": False, "locations": [
            {"is_oa": True, "version": "acceptedVersion", "pdf_url": "{u}/repo.pdf", "source": {"type": "repository"}},
            {"is_oa": True, "version": "publishedVersion", "pdf_url": "{u}/pub.pdf", "landing_page_url": "{u}/pub",
             "source": {"type": "journal"}},
            {"is_oa": False, "version": "publishedVersion", "pdf_url": "{u}/closed.pdf"}]}
        s = self.doi_server(work, **{"/pub.pdf": (403, {}, b""),
                                     "/repo.pdf": (200, {"Content-Type": "application/pdf"}, PDF)})
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text("Accepted manuscript\n" + "word " * 400, encoding="utf-8"))
        code, f = self.fetch("paper", "https://doi.org/10.1234/abc")
        self.assertEqual((code, f[2], f[5]), (0, "paper.txt", "accepted-copy"))
        self.assertEqual(self.paths(s), ["/works/doi:10.1234/abc", "/pub.pdf", "/repo.pdf"])

    def test_doi_goes_to_the_publisher_when_no_copy_works(self):
        article = (200, HTML, page("<article>" + LONG + "</article>"))
        for name, work in (("none", {"id": "W2", "locations": []}), ("gone", None)):  # no copies; OpenAlex 404
            with self.subTest(name=name):
                self.src = self.tmp / f"sources-{name}"  # the same DOI in one folder would be reused
                s = self.doi_server(work, **{"/10.1234/abc": article})
                code, f = self.fetch(name, "doi:10.1234/abc")
                self.assertEqual((code, f[2], len(f)), (0, f"{name}.md", 5))
                self.assertEqual(self.paths(s), ["/works/doi:10.1234/abc", "/10.1234/abc"])

    def test_doi_fail_counts_the_copies_tried(self):
        work = {"id": "W3", "is_retracted": True, "locations": [
            {"is_oa": True, "version": "publishedVersion", "pdf_url": "{u}/pub.pdf", "source": {"type": "journal"}}]}
        self.doi_server(work, **{"/pub.pdf": (403, {}, b""), "/10.1234/abc": (403, {}, b"")})
        self.assertEqual(self.fetch("p", "10.1234/abc"), (1, ["FAIL", "p", "http 403: open it in a browser and pass the "
                                                                    "saved file path (1 open-access copy failed too)"]))
        self.assertFalse(self.src.exists() and self.saved())

    def test_doi_of_a_retracted_work_is_marked(self):
        self.doi_server({"id": "W4", "is_retracted": True, "locations": []},
                        **{"/10.1234/abc": (200, HTML, page("<article>" + LONG + "</article>"))})
        self.assertEqual(self.fetch("r", "https://dx.doi.org/10.1234/abc")[1][5], "retracted")

    def test_doi_egress_and_key(self):
        work = {"id": "W5", "locations": [
            {"is_oa": True, "version": "submittedVersion", "pdf_url": "{u}/projectx/draft.pdf", "source": {}}]}
        s = self.doi_server(work, **{"/10.1234/abc": (200, HTML, page("<article>" + LONG + "</article>"))})
        self.patch(m, "egress_terms", lambda: [("projectx", "forbidden.txt")])
        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "k-secret-123"}):
            code, f = self.fetch("k", "10.1234/abc")
        self.assertEqual(code, 0)
        self.assertNotIn("k-secret-123", "\t".join(f))
        self.assertIn("api_key=k-secret-123", s.seen[0])
        self.assertEqual(self.paths(s), ["/works/doi:10.1234/abc", "/10.1234/abc"])  # the copy naming projectx is never asked for
        self.assertEqual(self.fetch("e", "doi:10.1234/projectx")[1][2],
                         "egress: 'projectx' is listed in forbidden.txt; use a generic problem statement")
        self.assertEqual(len(s.seen), 2)

    # sources/index.tsv: provenance and reuse

    def index(self):
        lines = (self.src / "index.tsv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split("\t"), list(m.INDEX_HEAD))
        return [dict(zip(m.INDEX_HEAD, line.split("\t"))) for line in lines[1:]]

    def test_index_row_with_the_dates_a_page_states(self):
        head = ('<meta content="2025-05-01T10:00:00Z" property="article:published_time">'
                '<script type="application/ld+json">{"dateModified": "2025-06-02"}</script>')
        body = f"<!doctype html><html><head><title>T</title>{head}</head><body><article>{LONG}</article></body></html>"
        s = self.serve({"/post": (200, HTML, body.encode())})
        self.assertEqual(self.fetch("post", s.url + "/post")[0], 0)
        row = self.index()[0]
        self.assertRegex(row.pop("fetched"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(row, {"name": "post", "url": s.url + "/post", "final": s.url + "/post", "published": "2025-05-01",
                               "modified": "2025-06-02", "extraction": "html", "version": "-", "marks": "-",
                               "files": "post.md"})

    def test_dates_from_other_places(self):
        page = lambda tag: f"<html><head>{tag}</head></html>".encode()
        self.assertEqual(m.html_dates(page('<meta name="citation_publication_date" content="2020/5/7">'), ""), ("2020-05-07", ""))
        self.assertEqual(m.html_dates(page('<time datetime="2019-12-31T08:00">x</time>'), ""), ("2019-12-31", ""))
        self.assertEqual(m.html_dates(page('<meta name="date" content="soon">'), ""), ("", ""))
        self.assertEqual(m.pdf_dates(b"%PDF-1.4 /CreationDate (D:20240115093000Z) /ModDate (D:202403)"), ("2024-01-15", "2024-03"))
        self.assertEqual(m.pdf_dates(b"<xmp:CreateDate>2023-02-03T00:00:00</xmp:CreateDate>"), ("2023-02-03", ""))
        self.assertEqual(m.pdf_dates(PDF), ("", ""))

    def test_same_source_is_reused_without_a_request(self):
        s = self.serve({"/p": (200, HTML, page("<article><h1>Kept</h1>" + LONG + "</article>")),
                        "/html/2508.00001v2": (200, HTML, page("<article><h1>Paper</h1>" + LONG + "</article>"))})
        self.patch(m, "ARXIV", s.url)
        first = self.fetch("kept", s.url + "/p#intro")
        self.assertEqual(self.fetch("again", s.url + "/p"), (0, first[1][:5] + ["reused"]))
        self.assertEqual((self.fetch("a", "https://arxiv.org/abs/2508.00001v2")[0], self.index()[1]["version"]), (0, "arXiv v2"))
        self.assertEqual(self.fetch("b", "https://arxiv.org/pdf/2508.00001v2.pdf")[1][1:2] + [self.fetch("b", "https://arxiv.org/pdf/2508.00001v2.pdf")[1][5]],
                         ["a", "arxiv-html,reused"])
        self.assertEqual(s.seen, ["/p", "/html/2508.00001v2"])
        self.assertFalse(any(p.name.startswith(("again", "b.")) for p in self.src.iterdir()))

    def test_taken_name_says_where_its_source_came_from(self):
        s = self.serve({"/one": (200, HTML, page("<article>" + LONG + "</article>")),
                        "/two": (200, HTML, page("<article>" + LONG + "</article>"))})
        self.fetch("x", s.url + "/one")
        self.assertEqual(self.fetch("x", s.url + "/two"), (1, ["FAIL", "x", f"exists: x.md, fetched from {s.url}/one"]))
        self.assertEqual(s.seen, ["/one"])

    def test_local_files_are_indexed_but_never_reused(self):
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text("Saved paper\n" + "word " * 400, encoding="utf-8"))
        pdf = self.tmp / "saved.pdf"
        pdf.write_bytes(PDF.replace(b"%synthetic", b"/CreationDate (D:20210304) %synthetic"))
        self.assertEqual(self.fetch("one", pdf)[0], 0)
        self.assertEqual(self.fetch("two", pdf)[0], 0)
        rows = self.index()
        self.assertEqual([(r["url"], r["extraction"], r["published"], r["files"]) for r in rows],
                         [("local:saved.pdf", "pdftotext", "2021-03-04", f"{n}.layout.txt,{n}.pdf,{n}.txt") for n in ("one", "two")])

    def test_caption_upload_date(self):
        info = {"title": "Talk", "language": "en", "upload_date": "20240115", "subtitles": {"en": [{}]}}

        def yt_dlp(cmd):
            if "-J" in cmd:
                return json.dumps(info)
            Path(cmd[cmd.index("-P") + 1], "cap.en.vtt").write_text(VTT, encoding="utf-8")
        self.tools(yt_dlp=yt_dlp)
        self.assertEqual(self.fetch("talk", "https://youtu.be/abc123")[0], 0)
        self.assertEqual((self.index()[0]["published"], self.index()[0]["extraction"]), ("2024-01-15", "captions"))

    def test_doi_row_names_the_copy_version(self):
        work = {"id": "W6", "locations": [{"is_oa": True, "version": "acceptedVersion", "pdf_url": "{u}/repo.pdf",
                                           "source": {"type": "repository"}}]}
        self.doi_server(work, **{"/repo.pdf": (200, {"Content-Type": "application/pdf"}, PDF)})
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text("Manuscript\n" + "word " * 400, encoding="utf-8"))
        self.assertEqual(self.fetch("d", "10.1234/ABC")[0], 0)
        row = self.index()[0]
        self.assertEqual((row["url"], row["version"], row["marks"]), ("https://doi.org/10.1234/ABC", "accepted", "accepted-copy"))
        self.assertEqual(self.fetch("d2", "https://doi.org/10.1234/abc")[1][1], "d")  # DOIs match without regard to case

    # review fixes

    def test_percent_encoded_doi_url_is_read_once(self):
        table = {"/works/doi:10.1234/x%3Cy%3E": (200, {"Content-Type": "application/json"}, b'{"id": "W7", "locations": []}'),
                 "/10.1234/x%3Cy%3E": (200, HTML, page("<article>" + LONG + "</article>"))}
        s = self.serve(table)
        self.patch(m, "OPENALEX", s.url)
        self.patch(m, "DOI", s.url)
        self.assertEqual(self.fetch("p", "https://doi.org/10.1234/x%3Cy%3E")[0], 0)
        self.assertEqual(self.paths(s), ["/works/doi:10.1234/x%3Cy%3E", "/10.1234/x%3Cy%3E"])
        self.assertEqual(self.fetch("q", "10.1234/x<y>")[1][5], "reused")  # the same DOI, given bare

    def test_reuse_ignores_rows_whose_name_was_fetched_again(self):
        s = self.serve({"/a": (200, HTML, page("<article><h1>Page A</h1>" + LONG + "</article>")),
                        "/b": (200, HTML, page("<article><h1>Page B</h1>" + LONG + "</article>"))})
        self.fetch("x", s.url + "/a")
        (self.src / "x.md").unlink()
        self.fetch("x", s.url + "/b")
        code, f = self.fetch("y", s.url + "/a")
        self.assertEqual((code, f[1], f[4]), (0, "y", "# Page A"))

    def test_an_index_that_cannot_be_written_leaves_no_file(self):
        s = self.serve({"/p": (200, HTML, page("<article>" + LONG + "</article>"))})
        (self.src / "index.tsv").mkdir(parents=True)  # stands in for an index another program holds open
        self.assertEqual(self.fetch("p", s.url + "/p")[0], 1)
        self.assertEqual(self.saved(), [])

    def test_doi_marks_an_unchecked_retraction_when_openalex_fails(self):
        self.doi_server(None, **{"/works/doi:10.1234/abc": (503, {}, b""),
                                 "/10.1234/abc": (200, HTML, page("<article>" + LONG + "</article>"))})
        self.assertEqual(self.fetch("u", "10.1234/abc")[1][5], "unchecked")
        self.assertEqual(self.index()[0]["marks"], "unchecked")

    def test_doi_copy_rules(self):
        work = {"id": "W8", "locations": [
            {"is_oa": True, "version": "publishedVersion", "landing_page_url": "{u}/handle/1", "source": {"type": "repository"}},
            {"is_oa": True, "version": "publishedVersion", "pdf_url": "{u}/record", "source": {"type": "repository"}},
            {"is_oa": True, "version": "publishedVersion", "pdf_url": "file:///etc/hosts", "source": {"type": "repository"}},
            {"is_oa": True, "version": "publishedVersion", "pdf_url": "repo.example/x.pdf", "source": {"type": "repository"}},
            {"is_oa": True, "version": "acceptedVersion", "pdf_url": "{u}/files/M\u00fcller.pdf", "source": {"type": "repository"}}]}
        record = page("<article><p>Embargoed until 2030.</p>" + LONG + "</article>")
        s = self.doi_server(work, **{"/record": (200, HTML, record), "/handle/1": (200, HTML, record),
                                     "/files/M%C3%BCller.pdf": (200, {"Content-Type": "application/pdf"}, PDF)})
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text("Accepted\n" + "word " * 400, encoding="utf-8"))
        code, f = self.fetch("p", "10.1234/abc")
        # A PDF link that serves a record page is no copy, bad URLs are skipped, and every PDF link comes before a
        # landing page; the accepted PDF with a non-ASCII name is fetched, and the published landing page never is.
        self.assertEqual((code, f[2], f[5]), (0, "p.txt", "accepted-copy"))
        self.assertEqual(self.paths(s), ["/works/doi:10.1234/abc", "/record", "/files/M%C3%BCller.pdf"])

    def test_arxiv_title_that_reads_like_a_wall(self):
        s = self.serve({"/html/2508.00004": (200, HTML, page("<article><h1>Access denied: a study</h1>" + LONG * 6 + "</article>",
                                                             title="Access Denied: A Study of Refusals"))})
        self.patch(m, "ARXIV", s.url)
        self.assertEqual(self.fetch("a", "https://arxiv.org/abs/2508.00004")[0], 0)

    def test_reuse_edges(self):
        long_url = "/p?" + "q=" + "x" * 600
        s = self.serve({"/p": (200, HTML, page("<article>" + LONG + "</article>"))})
        self.fetch("long", s.url + long_url)
        self.assertEqual(self.fetch("long2", s.url + long_url)[1][5], "reused")  # long URLs stay whole in the index
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text("Paper\n" + "word " * 400, encoding="utf-8"))
        self.serve({})
        (self.src / "long.md").rename(self.src / "keep.md")  # a missing readable file means no reuse
        self.assertEqual(self.fetch("long3", s.url + long_url)[1][1], "long3")
        (self.src / "map.layout.md").write_text("another source\n", encoding="utf-8")
        self.assertEqual(self.fetch("map", s.url + "/p")[0], 0)  # map.layout.md belongs to the name map.layout

    def test_reuse_survives_a_missing_layout_copy(self):
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text("Paper\n" + "word " * 400, encoding="utf-8"))
        s = self.serve({"/paper.pdf": (200, {"Content-Type": "application/pdf"}, PDF)})
        self.fetch("paper", s.url + "/paper.pdf")
        (self.src / "paper.layout.txt").unlink()
        self.assertEqual(self.fetch("again", s.url + "/paper.pdf")[1][1:3], ["paper", "paper.txt"])

    def test_stale_tool_output_is_never_read(self):
        work = self.tmp / "work"
        work.mkdir()
        (work / "out.txt").write_text("text of an earlier copy", encoding="utf-8")
        (work / "page-1.png").write_bytes(b"old page")
        self.tools(pdftotext=lambda cmd: None)
        self.assertEqual(m.pdf_text(work, PDF), ("", ""))

    def test_dates_and_versions_edge_cases(self):
        self.assertEqual(m.pdf_dates(b"/CreationDate (D:20100101) trailer /CreationDate (D:20240115) /ModDate (D:20240116)"),
                         ("2024-01-15", "2024-01-16"))  # an incremental update appends the current info last
        self.assertEqual(m.arxiv_version("https://arxiv.org/abs/hep-th/9901001v2"), "arXiv v2")
        self.assertEqual(m.arxiv_version("https://arxiv.org/abs/hep-th/9901001"), "arXiv")

    def test_refused_hosts_make_no_request(self):
        opener = mock.Mock(side_effect=AssertionError("a request was made"))
        self.patch(m.OPENER, "open", opener)
        for url, reason in (("https://x.com/a/status/1", "x.com is not fetched: login wall"),
                            ("https://mobile.twitter.com/a", "x.com is not fetched: login wall"),
                            ("https://old.reddit.com/r/x/comments/1/", "reddit.com is not fetched: robots rules"),
                            ("https://i.redd.it/x.png", "reddit.com is not fetched: robots rules")):
            self.assertEqual(self.fetch("post", url), (1, ["FAIL", "post", reason]))
        opener.assert_not_called()

    def test_redirect_to_refused_host_fails(self):
        s = self.serve({"/go": (302, {"Location": "https://x.com/a/status/1"}, b"")})
        self.assertEqual(self.fetch("go", s.url + "/go"), (1, ["FAIL", "go", "x.com is not fetched: login wall"]))

    def test_egress_blocks_before_any_request(self):
        opener = mock.Mock(side_effect=AssertionError("a request was made"))
        self.patch(m.OPENER, "open", opener)
        self.patch(m, "egress_terms", lambda: [("projectx", "forbidden.txt")])
        self.assertEqual(self.fetch("e", "https://example.org/search?q=ProjectX%20notes"), (1, [
            "FAIL", "e", "egress: 'projectx' is listed in forbidden.txt; use a generic problem statement"]))
        self.patch(m, "egress_terms", mock.Mock(side_effect=ValueError("bad json")))
        self.assertEqual(self.fetch("e", "https://example.org/"),
                         (1, ["FAIL", "e", "egress: cannot read the forbidden terms: bad json"]))
        opener.assert_not_called()

    def test_local_pdf_is_ingested(self):
        text = "Title line of the paper\n" + "word " * 400 + "\n\fPage two\n"
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text(text, encoding="utf-8"))
        pdf = self.tmp / "saved.pdf"
        pdf.write_bytes(PDF)
        self.assertEqual(self.fetch("saved", pdf), (0, ["OK", "saved", "saved.txt", str(len(text)), "Title line of the paper"]))
        self.assertEqual((self.src / "saved.pdf").read_bytes(), PDF)
        self.assertEqual((self.src / "saved.txt").read_bytes(), text.encode())  # form feeds kept, LF line ends
        self.assertEqual((self.src / "saved.layout.txt").read_bytes(), text.encode())

    def test_local_text_files(self):
        for suffix in (".txt", ".md"):
            path = self.tmp / f"note{suffix}"
            path.write_text("First line\n" + "word " * 400, encoding="utf-8")
            code, f = self.fetch("note" + suffix[1:], path)
            self.assertEqual((code, f[2], f[4]), (0, f"note{suffix[1:]}{suffix}", "First line"))

    def test_github_blob_is_fetched_raw(self):
        s = self.serve({"/o/r/main/docs/guide.md": (200, {"Content-Type": "text/plain; charset=utf-8"},
                                                     ("# Guide\n\n" + "word " * 400).encode())})
        self.patch(m, "RAW", s.url)
        code, f = self.fetch("guide", "https://github.com/o/r/blob/main/docs/guide.md")
        self.assertEqual((code, f[2], f[4]), (0, "guide.md", "# Guide"))
        self.assertEqual(s.seen, ["/o/r/main/docs/guide.md"])

    def test_308_redirect_is_followed(self):
        s = self.serve({"/old": (308, {"Location": "/new"}, b""),
                        "/new": (200, HTML, page("<article>" + LONG + "</article>"))})
        self.assertEqual(self.fetch("moved", s.url + "/old")[0], 0)
        self.assertEqual(s.seen, ["/old", "/new"])
        self.assertEqual(set(s.agents), {m.UA})

    def test_http_errors_and_rate_limits(self):
        s = self.serve({"/401": (401, {}, b""), "/403": (403, {}, b""), "/451": (451, {}, b""), "/500": (500, {}, b""),
                        "/jammed": (429, {}, b""),
                        "/busy": [(429, {}, b""), (200, HTML, page("<article>" + LONG + "</article>"))]})
        for path, reason in (("/404", "http 404"), ("/401", "http 401: login required"),
                             ("/403", "http 403: open it in a browser and pass the saved file path"),
                             ("/451", "http 451: unavailable for legal reasons"), ("/500", "http 500"),
                             ("/jammed", "http 429: still rate limited after 3 retries")):
            self.assertEqual(self.fetch("e", s.url + path), (1, ["FAIL", "e", reason]))
        self.assertEqual(s.seen.count("/jammed"), 4)
        self.assertEqual(self.fetch("busy", s.url + "/busy")[0], 0)
        self.assertEqual(s.seen.count("/busy"), 2)

    def test_one_retry_policy(self):
        wall = page("<p>Checking</p>", title="Just a moment...")
        s = self.serve({"/flaky": [(503, {}, b""), (200, HTML, page("<article>" + LONG + "</article>"))],
                        "/wall": (503, HTML, wall), "/flagged": (503, {"cf-mitigated": "challenge"}, b""),
                        "/github": (403, {"X-RateLimit-Remaining": "0"}, b""),
                        "/later": [(503, {"Retry-After": "30"}, b""), (200, HTML, page("<article>" + LONG + "</article>"))]})
        self.assertEqual(self.fetch("flaky", s.url + "/flaky")[0], 0)  # a 5xx is retried
        self.assertEqual(s.seen.count("/flaky"), 2)
        bot = "http 503: bot check; open it in a browser and pass the saved file path"
        self.assertEqual(self.fetch("w", s.url + "/wall"), (1, ["FAIL", "w", bot]))  # a bot check is a wall
        self.assertEqual(self.fetch("w", s.url + "/flagged"), (1, ["FAIL", "w", bot]))
        self.assertEqual(self.fetch("g", s.url + "/github")[1][2], "http 403: open it in a browser and pass the saved file path")
        self.assertEqual([s.seen.count(x) for x in ("/wall", "/flagged", "/github")], [1, 1, 1])
        self.patch(m, "DEADLINE", 5)  # a Retry-After that would pass the run deadline is not waited for
        self.assertEqual(self.fetch("l", s.url + "/later"), (1, ["FAIL", "l", "http 503; run deadline reached"]))
        self.assertEqual(s.seen.count("/later"), 1)
        self.patch(m, "DEADLINE", 0)
        self.assertEqual(self.fetch("l", s.url + "/later"), (1, ["FAIL", "l", "run deadline reached"]))
        self.assertEqual(s.seen.count("/later"), 1)
        self.assertIsNone(m._end)  # the deadline belongs to one run

    def test_timeout_is_retried(self):
        class Reply(io.BytesIO):
            headers = {"Content-Type": "text/html"}

            def geturl(self):
                return "https://example.org/a"
        replies = [TimeoutError("timed out"), Reply(page("<article>" + LONG + "</article>"))]
        timeouts = []

        def opener(req, timeout=None):
            timeouts.append(timeout)
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        self.patch(m.OPENER, "open", opener)
        self.assertEqual(self.fetch("t", "https://example.org/a")[0], 0)
        self.assertEqual(len(timeouts), 2)
        self.assertTrue(all(0 < t <= 30 for t in timeouts))

    def test_existing_name_is_refused(self):
        self.src.mkdir()
        old = self.src / "taken.md"
        old.write_bytes(b"cited line\n")
        before = old.stat().st_mtime_ns
        (self.src / "base.v2.md").write_bytes(b"another source\n")
        s = self.serve({"/p": (200, HTML, page("<article>" + LONG + "</article>"))})
        self.assertEqual(self.fetch("taken", s.url + "/p"), (1, ["FAIL", "taken", "exists: taken.md"]))
        self.assertEqual((old.read_bytes(), old.stat().st_mtime_ns), (b"cited line\n", before))
        self.assertEqual(s.seen, [])
        self.assertEqual(self.fetch("base", s.url + "/p")[0], 0)  # base.v2.md belongs to another name

    def test_bad_input(self):
        for name in ("Bad", ".x", "a/b", "a b", "a_b"):
            self.assertEqual(self.fetch(name, "https://example.org/")[1][2], "bad name")
        missing = self.tmp / "nope.pdf"
        self.assertEqual(self.fetch("n", missing), (1, ["FAIL", "n", f"not found: {missing}"]))
        s = self.serve({"/api": (200, {"Content-Type": "application/json"}, b'{"a": 1}')})
        self.assertEqual(self.fetch("j", s.url + "/api"), (1, ["FAIL", "j", "unknown content: application/json"]))

    def test_printed_fields_are_sanitized(self):
        zw, rlo, bel, bom, lq, rq = chr(0x200B), chr(0x202E), chr(7), chr(0xFEFF), chr(0x201C), chr(0x201D)
        h1 = f"Re{zw}al {rlo}ti{bel}tle {lq}q{rq}{bom}"
        s = self.serve({"/p": (200, HTML, page(f"<article><h1>{h1}</h1>{LONG}</article>")),
                        "/x.pdf": (200, HTML, page("<p>x</p>", title=f"Sign{zw} in{rlo}\t{bel}now"))})
        code, f = self.fetch("clean", s.url + "/p")
        self.assertEqual((code, f[4]), (0, '# Real title "q"'))
        self.assertIn(h1, self.read("clean.md"))  # the saved file keeps the original text
        self.assertEqual(self.fetch("fake", s.url + "/x.pdf"),
                         (1, ["FAIL", "fake", "expected PDF, got an HTML page: Sign in now"]))

    def test_vtt_to_lines(self):
        self.assertEqual(m.vtt_lines(VTT), VTT_LINES)

    def test_youtube_captions(self):
        info = {"title": "Demo talk", "language": "en", "subtitles": {},
                "automatic_captions": {"fr": [{}], "en-orig": [{}], "en": [{}]}}
        calls = []

        def yt_dlp(cmd):
            calls.append(cmd)
            self.assertIn("--skip-download", cmd)
            if "-J" in cmd:
                return json.dumps(info)
            self.assertEqual(cmd[cmd.index("--sub-langs") + 1], re.escape("en-orig"))
            self.assertIn("--write-auto-subs", cmd)
            Path(cmd[cmd.index("-P") + 1], "cap.en-orig.vtt").write_text(VTT, encoding="utf-8")
        self.tools(yt_dlp=yt_dlp)
        code, f = self.fetch("demo-talk", "https://www.youtube.com/watch?v=abc123")
        self.assertEqual((code, f[2], f[4], f[5]), (0, "demo-talk.md", "# Demo talk", "auto-captions"))
        self.assertEqual(self.read("demo-talk.md"), "# Demo talk\n\n" + "\n".join(VTT_LINES) + "\n")
        self.assertEqual(len(calls), 2)

    def test_caption_track_choice(self):
        for info, want in (
                ({"subtitles": {"de": [], "en": []}, "automatic_captions": {"en-orig": []}, "language": "en"}, ("en", False)),
                ({"subtitles": {"ar": [], "en-x1": []}, "language": "en-US"}, ("en-x1", False)),
                ({"subtitles": {"live_chat": []}, "automatic_captions": {"fr": [], "ko-orig": [], "ko": []}}, ("ko-orig", True)),
                ({"automatic_captions": {"en-orig": [], "ja-orig": []}, "language": "ja"}, ("ja-orig", True)),
                ({"title": "silent"}, (None, True))):
            self.assertEqual(m.pick(info), want)

    def test_no_captions_and_missing_yt_dlp(self):
        self.assertEqual(self.fetch("v", "https://youtu.be/abc123"), (1, ["FAIL", "v", "missing tool: yt-dlp"]))
        self.tools(yt_dlp=lambda cmd: json.dumps({"title": "silent", "subtitles": {"live_chat": [{}]}}))
        self.assertEqual(self.fetch("v", "https://www.youtube.com/shorts/abc123"), (1, ["FAIL", "v", "no captions"]))

    def test_ocr_when_no_text_layer(self):
        pdf = self.tmp / "scan.pdf"
        pdf.write_bytes(PDF)
        self.tools(pdftotext=lambda cmd: None)
        self.assertEqual(self.fetch("scan", pdf),
                         (1, ["FAIL", "scan", "no text layer, and OCR needs pdftoppm and tesseract"]))

        def pdftoppm(cmd):
            for n in (1, 2, 10):
                Path(f"{cmd[-1]}-{n:02d}.png").write_bytes(b"png")

        def tesseract(cmd):
            if cmd[1] == "--list-langs":
                return "List of available languages (3):\neng\nkor\nosd\n"
            self.assertEqual(cmd[2:], ["stdout", "-l", "eng+kor"])
            return f"text of {Path(cmd[1]).stem} " + "word " * 150
        self.tools(pdftotext=lambda cmd: None, pdftoppm=pdftoppm, tesseract=tesseract)
        code, f = self.fetch("scan", pdf)
        self.assertEqual((code, f[2], f[5]), (0, "scan.txt", "ocr"))
        self.assertEqual([p.split()[2] for p in self.read("scan.txt").split("\f")], ["page-01", "page-02", "page-10"])


if __name__ == "__main__":
    unittest.main()
