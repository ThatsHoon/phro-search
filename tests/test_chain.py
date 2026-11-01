import contextlib
import http.client
import io
import json
import os
import socket
import ssl
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from pathlib import Path
from unittest import mock

from tests._load import ROOT, load

m = load("scripts/chain.py")
FIX = ROOT / "tests" / "fixtures" / "chain"
BATES = "W1964729842"
BATES_ROW = ("1989\t1761\tW1964729842\tThe design of browsing and berrypicking techniques for the online search "
             "interface\t10.1108/eb024320\t-\t-\t-\t-")
BATES_WORK = "# work\tW1964729842\t1989\tThe design of browsing and berrypicking techniques for the online search interface\t-"
SPECIAL_DOI = "10.1002/(sici)1097-4571(1999)50:12<1043::aid-asi1>3.0.co;2-x"
NOTE_EMPTY = ("# note: 0 results. OpenAlex often lacks citation links for works under about a year old, so this means "
              "unknown, not none: grep the reference section of the downloaded text, or search for works citing the title.")


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def query(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)


def path(url):
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path)


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://api.openalex.org/x", code, "error", headers, None)


def page(reply, q):
    """The reply cut to the requested page size, as the real API does."""
    return {**reply, "results": reply["results"][:int(q["per-page"][0])]}


def api(p, q):
    """Answers like OpenAlex for the recorded works and authors."""
    if p == "/authors":
        return page(fx("authors_marcia_bates.json"), q)
    if p == "/authors/A5046418008":
        return fx("author_one.json")
    if p.lower() in ("/works/" + BATES.lower(), "/works/doi:10.1108/eb024320"):
        return fx("work_bates.json")
    if p == "/works/doi:" + SPECIAL_DOI:
        return fx("work_special_doi.json")
    if p.startswith(("/works/", "/authors/")):
        return http_error(404)
    kind, _, value = q["filter"][0].partition(":")
    if kind == "title.search":
        return page(fx("title_berrypicking.json" if value == "berrypicking" else "empty.json"), q)
    if kind == "cites":
        return page(fx("cites.json"), q)
    if kind == "author.id":
        return page(fx("author_works.json"), q)
    if kind == "openalex":
        rows = [w for w in fx("refs_batch.json")["results"] if w["id"].rsplit("/", 1)[-1] in value.split("|")]
        return {"results": rows}
    raise AssertionError(f"unexpected request {p} {q}")


class Resp:
    """The part of an HTTP response the script uses."""

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.asked = None

    def read(self, n=-1):
        self.asked = n
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    """Stands in for the script's opener: asks the handler for each reply and records the requests."""

    def __init__(self, handler):
        self.handler, self.reqs, self.timeouts, self.resps = handler, [], [], []

    def open(self, req, timeout=None):
        self.reqs.append(req)
        self.timeouts.append(timeout)
        u = urllib.parse.urlsplit(req.full_url)
        reply = self.handler(urllib.parse.unquote(u.path), urllib.parse.parse_qs(u.query))
        if isinstance(reply, BaseException):
            raise reply
        self.resps.append(Resp(reply))
        return self.resps[-1]


class ChainTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        env = mock.patch.dict(os.environ, {"HOME": tmp.name, "USERPROFILE": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(tmp.name)
        sleep = mock.patch.object(m.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        m._last = 0.0
        self.project("{}")  # the nearest project file wins, so a file further up cannot add terms
        guard = mock.patch.object(m, "_opener", Opener(lambda p, q: AssertionError("live request")))
        guard.start()
        self.addCleanup(guard.stop)

    def call(self, *argv, handler=api):
        """(exit code, stdout lines, requested URLs) of one call of the script against the fake API."""
        self.opener = Opener(handler)
        out = io.StringIO()
        with mock.patch.object(m, "_opener", self.opener), contextlib.redirect_stdout(out):
            code = m.main(list(argv))
        return code, out.getvalue().splitlines(), [r.full_url for r in self.opener.reqs]

    def forbid(self, *terms):
        d = Path(self.home) / ".claude" / "phro-search"
        d.mkdir(parents=True)
        (d / "forbidden.txt").write_text("# comment\n" + "\n".join(terms) + "\n", encoding="utf-8")
        return str(d / "forbidden.txt")

    def project(self, text):
        d = Path.cwd().resolve() / ".phro"
        d.mkdir(exist_ok=True)
        (d / "project.json").write_text(text, encoding="utf-8")
        return str(d / "project.json")

    # find

    def test_title_search_ranks_by_citations(self):
        code, lines, urls = self.call("find", "berrypicking")
        self.assertEqual(code, 0)
        self.assertEqual(len(urls), 1)
        q = query(urls[0])
        self.assertEqual(path(urls[0]), "/works")
        self.assertEqual((q["filter"], q["sort"], q["per-page"]), (["title.search:berrypicking"], ["cited_by_count:desc"], ["5"]))
        self.assertNotIn("search", q)
        self.assertEqual([l.split("\t")[2] for l in lines],
                         [w["id"].rsplit("/", 1)[-1] for w in fx("title_berrypicking.json")["results"]])
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[0], BATES_ROW)
        self.assertEqual(lines[2].split("\t")[4:6],
                         ["10.1002/meet.14504201241", "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/meet.14504201241"])

    def test_title_is_cleaned_for_the_filter(self):
        # Commas separate OpenAlex filters, | means OR, a leading ! negates and upper-case AND, OR, NOT are operators.
        code, lines, urls = self.call("find", "Exploratory", "search: from finding,", "to")
        self.assertEqual(query(urls[0])["filter"], ["title.search:Exploratory search: from finding to"])
        self.assertEqual((code, lines), (0, ["# note: no match; try the DOI, or a shorter title without the subtitle."]))
        code, lines, urls = self.call("find", "!Search AND browse|scan, OR NOT")
        self.assertEqual(query(urls[0])["filter"], ["title.search:Search and browse scan or not"])

    def test_doi_url_and_ids_resolve_the_same_work(self):
        cases = [("10.1108/eb024320", "/works/doi:10.1108/eb024320"),
                 ("https://doi.org/10.1108/eb024320", "/works/doi:10.1108/eb024320"),
                 ("https://doi.org/10.1108/EB024320", "/works/doi:10.1108/EB024320"),
                 ("doi:10.1108/eb024320", "/works/doi:10.1108/eb024320"),
                 ("W1964729842", "/works/W1964729842"),
                 ("w1964729842", "/works/W1964729842"),
                 ("https://openalex.org/W1964729842", "/works/W1964729842")]
        for key, want in cases:
            with self.subTest(key=key):
                code, lines, urls = self.call("find", key)
                self.assertEqual((code, lines, [path(u) for u in urls]), (0, [BATES_ROW], [want]))

    def test_odd_doi_is_quoted_in_the_path(self):
        code, lines, urls = self.call("find", "https://doi.org/" + SPECIAL_DOI)
        raw = urllib.parse.urlsplit(urls[0]).path
        self.assertEqual(code, 0)
        self.assertTrue(not {"<", ">", ";", "("} & set(raw), raw)
        self.assertEqual(path(urls[0]), "/works/doi:" + SPECIAL_DOI)
        self.assertEqual(lines[0].split("\t")[4], SPECIAL_DOI)

    def test_request_headers_and_no_credentials(self):
        self.call("find", BATES)
        req = self.opener.reqs[0]
        self.assertEqual(req.get_header("User-agent"),
                         f"Mozilla/5.0 (compatible; phro-search/{m.VERSION}; +https://github.com/ThatsHoon/phro-search)")
        self.assertEqual(self.opener.timeouts, [30])
        self.assertEqual([r.asked for r in self.opener.resps], [m.CAP + 1])
        self.assertTrue(req.full_url.startswith("https://api.openalex.org/works/W1964729842?"))
        for word in ("mailto", "api_key", "email"):
            self.assertNotIn(word, req.full_url)

    # refs and cites

    def test_refs_name_the_work_and_sort_by_citations(self):
        code, lines, urls = self.call("refs", "10.1108/eb024320")
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], BATES_WORK)
        self.assertEqual([int(l.split("\t")[1]) for l in lines[1:]], [931, 144, 55, 21, 20, 10])
        self.assertEqual(lines[1], "1968\t931\tW1602667807\tAutomatic information organization and retrieval\t-\t-\t-\t-\t-")
        self.assertEqual(len(urls), 2)
        q = query(urls[1])
        self.assertEqual(q["filter"], ["openalex:W195302104|W1570378841|W1602667807|W1964020902|W1974170312|W1979070506"])
        self.assertEqual(q["sort"], ["cited_by_count:desc"])

    def test_refs_merge_batches_and_keep_the_top_n(self):
        with mock.patch.object(m, "BATCH", 2):
            code, lines, urls = self.call("refs", BATES, "-n", "4")
        self.assertEqual(len(urls), 4)
        for u in urls[1:]:
            self.assertLessEqual(len(query(u)["filter"][0].partition(":")[2].split("|")), 2)
        self.assertEqual([int(l.split("\t")[1]) for l in lines[1:]], [931, 144, 55, 21])

    def test_cites_rows(self):
        code, lines, urls = self.call("cites", "https://openalex.org/W1964729842", "-n", "3")
        q = query(urls[1])
        self.assertEqual((code, lines[0], len(urls)), (0, BATES_WORK, 2))
        self.assertEqual((q["filter"], q["sort"], q["per-page"]), (["cites:W1964729842"], ["cited_by_count:desc"], ["3"]))
        self.assertEqual([l.split("\t")[2] for l in lines[1:]], ["W2111335329", "W1570418772", "W2017022128"])
        self.assertEqual(lines[2], "2016\t1543\tW1570418772\tLooking for Information: A Survey of Research on Information "
                                   "Seeking, Needs, and Behavior\t10.1108/s2055-53772016\t-\t-\t-\t-")

    def test_empty_refs_and_cites_give_the_note(self):
        def new_paper(p, q):
            if p.startswith("/works/"):
                return {"id": "https://openalex.org/W9", "display_name": "A new paper", "publication_year": 2026}
            return fx("empty.json")

        for cmd, requests in (("refs", 1), ("cites", 2)):  # a work without references needs no batch request
            with self.subTest(cmd=cmd):
                code, lines, urls = self.call(cmd, "W9", handler=new_paper)
                self.assertEqual((code, lines, len(urls)), (0, ["# work\tW9\t2026\tA new paper\t-", NOTE_EMPTY], requests))

    # author

    def test_author_header_and_other_matches(self):
        code, lines, urls = self.call("author", "Marcia", "Bates")
        self.assertEqual(code, 0)
        self.assertEqual(lines[:3], [
            "# author\tA5046418008\tMarcia J. Bates\tUniversity of California, Los Angeles\t110 works",
            "# other matches\tA5062361148 Marcia H. Bates (-)",
            "# other matches\tA5106234332 Marcia Bates (North Carolina State University)"])
        self.assertEqual(len(lines), 3 + 5)
        self.assertEqual(lines[3], BATES_ROW)
        self.assertEqual(path(urls[0]), "/authors")
        self.assertEqual((query(urls[0])["search"], query(urls[0])["per-page"]), (["Marcia Bates"], ["4"]))
        q = query(urls[1])
        self.assertEqual((path(urls[1]), q["filter"], q["sort"], q["per-page"]),
                         ("/works", ["author.id:A5046418008"], ["cited_by_count:desc"], ["20"]))

    def test_author_other_matches_stop_at_three(self):
        many = {"results": [{"id": f"https://openalex.org/A{i}", "display_name": f"Pat {i}", "works_count": i} for i in range(1, 6)]}
        code, lines, urls = self.call("author", "Pat", handler=lambda p, q: many if p == "/authors" else fx("empty.json"))
        self.assertEqual([l.split("\t")[0] for l in lines], ["# author", "# other matches", "# other matches", "# other matches",
                                                              "# note: no works listed for that author."])
        self.assertEqual(lines[0], "# author\tA1\tPat 1\t-\t1 works")

    def test_author_by_id_has_no_other_matches(self):
        code, lines, urls = self.call("author", "https://openalex.org/A5046418008", "-n", "2")
        self.assertEqual(code, 0)
        self.assertEqual([path(u) for u in urls], ["/authors/A5046418008", "/works"])
        self.assertEqual(query(urls[1])["per-page"], ["2"])
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("# author\tA5046418008\tMarcia J. Bates\t"))

    def test_author_without_a_match(self):
        code, lines, urls = self.call("author", "Nobody Here", handler=lambda p, q: fx("empty.json"))
        self.assertEqual((code, len(urls)), (0, 1))
        self.assertEqual(lines, ["# note: no author matches; check the spelling, or pass an A id."])

    # egress

    def test_egress_hit_sends_nothing(self):
        src = self.forbid("acme-secret")
        for argv in (("find", "ACME-Secret", "battery"), ("find", "acme%2Dsecret"), ("author", "acme-secret person")):
            with self.subTest(argv=argv):
                code, lines, urls = self.call(*argv)
                self.assertEqual(code, 1)
                self.assertEqual(lines, [f"FAIL\tegress: 'acme-secret' is listed in {src}; use a generic problem statement"])
                self.assertEqual(urls, [])

    def test_egress_terms_from_the_project_file(self):
        src = self.project(json.dumps({"egress": {"forbidden_terms": ["Zebra Project"]}}))
        code, lines, urls = self.call("find", "zebra project battery")
        self.assertEqual((code, urls), (1, []))
        self.assertEqual(lines, [f"FAIL\tegress: 'Zebra Project' is listed in {src}; use a generic problem statement"])
        self.assertEqual(self.call("find", "zebra projects")[0], 0)  # the term must not touch another letter

    def test_unreadable_term_sources_fail_closed(self):
        for text in ("{not json", json.dumps({"egress": {"forbidden_terms": "oops"}})):
            with self.subTest(text=text):
                self.project(text)
                code, lines, urls = self.call("find", "battery model")
                self.assertEqual((code, urls), (1, []))
                self.assertTrue(lines[0].startswith("FAIL\tegress: cannot read the forbidden terms"), lines)

    def test_egress_matching_copy_is_intact(self):
        terms = [("acme-secret", "f"), ("ai", "f")]
        self.assertEqual(m.egress_hit("Acme%2DSecret battery", terms), ("acme-secret", "f"))
        self.assertIsNone(m.egress_hit("said maintain", terms))
        self.assertEqual(m.egress_hit("an AI model", terms), ("ai", "f"))

    # output safety

    def test_printed_fields_are_sanitized(self):
        work = {"id": "https://openalex.org/W7", "publication_year": 2020, "cited_by_count": 3,
                "display_name": "Intro\U0000202e\U0000200bduction\x00 to\t\U0000201cquoted\U0000201d \U00002018x\U00002019\nnext line" + " pad" * 100,
                "doi": "https://doi.org/10.1/abc\U0000202e\ndef", "best_oa_location": {"pdf_url": "https://x.example/a\tb.pdf"}}
        code, lines, _ = self.call("find", "W7", handler=lambda p, q: work)
        cols = lines[0].split("\t")
        self.assertEqual((code, len(lines), len(cols)), (0, 1, 9))
        self.assertTrue(cols[3].startswith("Introduction to \"quoted\" 'x' next line pad"), cols[3])
        self.assertLessEqual(len(cols[3]), 200)
        self.assertEqual(cols[4:6], ["10.1/abc def", "https://x.example/a b.pdf"])
        self.assertTrue(all(c.isprintable() for c in cols))

    def test_author_lines_are_sanitized(self):
        evil = {"id": "https://openalex.org/A1", "display_name": "Evil\U0000202e\nName", "works_count": 2,
                "last_known_institutions": [{"display_name": "Uni\x00versity\tX"}]}
        code, lines, _ = self.call("author", "A1", handler=lambda p, q: evil if p == "/authors/A1" else fx("empty.json"))
        self.assertEqual(lines[0], "# author\tA1\tEvil Name\tUniversity X\t2 works")

    def test_free_pdf_choice(self):
        base = {"id": "https://openalex.org/W5", "display_name": "T", "publication_year": 2000, "cited_by_count": 0}
        cases = [({"best_oa_location": {"pdf_url": "https://a/p.pdf"}, "open_access": {"oa_url": "https://a/page"}}, "https://a/p.pdf"),
                 ({"best_oa_location": {"pdf_url": None}, "open_access": {"oa_url": "https://a/page"}}, "https://a/page"),
                 ({"best_oa_location": None, "open_access": {"oa_url": None}}, "-"),
                 ({}, "-")]
        for extra, want in cases:
            with self.subTest(want=want, extra=extra):
                cols = m.row({**base, **extra}).split("\t")
                self.assertEqual((cols[1], cols[4], cols[5]), ("0", "-", want))

    # columns, flags and open-access copies

    def test_type_venue_and_flags(self):
        base = {"id": "https://openalex.org/W5", "display_name": "T", "publication_year": 2020, "cited_by_count": 1}
        accepted = {"is_oa": True, "version": "acceptedVersion", "pdf_url": "https://repo.example/a.pdf",
                    "source": {"type": "repository", "display_name": "Repo"}}
        cases = [({"type": "preprint", "is_retracted": True, "locations": [accepted],
                   "primary_location": {"source": {"display_name": "arXiv (Cornell University)"}}},
                  ["preprint", "arXiv (Cornell University)", "retracted,preprint,accepted-copy"]),
                 ({"type": "erratum"}, ["erratum", "-", "erratum"]),
                 ({"type": "retraction"}, ["retraction", "-", "erratum"]),
                 ({"type": "editorial", "primary_location": {"source": None}}, ["editorial", "-", "comment"]),
                 ({"type": "article", "locations": [dict(accepted, is_oa=False)]}, ["article", "-", "-"]),
                 ({}, ["-", "-", "-"])]
        for extra, want in cases:
            with self.subTest(want=want):
                self.assertEqual(m.row({**base, **extra}).split("\t")[6:], want)

    def test_oa_lists_legal_copies_best_first(self):
        def loc(version, kind, pdf=None, landing=None, name="Src", license=None, oa=True):
            return {"is_oa": oa, "version": version, "pdf_url": pdf, "landing_page_url": landing, "license": license,
                    "source": {"type": kind, "display_name": name}}
        work = {"id": "https://openalex.org/W8", "display_name": "A paper", "publication_year": 2021, "type": "article",
                "locations": [loc("publishedVersion", "journal", "https://pub.example/p.pdf", "https://pub.example/p",
                                  "Journal", "cc-by"),
                              loc("acceptedVersion", "repository", "https://repo.example/a.pdf", name="Uni repository"),
                              loc("submittedVersion", "repository", "https://arxiv.org/pdf/2101.00001",
                                  "https://arxiv.org/abs/2101.00001", "arXiv (Cornell University)"),
                              loc("publishedVersion", "repository", None, "https://pmc.example/a", "PubMed Central"),
                              loc("publishedVersion", "journal", "https://closed.example/x.pdf", oa=False),
                              loc(None, None, None, "https://blog.example/post", "-")]}
        code, lines, urls = self.call("oa", "W8", handler=lambda p, q: work)
        self.assertEqual((code, [path(u) for u in urls]), (0, ["/works/W8"]))
        self.assertEqual(lines, [
            "# work\tW8\t2021\tA paper\taccepted-copy",
            "published\tpublisher\thttps://pub.example/p.pdf\thttps://pub.example/p\tJournal\tcc-by",
            "accepted\trepository\thttps://repo.example/a.pdf\t-\tUni repository\t-",
            "submitted\trepository\thttps://arxiv.org/pdf/2101.00001\thttps://arxiv.org/abs/2101.00001"
            "\tarXiv (Cornell University)\t-",
            "published\trepository\t-\thttps://pmc.example/a\tPubMed Central\t-",
            "-\tother\t-\thttps://blog.example/post\t-\t-"])

    def test_oa_without_copies(self):
        work = {"id": "https://openalex.org/W9", "display_name": "Closed", "publication_year": 2019, "locations": []}
        code, lines, _ = self.call("oa", "10.1234/closed", handler=lambda p, q: work)
        self.assertEqual((code, lines[0]), (0, "# work\tW9\t2019\tClosed\t-"))
        self.assertTrue(lines[1].startswith("# note: no open-access copy is listed"), lines)

    def test_cites_sorted_by_recency_and_since_a_year(self):
        code, lines, urls = self.call("cites", BATES, "--sort", "recent", "--since", "2020", "-n", "3")
        q = query(urls[1])
        self.assertEqual((code, q["filter"], q["sort"]),
                         (0, ["cites:W1964729842,from_publication_date:2020-01-01"], ["publication_date:desc"]))

    def test_review_fixes(self):
        self.forbid("acme secret")
        code, lines, urls = self.call("find", "acme,secret", "battery")  # the comma becomes a space before sending
        self.assertEqual((code, urls), (1, []))
        retracted = {"id": "https://openalex.org/W3", "display_name": "Gone", "publication_year": 2018, "is_retracted": True}
        self.assertEqual(self.call("oa", "W3", handler=lambda p, q: retracted)[1][0], "# work\tW3\t2018\tGone\tretracted")
        code, lines, urls = self.call("find", "https://doi.org/10.1234/x%3Cy%3E", handler=lambda p, q: retracted)
        self.assertEqual((code, path(urls[0])), (0, "/works/doi:10.1234/x<y>"))

    def test_api_key_comes_from_the_environment_only(self):
        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "k-secret-123"}):
            code, lines, urls = self.call("find", BATES)
            self.assertEqual((code, query(urls[0])["api_key"]), (0, ["k-secret-123"]))
            code, lines, _ = self.call("find", BATES, handler=lambda p, q: http_error(500))
            self.assertEqual((code, lines), (1, ["FAIL\thttp 500"]))
        code, lines, urls = self.call("find", BATES)
        self.assertNotIn("api_key", urls[0])

    # network behavior

    def sleeps(self):
        return [c.args[0] for c in self.sleep.call_args_list]

    def test_429_retries_and_honors_retry_after(self):
        for header, wait in (("3", 3), ("120", 2), ("soon", 2), (None, 2)):
            with self.subTest(retry_after=header):
                self.sleep.reset_mock()
                m._last = 0.0
                replies = [http_error(429, header), fx("work_bates.json")]
                code, lines, urls = self.call("find", BATES, handler=lambda p, q: replies.pop(0))
                self.assertEqual((code, lines, len(urls)), (0, [BATES_ROW], 2))
                self.assertEqual(self.sleeps(), [wait])  # the wait also covers the 1 s spacing

    def test_429_backoff_then_fail(self):
        code, lines, urls = self.call("find", BATES, handler=lambda p, q: http_error(429))
        self.assertEqual(code, 1)
        self.assertEqual(lines, [f"FAIL\t{m.RATE_LIMITED}"])
        self.assertIn("1,000", m.RATE_LIMITED)
        self.assertEqual(len(urls), 4)
        self.assertEqual(self.sleeps(), [2, 4, 8])

    def test_one_second_between_requests(self):
        m._last = m.time.monotonic()
        self.call("find", BATES)
        self.assertTrue(0.5 < self.sleep.call_args_list[0].args[0] <= 1)

    def test_errors_become_fail_lines(self):
        cases = [(http_error(404), "FAIL\tnot in OpenAlex: W1964729842"),
                 (http_error(500), "FAIL\thttp 500"),
                 (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")), "FAIL\tdns"),
                 (urllib.error.URLError(ssl.SSLCertVerificationError("bad certificate")), "FAIL\ttls"),
                 (urllib.error.URLError(TimeoutError("timed out")), "FAIL\ttimeout"),
                 (TimeoutError("The read operation timed out"), "FAIL\ttimeout"),
                 (http.client.RemoteDisconnected("Remote end closed connection"), "FAIL\tRemote end closed connection")]
        for err, want in cases:
            with self.subTest(want=want):
                code, lines, _ = self.call("find", BATES, handler=lambda p, q: err)
                self.assertEqual((code, lines), (1, [want]))
        self.assertEqual(self.call("find", "10.1108/zzz-nope")[:2], (1, ["FAIL\tnot in OpenAlex: 10.1108/zzz-nope"]))

    def test_too_large_and_not_json(self):
        with mock.patch.object(m, "CAP", 10):
            self.assertEqual(self.call("find", BATES, handler=lambda p, q: b"x" * 11)[:2], (1, ["FAIL\ttoo large"]))
        self.assertEqual(self.call("find", BATES, handler=lambda p, q: b"<html>")[:2], (1, ["FAIL\tnot json"]))
        self.assertEqual(self.call("find", BATES, handler=lambda p, q: [1])[:2], (1, ["FAIL\tunexpected reply from the API"]))

    def test_308_redirect_is_followed(self):
        req = urllib.request.Request("https://api.openalex.org/works")
        new = m._Redirect().redirect_request(req, None, 308, "Permanent Redirect", Message(), "https://api.openalex.org/other")
        self.assertEqual(new.full_url, "https://api.openalex.org/other")
        self.assertTrue(callable(m._Redirect.http_error_308))

    def test_bad_usage_exits_2(self):
        for argv in (["refs", "just a title"], ["cites", "W1", "-n", "0"], ["refs", "W1", "-n", "201"], ["find"], [],
                     ["cites", "W1", "--since", "20"], ["cites", "W1", "--sort", "newest"], ["oa", "a title"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                m.main(argv)
            self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
