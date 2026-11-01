import contextlib, io, json, os, shutil, tempfile, unittest, urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests._load import load

m = load("scripts/watch.py")
FIX = Path(__file__).resolve().parent / "fixtures" / "watch"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
RSS = "https://blog.example.com/feed.xml"
ATOM = "https://atom.example.com/feed"
OA = "https://api.openalex.org"
OA_FEED = (f"{OA}/works?filter=primary_location.source.id:S123&sort=publication_date:desc&per-page=100"
           "&select=id,doi,display_name,publication_date,primary_location,abstract_inverted_index")
OA_NOW = OA_FEED.replace("S123&", "S123,to_publication_date:2026-10-30&")  # the request: nothing dated after today


def work(n, title, day, doi=True, abstract=None):
    """One work of an OpenAlex /works list; abstract is plain text, sent as abstract_inverted_index."""
    index = {}
    for k, w in enumerate((abstract or "").split()):
        index.setdefault(w, []).append(k)
    return {"id": f"https://openalex.org/W{n}", "doi": f"https://doi.org/10.1/w{n}" if doi else None, "display_name": title,
            "publication_date": day, "abstract_inverted_index": index or None,
            "primary_location": {"landing_page_url": f"https://journal.example.com/article/{n}"}}


def works(*rows):
    return json.dumps({"meta": {"count": len(rows)}, "results": list(rows)}).encode()


def fixture(name):
    return (FIX / name).read_bytes()


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


