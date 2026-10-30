import contextlib
import io
import json
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
                answer = routes.get(self.path, (404, {}, b"not found"))
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

    def test_arxiv_html_fallback(self):
        s = self.serve({"/pdf/2508.00001": (200, {"Content-Type": "application/pdf"}, PDF),
                        "/html/2508.00001": (200, HTML, page("<article><h1>Paper title</h1>" + LONG + "</article>"))})
        self.patch(m, "ARXIV", s.url)
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text(" \f \n", encoding="utf-8"))
        code, f = self.fetch("arxiv-2508.00001-x", "https://arxiv.org/abs/2508.00001")
        self.assertEqual((code, f[2], f[4], f[5]), (0, "arxiv-2508.00001-x.md", "# Paper title", "arxiv-html"))
        self.assertEqual(s.seen, ["/pdf/2508.00001", "/html/2508.00001"])
        self.assertEqual(sorted(p.name for p in self.src.iterdir()), ["arxiv-2508.00001-x.md", "arxiv-2508.00001-x.pdf"])

    def test_nothing_is_written_after_a_fail(self):
        s = self.serve({"/pdf/2508.00002": (200, {"Content-Type": "application/pdf"}, PDF)})  # no HTML version
        self.patch(m, "ARXIV", s.url)
        self.tools(pdftotext=lambda cmd: Path(cmd[-1]).write_text("", encoding="utf-8"))
        self.assertEqual(self.fetch("p", "https://arxiv.org/pdf/2508.00002.pdf"), (1, ["FAIL", "p", "http 404"]))
        self.assertEqual(s.seen, ["/pdf/2508.00002", "/html/2508.00002"])
        self.assertEqual(list(self.src.iterdir()), [])

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