class FixedClock(m.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class Opener:
    """Fake opener: URL to body bytes, HTTP status, (status, headers, body), an exception, or a list of those served
    in turn; records every URL."""

    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def open(self, req, timeout=None):
        self.urls.append(req.full_url)
        r = self.routes.get(req.full_url, 404)
        if isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, tuple):
            raise urllib.error.HTTPError(req.full_url, r[0], "error", r[1], io.BytesIO(r[2]))
        if isinstance(r, int):
            raise urllib.error.HTTPError(req.full_url, r, "error", {}, None)
        return io.BytesIO(r)


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.top = Path(tempfile.mkdtemp()) / "topic"
        self.addCleanup(shutil.rmtree, self.top.parent)
        self.sleep = mock.patch("time.sleep").start()
        mock.patch.object(m, "datetime", FixedClock).start()
        mock.patch.object(m, "egress_terms", lambda cwd=None: []).start()
        mock.patch.dict(os.environ, {"OPENALEX_API_KEY": ""}).start()
        self.addCleanup(mock.patch.stopall)

    def run_watch(self, routes, cmd, *args):
        """Exit code, stdout lines and requested URLs of one watch.py call on the test topic."""
        opener, out = Opener(routes), io.StringIO()
        with mock.patch.object(m, "OPENER", opener), contextlib.redirect_stdout(out):
            code = m.main([cmd, str(self.top), *args])
        return code, out.getvalue().splitlines(), opener.urls

    def feeds(self, *rows):
        """watch.tsv with (kind, name, feed) rows."""
        self.top.mkdir(parents=True, exist_ok=True)
        lines = "".join(f"{k}\t{n}\t{f}\t{f}\n" for k, n, f in rows)
        (self.top / "watch.tsv").write_text("kind\tname\tfeed\tsource\n" + lines, encoding="utf-8")

    def state(self):
        return json.loads((self.top / "watch-state.json").read_text(encoding="utf-8"))

    def test_bad_state_file_fails_before_any_request(self):
        self.feeds(("rss", "blog", RSS))
        for text in ("{broken", "[]"):
            with self.subTest(text=text):
                (self.top / "watch-state.json").write_text(text, encoding="utf-8")
                code, out, urls = self.run_watch({RSS: fixture("rss.xml")}, "check")
                self.assertEqual((code, urls), (1, []))
                self.assertEqual(out[-1].split("\t")[-1], "not a valid state file; fix or remove it")

    def test_doctype_and_entity_refused(self):
        for body in (b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "x">]><rss><channel><title>&a;</title></channel></rss>',
                     b"<!doctype rss><rss/>", b'<rss><!ENTITY a "x"></rss>',
                     '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss><rss/>'.encode("utf-16")):
            with self.assertRaisesRegex(m.Fail, r"^refused: DOCTYPE or ENTITY in feed$"):
                m.parse(body)
        self.feeds(("rss", "bomb", RSS))
        code, out, _ = self.run_watch({RSS: b"<!DOCTYPE rss><rss/>"}, "check")
        self.assertEqual(code, 1)
        self.assertEqual(out[0], "FAIL\tbomb\trefused: DOCTYPE or ENTITY in feed")

    def test_first_check_keeps_the_window_and_marks_everything_seen(self):
        self.feeds(("rss", "blog", RSS))
        code, out, _ = self.run_watch({RSS: fixture("rss.xml")}, "check")
        self.assertEqual(code, 0)
        self.assertEqual(out, ["NEW\t2026-10-27\tblog\tRecent post\thttps://blog.example.com/posts/recent"
                               "\tFirst line of the recent post & more.",
                               "# 1 new from 1 feeds, 0 quiet, 0 failed: watch/2026-10-30-1200.md"])
        self.assertEqual(self.state()[RSS], {"seen": ["https://blog.example.com/posts/old", "https://blog.example.com/posts/recent"],
                                             "checked": "2026-10-30T12:00:00Z"})

    def test_quiet_feed_shows_its_latest_item(self):
        self.feeds(("rss", "blog", RSS))
        self.run_watch({RSS: fixture("rss.xml")}, "check")
        code, out, _ = self.run_watch({RSS: fixture("rss.xml")}, "check")
        self.assertEqual(out, ["LATEST\t2026-10-27\tblog\tRecent post\thttps://blog.example.com/posts/recent",
                               "# 0 new from 0 feeds, 1 quiet, 0 failed: watch/2026-10-30-1200-2.md"])

    def test_fresh_brings_back_seen_items_in_the_window(self):
        self.feeds(("rss", "blog", RSS))
        self.run_watch({RSS: fixture("rss.xml")}, "check")
        _, out, _ = self.run_watch({RSS: fixture("rss.xml")}, "check", "--fresh")
        self.assertEqual([ln.split("\t")[3] for ln in out if ln.startswith("NEW")], ["Recent post"])
        _, out, _ = self.run_watch({RSS: fixture("rss.xml")}, "check", "--fresh", "--days", "40")
        self.assertEqual([ln.split("\t")[3] for ln in out if ln.startswith("NEW")], ["Recent post", "Old post"])

    def test_reddit_goes_through_arctic_shift(self):
        api = m.ARCTIC + "/api/posts/search?subreddit=Python&sort=desc&limit=100"
        code, out, urls = self.run_watch({api: fixture("arctic.json")}, "add", "https://old.reddit.com/r/Python/")
        self.assertEqual((code, out, urls), (0, [f"ADDED\treddit\treddit.com/r/Python\t{api}\t2 items, latest 2026-10-30"], [api]))
        code, out, urls = self.run_watch({api: fixture("arctic.json")}, "check")
        self.assertEqual(out[0], "NEW\t2026-10-30\treddit.com/r/Python\tAsk[2J me anything"
                                 "\thttps://www.reddit.com/r/Python/comments/abc123/ask_me_anything/\tFirst & only line")
        self.assertEqual(urls, [api])
        link = m.parse(fixture("arctic.json"), "reddit")[2][1]
        self.assertEqual((link["url"], link["first"]), ("https://www.reddit.com/r/Python/comments/def456/a_link_post/",
                                                        "https://example.com/article"))
        code, out, urls = self.run_watch({}, "add", "https://www.reddit.com/user/someone")
        self.assertEqual((code, urls), (1, []))

    def test_github_repo_resolves_to_releases_atom(self):
        self.assertEqual(self.run_watch({}, "list")[1], ["# no feeds yet: watch.py add <topic_dir> <url>"])
        feed = "https://github.com/example-org/example-tool/releases.atom"
        code, out, urls = self.run_watch({feed: fixture("github.atom")}, "add", "https://github.com/example-org/example-tool")
        self.assertEqual(out, [f"ADDED\tgithub-releases\tRelease notes from example-tool\t{feed}\t2 items, latest 2026-10-28"])
        self.assertEqual(urls, [feed])
        code, out, urls = self.run_watch({}, "add", "https://github.com/example-org/example-tool/releases")
        self.assertEqual((code, out, urls), (0, [f"EXISTS\tRelease notes from example-tool\t{feed}"], []))
        self.assertEqual(self.run_watch({}, "list")[1], [f"github-releases\tRelease notes from example-tool\t{feed}"
                                                         "\thttps://github.com/example-org/example-tool"])
        items = m.parse(fixture("github.atom"), "github-releases")[2]
        self.assertEqual([(i["title"], i["url"], i["date"], i["first"]) for i in items], [
            ("v2.1.0", "https://github.com/example-org/example-tool/releases/tag/v2.1.0", utc(2026, 10, 28, 15), "Changes"),
            ("v2.0.0", "https://github.com/example-org/example-tool/releases/tag/v2.0.0", utc(2026, 9, 1, 12), "Release 2.0.0")])

    def test_x_twitter_and_pixiv_refused_without_a_request(self):
        for url in ("https://x.com/someone", "https://mobile.twitter.com/someone/status/1", "https://www.pixiv.net/users/1"):
            self.assertEqual(self.run_watch({}, "add", url), (1, [f"FAIL\t{url}\tno public feed"], []))

    def test_autodiscovery_from_html(self):
        page = "https://blog.example.com/"
        code, out, urls = self.run_watch({page: fixture("page.html"), RSS: fixture("rss.xml")}, "add", page)
        self.assertEqual(out, [f"ADDED\trss\tExample Blog\t{RSS}\t2 items, latest 2026-10-27"])
        self.assertEqual(urls, [page, RSS])
        bare, rss = "https://plain.example.com/about", "https://plain.example.com/rss"
        routes = {bare: b"<!doctype html><html><body>No feed links</body></html>", rss: fixture("rdf.xml")}
        code, out, urls = self.run_watch(routes, "add", bare, "plain")
        self.assertEqual(out, [f"ADDED\trss\tplain\t{rss}\t1 items, latest 2026-10-28"])
        self.assertEqual(urls, [bare, "https://plain.example.com/feed", rss])
        code, out, _ = self.run_watch({"https://none.example.com/": b"<html></html>"}, "add", "https://none.example.com/")
        self.assertEqual((code, out), (1, ["FAIL\thttps://none.example.com/\tno feed found"]))

    def test_same_minute_check_keeps_the_first_results_file(self):
        self.feeds(("rss", "blog", RSS))
        self.run_watch({RSS: fixture("rss.xml")}, "check")
        first = (self.top / "watch" / "2026-10-30-1200.md").read_text(encoding="utf-8")
        self.run_watch({RSS: fixture("rss.xml")}, "check")
        self.assertEqual((self.top / "watch" / "2026-10-30-1200.md").read_text(encoding="utf-8"), first)
        self.assertTrue((self.top / "watch" / "2026-10-30-1200-2.md").is_file())
        self.assertTrue(first.startswith("# watch topic 2026-10-30 12:00 UTC\n\n## New\n\n"
                                         "- 1. 2026-10-27 blog: [Recent post](https://blog.example.com/posts/recent)\n"
                                         "  > First line of the recent post & more.\n"))

    def test_many_new_items_print_a_numbered_index(self):
        def rss(n):
            items = "".join(f"<item><title>Post {k} with a title long enough to be cut short in the printed index line</title>"
                            f"<link>https://blog.example.com/posts/{k}</link>"
                            f"<pubDate>Tue, {k:02d} Oct 2026 09:00:00 GMT</pubDate><description>Line {k}.</description></item>"
                            for k in range(1, n + 1))
            return f"<rss><channel><title>B</title>{items}</channel></rss>".encode()
        self.feeds(("rss", "blog", RSS))
        _, out, _ = self.run_watch({RSS: rss(20)}, "check", "--days", "40")  # 20 new: full lines as before
        self.assertEqual([ln.split("\t")[0] for ln in out[:-1]], ["NEW"] * 20)
        shutil.rmtree(self.top / "watch")
        (self.top / "watch-state.json").unlink()
        _, out, _ = self.run_watch({RSS: rss(25)}, "check", "--days", "40")  # over 20: a numbered index only
        index = [ln.split("\t") for ln in out if ln.startswith("INDEX")]
        self.assertEqual(len(index), 25)
        self.assertEqual(index[0][:4], ["INDEX", "1", "2026-10-25", "blog"])
        self.assertEqual(index[-1][:4], ["INDEX", "25", "2026-10-01", "blog"])
        self.assertTrue(index[0][4].startswith("Post 25 with a title") and len(index[0][4]) <= 60, index[0][4])
        joined = "\n".join(out)
        self.assertNotIn("NEW\t", joined)
        self.assertNotIn("https://blog.example.com/posts/", joined)  # links and first lines stay in the file
        self.assertNotIn("Line 25.", joined)
        self.assertIn("grep", out[-2])
        self.assertEqual(out[-1], "# 25 new from 1 feeds, 0 quiet, 0 failed: watch/2026-10-30-1200.md")
        md = (self.top / "watch" / "2026-10-30-1200.md").read_text(encoding="utf-8")
        self.assertIn("- 1. 2026-10-25 blog: [Post 25 with a title long enough to be cut short in the printed index line]"
                      "(https://blog.example.com/posts/25)\n  > Line 25.\n", md)
        self.assertIn("\n- 25. 2026-10-01 blog: [Post 1 ", md)
        doc = (Path(__file__).resolve().parents[1] / "skills" / "search" / "references" / "watch.md").read_text(encoding="utf-8")
        for text in (m.__doc__, doc):
            self.assertIn("INDEX", text)
            self.assertRegex(" ".join(text.split()), r"(?i)over 20 new items")

    def test_one_failing_feed_does_not_stop_the_others(self):
        self.feeds(("rss", "down", RSS), ("atom", "up", ATOM))
        code, out, _ = self.run_watch({RSS: 500, ATOM: fixture("atom.xml")}, "check")
        self.assertEqual(code, 0)
        self.assertEqual([ln.split("\t")[:4] for ln in out[:3]], [["NEW", "2026-10-28", "up", "Atom entry one"],
                                                                 ["NEW", "2026-10-26", "up", "Atom entry two"],
                                                                 ["FAIL", "down", "http 500"]])
        self.assertEqual(out[3], "# 2 new from 1 feeds, 0 quiet, 1 failed: watch/2026-10-30-1200.md")
        self.assertEqual(list(self.state()), [ATOM])

    def test_check_exit_codes(self):
        self.feeds(("rss", "flaky", RSS), ("atom", "down", ATOM))
        code, out, _ = self.run_watch({RSS: [503, fixture("rss.xml")], ATOM: 404}, "check")  # one answered after a 503
        self.assertEqual((code, out[-2]), (0, "FAIL\tdown\thttp 404"))
        code, out, _ = self.run_watch({RSS: fixture("rss.xml"), ATOM: 404}, "check")  # nothing new now: quiet
        self.assertEqual((code, out[0].split("\t")[0]), (0, "LATEST"))
        code, out, _ = self.run_watch({RSS: [503] * 4, ATOM: 404}, "check")  # every feed failed
        self.assertEqual((code, out[-1].split(", ")[-1].split(":")[0]), (1, "2 failed"))
        doc = (Path(__file__).resolve().parents[1] / "skills" / "search" / "references" / "watch.md").read_text(encoding="utf-8")
        for text in (m.__doc__, doc):  # the exit codes are stated where the model and a reader look
            self.assertIn("exit 1 when every feed failed", " ".join(text.split()))
            self.assertIn("exit 0 when some feeds failed and others answered", " ".join(text.split()))

    def test_titles_with_control_and_bidi_characters_print_clean(self):
        dirty = ("<rss><channel><title>T</title><item><title>Safe\U0000202e\U0000200b\x85 \U0000201cquoted\U0000201d\ttitle</title>"
                 "<link>https://e.example.com/1</link><pubDate>Thu, 29 Oct 2026 00:00:00 GMT</pubDate>"
                 "<description>line\U00002066 one</description></item></channel></rss>").encode()
        self.feeds(("rss", "dirty\U0000202ename", RSS))
        _, out, _ = self.run_watch({RSS: dirty}, "check")
        self.assertEqual(out[0], 'NEW\t2026-10-29\tdirtyname\tSafe "quoted" title\thttps://e.example.com/1\tline one')

    def test_rss_atom_and_rdf_dates(self):
        self.assertEqual([i["date"] for i in m.parse(fixture("rss.xml"))[2]], [utc(2026, 10, 27, 0, 30), utc(2026, 9, 30, 10)])
        self.assertEqual([i["date"] for i in m.parse(fixture("atom.xml"))[2]], [utc(2026, 10, 28, 10), utc(2026, 10, 26, 9)])
        self.assertEqual([i["date"] for i in m.parse(fixture("rdf.xml"))[2]], [utc(2026, 10, 28, 23)])
        self.assertEqual(m.to_utc("Tue, 27 Oct 2026 09:30:00 -0000"), utc(2026, 10, 27, 9, 30))
        self.assertEqual(m.to_utc("2026-10-27"), utc(2026, 10, 27))
        self.assertIsNone(m.to_utc("soon"))

    def test_429_backs_off_then_retries(self):
        self.feeds(("rss", "blog", RSS))
        _, out, urls = self.run_watch({RSS: [429, 429, fixture("rss.xml")]}, "check")
        self.assertEqual(urls, [RSS] * 3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list if c.args[0] >= 2], [2, 4])
        self.assertTrue(out[0].startswith("NEW\t2026-10-27"))
        _, out, urls = self.run_watch({RSS: [429] * 4}, "check")
        self.assertEqual((len(urls), out[0]), (4, "FAIL\tblog\thttp 429"))

    def test_5xx_and_timeouts_are_retried_walls_are_not(self):
        self.feeds(("rss", "blog", RSS))
        flaky = [503, urllib.error.URLError(TimeoutError("timed out")), (500, {"Retry-After": "9"}, b""), fixture("rss.xml")]
        _, out, urls = self.run_watch({RSS: flaky}, "check")
        self.assertEqual(urls, [RSS] * 4)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list if c.args[0] >= 2], [2, 4, 9])
        self.assertTrue(out[0].startswith("NEW\t2026-10-27"))
        for reply, why in (((503, {}, b"<title>Just a moment...</title>"), "http 503: bot check"),
                           ((403, {"X-RateLimit-Remaining": "0"}, b""), "http 403")):
            with self.subTest(why=why):
                _, out, urls = self.run_watch({RSS: [reply, fixture("rss.xml")]}, "check")
                self.assertEqual((len(urls), out[0]), (1, f"FAIL\tblog\t{why}"))

    def test_one_run_deadline_across_feeds(self):
        self.feeds(("rss", "blog", RSS), ("atom", "news", ATOM))
        with mock.patch.object(m, "DEADLINE", 5):
            code, out, urls = self.run_watch({RSS: [(429, {"Retry-After": "30"}, b""), fixture("rss.xml")], ATOM: fixture("atom.xml")}, "check")
        self.assertEqual(urls[0], RSS)
        self.assertIn("FAIL\tblog\thttp 429; run deadline reached", out)
        with mock.patch.object(m, "DEADLINE", 0):
            code, out, urls = self.run_watch({RSS: fixture("rss.xml")}, "check")
        self.assertEqual((code, urls), (1, []))
        self.assertIn("FAIL\tnews\trun deadline reached", out)
        self.assertIsNone(m._end)

    def test_egress_blocks_listed_terms_before_any_request(self):
        url = "https://example.com/search?q=Acme%2DSecret"
        with mock.patch.object(m, "egress_terms", lambda cwd=None: [("acme-secret", "forbidden.txt")]):
            self.assertEqual(self.run_watch({}, "add", url), (1, [
                f"FAIL\t{url}\tegress: 'acme-secret' is listed in forbidden.txt; use a generic problem statement"], []))

        def unreadable(cwd=None):
            raise ValueError("bad list")
        with mock.patch.object(m, "egress_terms", unreadable):
            code, out, urls = self.run_watch({}, "add", "https://example.com/")
        self.assertEqual((code, urls), (1, []))
        self.assertTrue(out[0].startswith("FAIL\thttps://example.com/\tegress: "))

    def test_check_rechecks_the_terms_before_each_feed(self):
        secret = "https://acme-secret.example.com/feed"
        self.feeds(("rss", "blog", RSS), ("rss", "private", secret), ("atom", "news", ATOM))
        calls = []

        def terms(cwd=None):
            calls.append(1)
            return [("acme-secret", "forbidden.txt")]
        with mock.patch.object(m, "egress_terms", terms):
            code, out, urls = self.run_watch({RSS: fixture("rss.xml"), ATOM: fixture("atom.xml"), secret: fixture("rss.xml")},
                                             "check")
        self.assertEqual((code, urls, len(calls)), (0, [RSS, ATOM], 3))
        self.assertIn("FAIL\tprivate\tegress: 'acme-secret' is listed in forbidden.txt; use a generic problem statement", out)
        self.assertNotIn(secret, self.state())

        def unreadable(cwd=None):
            raise ValueError("bad list")
        with mock.patch.object(m, "egress_terms", unreadable):
            code, out, urls = self.run_watch({RSS: fixture("rss.xml")}, "check")
        self.assertEqual((code, urls), (1, []))
        self.assertIn("FAIL\tblog\tegress: cannot read the term list: bad list", out)

    # openalex: journals and proceedings without a feed

    def test_openalex_source_by_id_is_added_and_checked(self):
        source = json.dumps({"id": "https://openalex.org/S123", "display_name": "Journal of Widgets"}).encode()
        listing = works(work(2, "Widget engines at scale", "2026-10-28", abstract="We scale widget engines. Then we stop."),
                        work(1, "Old widget study", "2026-08-01", doi=False))
        routes = {f"{OA}/sources/S123?select=id,display_name": source, OA_NOW: listing}
        code, out, urls = self.run_watch(routes, "add", "openalex:S123")
        self.assertEqual((code, out), (0, [f"ADDED\topenalex\tJournal of Widgets\t{OA_FEED}\t2 items, latest 2026-10-28"]))
        self.assertEqual(urls, [f"{OA}/sources/S123?select=id,display_name", OA_NOW])
        self.assertIn(f"openalex\tJournal of Widgets\t{OA_FEED}\thttps://openalex.org/S123\n",
                      (self.top / "watch.tsv").read_text(encoding="utf-8"))
        self.assertEqual(self.run_watch(routes, "add", "openalex:https://openalex.org/S123")[1],
                         [f"EXISTS\tJournal of Widgets\t{OA_FEED}"])
        code, out, urls = self.run_watch(routes, "check")
        self.assertEqual(out[0], "NEW\t2026-10-28\tJournal of Widgets\tWidget engines at scale\thttps://doi.org/10.1/w2"
                                 "\tWe scale widget engines.")
        self.assertEqual((code, urls), (0, [OA_NOW]))
        # a later check lists the works published since the last one; an older work indexed late is not new
        later = works(work(3, "Widget engines, again", "2026-10-30"), work(4, "Late-indexed widget paper", "2026-10-02", doi=False),
                      work(2, "Widget engines at scale", "2026-10-28"))
        code, out, _ = self.run_watch({OA_NOW: later}, "check")
        self.assertEqual([ln.split("\t")[3:5] for ln in out if ln.startswith("NEW")],
                         [["Widget engines, again", "https://doi.org/10.1/w3"]])
        code, out, _ = self.run_watch({OA_NOW: later}, "check", "--fresh", "--days", "60")
        self.assertIn(["Late-indexed widget paper", "https://journal.example.com/article/4"],
                      [ln.split("\t")[3:5] for ln in out if ln.startswith("NEW")])

    def test_openalex_source_by_name(self):
        def search(*names):
            return json.dumps({"results": [{"id": f"https://openalex.org/S{n}", "display_name": d} for n, d in names]}).encode()
        url = f"{OA}/sources?search=widget+systems&per-page=10&select=id,display_name"
        exact = search((7, "Widget Systems Letters"), (8, "Widget Systems"))
        code, out, urls = self.run_watch({url.replace("widget", "Widget"): exact, OA_NOW.replace("S123", "S8"): works()}, "add",
                                         "openalex:Widget systems")
        self.assertEqual((code, out[0].split("\t")[:3]), (0, ["ADDED", "openalex", "Widget Systems"]))
        code, out, _ = self.run_watch({url: search((7, "Widget Systems Letters"), (9, "Widget Systems Review"))}, "add",
                                      "openalex:widget systems")
        self.assertEqual((code, out), (1, ["FAIL\topenalex:widget systems\tambiguous: S7 Widget Systems Letters; "
                                           "S9 Widget Systems Review; add it by its S id"]))
        code, out, _ = self.run_watch({url: search()}, "add", "openalex:widget systems")
        self.assertEqual((code, out), (1, ["FAIL\topenalex:widget systems\tno OpenAlex source matches widget systems"]))

    def test_openalex_egress_shape_and_key(self):
        with mock.patch.object(m, "egress_terms", lambda cwd=None: [("acme-secret", "forbidden.txt")]):
            self.assertEqual(self.run_watch({}, "add", "openalex:Acme-Secret Journal"), (1, [
                "FAIL\topenalex:Acme-Secret Journal\tegress: 'acme-secret' is listed in forbidden.txt; use a generic problem statement"], []))
        self.feeds(("openalex", "Journal of Widgets", OA_FEED))
        code, out, _ = self.run_watch({OA_NOW: b'{"error": "moved"}'}, "check")
        self.assertEqual((code, out[0]), (1, "FAIL\tJournal of Widgets\tnot an OpenAlex works response"))
        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "k3y"}):
            code, out, urls = self.run_watch({OA_NOW + "&api_key=k3y": works()}, "check")
        self.assertEqual((code, urls), (0, [OA_NOW + "&api_key=k3y"]))
        self.assertNotIn("k3y", "\n".join(out) + (self.top / "watch.tsv").read_text(encoding="utf-8"))

    def test_openalex_abstract_first_sentence(self):
        index = {"Widgets": [0], "matter.": [1], "We": [2], "show": [3], "why,": [4], "e.g.": [5], "in": [6], "labs.": [7]}
        self.assertEqual(m.abstract(index), "Widgets matter. We show why, e.g. in labs.")
        self.assertEqual(m.first_sentence(m.abstract(index)), "Widgets matter.")
        self.assertEqual(m.first_sentence("No full stop here"), "No full stop here")
        self.assertEqual(m.abstract({"x": ["0", True, -1]}), "")
        self.assertEqual(m.abstract(None), "")


if __name__ == "__main__":
    unittest.main()
