import contextlib, io, json, os, shutil, tempfile, threading, time, unittest, urllib.error, urllib.request
from datetime import datetime
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._load import load

m = load("scripts/pulse.py")
AS_OF = "2026-10-30"  # with 30 days the window is 2026-10-01T00:00Z to 2026-10-31T00:00Z
HANG = object()


def ts(day, hour=12):
    return int(datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00").timestamp())


def js(x):
    return json.dumps(x).encode()


# Responses in the shapes the live endpoints return (synthetic: real ones carry other people's posts).

def story(i, title, day, points=10, comments=0, url=None, author="ann"):
    return {"objectID": str(i), "title": title, "url": url, "author": author, "points": points,
            "num_comments": comments, "created_at_i": ts(day), "story_text": None}


def post(i, sub, title, day, score=10, comments=0, url=None, author="bob"):  # the fields pulse.py asks for
    return {"id": i, "subreddit": sub, "title": title, "url": url or f"https://www.reddit.com/r/{sub}/comments/{i}/slug/",
            "author": author, "score": score, "num_comments": comments, "created_utc": ts(day), "selftext": ""}


def repo(name, day, stars=100, desc=""):
    return {"full_name": name, "owner": {"login": name.split("/")[0]}, "pushed_at": f"{day}T12:00:00Z",
            "stargazers_count": stars, "description": desc}


def issue(name, n, title, day, reactions=1, comments=0):
    return {"html_url": f"https://github.com/{name}/issues/{n}", "comments_url": f"https://api.github.com/repos/{name}/issues/{n}/comments",
            "title": title, "user": {"login": "dev"}, "created_at": f"{day}T12:00:00Z", "reactions": {"total_count": reactions},
            "comments": comments, "body": ""}


def feed(*entries):
    """An arXiv Atom feed of (id, title, day, summary) entries."""
    body = "".join(f"<entry><id>http://arxiv.org/abs/{i}v1</id><title>{t}</title><published>{d}T00:00:00Z</published>"
                   f"<summary>{s}</summary><author><name>A. Author</name></author></entry>" for i, t, d, s in entries)
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'.encode()


def model(name, day, likes=5, downloads=100, trending=2, tags=("transformers", "region:us")):
    """One model of the Hub's /api/models list with full metadata."""
    return {"_id": "x", "id": name, "modelId": name, "author": name.split("/")[0], "likes": likes, "downloads": downloads,
            "trendingScore": trending, "tags": list(tags), "pipeline_tag": "text-generation", "library_name": "transformers",
            "createdAt": f"{day}T10:00:00.000Z", "lastModified": f"{day}T11:00:00.000Z", "private": False}


def daily(pid, title, upvotes=10, comments=0, summary=""):
    """One entry of the Hub's /api/daily_papers list."""
    return {"paper": {"id": pid, "authors": [{"name": "A. Author"}], "publishedAt": "2026-10-01T00:00:00.000Z", "title": title,
                      "summary": summary, "upvotes": upvotes}, "title": title, "numComments": comments}


class Resp(io.BytesIO):
    """A response body with headers, for a route that must answer with a Link header."""

    def __init__(self, body, headers):
        super().__init__(body)
        self.headers = headers


def sub(label="main", query="widget engine", ranking="widget engine for rust", lanes=("hn",), weight=1.0):
    return {"label": label, "search_query": query, "ranking_query": ranking, "lanes": list(lanes), "weight": weight}


class Opener:
    """Fake opener: the first route whose substrings all appear in the URL answers with body bytes, an HTTP status,
    a (status, headers[, body]) tuple, HANG (blocks for good) or a list of those served in turn; records URLs and headers."""

    def __init__(self, routes):
        self.routes, self.urls, self.headers = routes, [], []

    def open(self, req, timeout=None):
        self.urls.append(req.full_url)
        self.headers.append(dict(req.header_items()))
        r = next((r for keys, r in self.routes if all(k in req.full_url for k in keys)), 404)
        if isinstance(r, list):
            r = r.pop(0)
        if r is HANG:
            threading.Event().wait()
        if isinstance(r, Exception):
            raise r
        if isinstance(r, tuple):  # (status, headers) or (status, headers, body)
            raise urllib.error.HTTPError(req.full_url, r[0], "error", r[1], io.BytesIO(r[2]) if len(r) > 2 else None)
        if isinstance(r, int):
            raise urllib.error.HTTPError(req.full_url, r, "error", {}, None)
        return r if isinstance(r, Resp) else io.BytesIO(r)


def no_run(cmd, **kw):
    raise AssertionError("yt-dlp must not run")


class PulseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.top = self.tmp / "topic"
        self.sleep = mock.patch("time.sleep").start()
        mock.patch.object(m, "egress_terms", lambda cwd=None: []).start()
        mock.patch.dict(os.environ, {"GH_TOKEN": "", "GITHUB_TOKEN": ""}).start()
        self.addCleanup(mock.patch.stopall)

    def run_pulse(self, plan, routes, *args, ytdlp=None, top=None):
        """Exit code, stdout lines, the result JSON (None without an OK line) and the opener of one pulse.py call."""
        path = self.tmp / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        opener, out = Opener(routes), io.StringIO()
        with mock.patch.object(m, "OPENER", opener), mock.patch.object(m, "RUN", ytdlp or no_run), \
                mock.patch.object(m.shutil, "which", lambda name: "yt-dlp" if ytdlp else None), contextlib.redirect_stdout(out):
            code = m.main([str(top or self.top), "--plan", str(path), "--as-of", AS_OF, *args])
        lines = out.getvalue().splitlines()
        ok = [line.split("\t") for line in lines if line.startswith("OK\t")]
        return code, lines, json.loads(Path(ok[0][1]).read_text(encoding="utf-8")) if ok else None, opener

    @staticmethod
    def lanes(lines):
        return {f[1]: f[2] for f in (line.split("\t") for line in lines) if f[0] == "LANE"}

    def test_bad_plan_exits_2_before_any_request(self):
        good = {"subqueries": [sub()]}
        for bad in ([1], {"subqueries": []}, {"subqueries": [{"search_query": " "}]}, {"subqueries": [sub(lanes=("x",))]},
                    {"subqueries": [sub(weight=0)]}, {"subqueries": [sub(), sub()]}, {**good, "subreddits": ["no such"]},
                    {**good, "github_repos": ["../x"]}, {**good, "days": 0}, {**good, "freshness": "soon"}):
            with self.subTest(bad=bad):
                code, lines, result, opener = self.run_pulse(bad, [])
                self.assertEqual((code, opener.urls, result), (2, [], None))
                self.assertTrue(lines[-1].startswith("FAIL\tplan\t"))

    def test_egress_hit_blocks_every_request(self):
        with mock.patch.object(m, "egress_terms", lambda cwd=None: [("acme", "forbidden.txt")]):
            code, lines, result, opener = self.run_pulse({"subqueries": [sub()], "github_repos": ["acme/widget"]}, [])
        self.assertEqual((code, opener.urls, result), (2, [], None))
        self.assertIn("egress: 'acme' is listed in forbidden.txt", lines[-1])

    def test_requests_carry_the_window_and_one_subreddit_each(self):
        plan = {"subqueries": [sub(lanes=("hn", "reddit", "github", "arxiv"))], "subreddits": ["rust", "r/programming"],
                "dedicated_subreddits": ["widgets"], "github_repos": ["acme/widget"]}
        code, lines, result, opener = self.run_pulse(plan, [])
        lo, hi = ts("2026-10-01", 0), ts("2026-10-31", 0)
        self.assertEqual([u for u in opener.urls if "hn.algolia.com" in u],
                         [f"{m.HN}/search?query=widget+engine&tags=story&numericFilters="
                          f"created_at_i%3E%3D{lo},created_at_i%3C{hi}&hitsPerPage=50"])
        posts = [u for u in opener.urls if "/posts/search" in u]
        self.assertTrue(all(f"after={lo}&before={hi}" in u and "&fields=id,title," in u for u in posts))
        self.assertEqual(sorted(u.split("&subreddit=")[1] for u in posts),
                         ["programming&query=widget+engine", "rust&query=widget+engine", "widgets", "widgets&query=widget+engine"])
        gh = [u for u in opener.urls if "api.github.com" in u]
        self.assertEqual(gh, [f"{m.GH}/search/repositories?q=widget+engine+pushed%3A2026-10-01..2026-10-30&sort=stars&order=desc&per_page=50",
                              f"{m.GH}/search/issues?q=widget+engine+created%3A2026-10-01..2026-10-30&sort=reactions&order=desc&per_page=50",
                              f"{m.GH}/repos/acme/widget",
                              f"{m.GH}/search/issues?q=repo%3Aacme%2Fwidget+created%3A2026-10-01..2026-10-30&sort=reactions&order=desc&per_page=50",
                              f"{m.GH}/repos/acme/widget/releases?per_page=10"])
        self.assertEqual([u for u in opener.urls if "arxiv" in u],
                         [f"{m.ARXIV}?search_query=all:widget+AND+all:engine&sortBy=submittedDate&sortOrder=descending&max_results=50"])
        self.assertEqual(code, 1)  # every request got a 404, and yt-dlp is missing

    def test_items_outside_the_window_drop(self):
        hits = {"hits": [story(1, "Widget engine 2 is out", "2026-10-20"), story(2, "Widget engine 1 retrospective", "2026-09-29"),
                         story(3, "Widget engine roadmap", "2026-10-31")]}
        code, lines, result, _ = self.run_pulse({"subqueries": [sub()]}, [(("hn.algolia.com",), js(hits))])
        self.assertEqual([i["id"] for i in result["items"]], ["hn:1"])
        self.assertIn("# window 2026-10-01T00:00:00Z to 2026-10-31T00:00:00Z (UTC)", lines)

    def test_same_url_from_two_lanes_merges_and_keeps_both_engagements(self):
        hits = {"hits": [story(1, "Widget engine: a fast engine for widgets", "2026-10-20", points=300, url="https://github.com/Acme/Widget")]}
        repos = {"items": [repo("acme/widget", "2026-10-25", stars=1200, desc="Widget engine for rust")]}
        code, lines, result, _ = self.run_pulse({"subqueries": [sub(lanes=("hn", "github"))]},
                                                [(("hn.algolia.com",), js(hits)), (("search/repositories",), js(repos)),
                                                 (("search/issues",), js({"items": []}))])
        (item,) = result["items"]
        self.assertEqual(item["lanes"], ["github", "hn"])
        self.assertEqual(item["engagement"], {"hn": {"points": 300, "comments": 0}, "github": {"stars": 1200}})
        self.assertEqual(item["links"]["hn"], "https://news.ycombinator.com/item?id=1")
        self.assertEqual((result["clusters"][0]["lanes"], result["clusters"][0]["labels"]), (["github", "hn"], []))

    def test_score_rises_with_engagement_and_recency(self):
        hits = {"hits": [story(1, "Widget engine one", "2026-10-20", points=500), story(2, "Widget engine two", "2026-10-20", points=5),
                         story(3, "Widget engine three", "2026-10-29", points=5)]}
        code, lines, result, _ = self.run_pulse({"subqueries": [sub()]}, [(("hn.algolia.com",), js(hits))])
        s = {i["id"]: i["score"] for i in result["items"]}
        self.assertGreater(s["hn:1"], s["hn:2"])  # more points on the same day
        self.assertGreater(s["hn:3"], s["hn:2"])  # the same points, later

    def test_items_without_the_entity_head_token_stay_out_of_clusters(self):
        hits = {"hits": [story(1, "Widget engine 2.0 released", "2026-10-20", points=50), story(2, "A faster engine for widgets", "2026-10-21")]}
        code, lines, result, _ = self.run_pulse({"entity": "Widget engine", "subqueries": [sub()]}, [(("hn.algolia.com",), js(hits))])
        by = {i["id"]: i for i in result["items"]}
        self.assertEqual([(by[k]["grounded"], by[k]["pool"]) for k in ("hn:1", "hn:2")], [(True, True), (False, False)])
        self.assertNotIn("hn:2", {i for c in result["clusters"] + result["weak"] for i in c["items"]})

    def test_a_cluster_spanning_lanes_outranks_a_single_lane_one_of_equal_score(self):
        def item(i, lanes, title):
            return {"id": i, "url": f"https://example.com/{i}", "lanes": lanes, "score": 50.0, "relevance": 0.8, "title": title,
                    "_tok": set(m.content(title)), "_top": False}
        out = m.cluster([item("a", ["hn"], "alpha story"), item("b", ["hn", "reddit"], "beta story")])
        self.assertEqual([(c["items"], c["score"], c["labels"], c["_solid"]) for c in out],
                         [(["b"], 55.0, [], True), (["a"], 50.0, ["single-lane"], False)])

    def test_nothing_over_the_floor_gives_the_empty_state(self):
        papers = feed(("2610.00001", "Widget engine scheduling", "2026-10-20", "We study widget engines."))
        code, lines, result, _ = self.run_pulse({"subqueries": [sub(lanes=("arxiv",))]}, [(("export.arxiv.org",), papers)])
        self.assertEqual((code, result["clusters"], len(result["weak"])), (0, [], 1))
        self.assertIn("# nothing solid in the window: no cluster spans 2 lanes or leads its lane's engagement", lines)
        self.assertEqual(result["items"][0]["url"], "https://arxiv.org/abs/2610.00001")

    def test_a_hanging_lane_is_cut_at_the_deadline(self):
        papers = feed(("2610.00001", "Widget engine scheduling", "2026-10-20", "Widget engine study."))
        code, lines, result, _ = self.run_pulse({"subqueries": [sub(lanes=("hn", "arxiv"))]},
                                                [(("hn.algolia.com",), HANG), (("export.arxiv.org",), papers)], "--deadline", "0.5")
        self.assertEqual((code, self.lanes(lines)["hn"], result["lanes"]["arxiv"]["status"]), (0, "timeout", "ok"))

    def test_one_failing_lane_is_reported_and_the_rest_finish(self):
        hits = {"hits": [story(1, "Widget engine 2 is out", "2026-10-20", points=50)]}
        code, lines, result, _ = self.run_pulse({"subqueries": [sub(lanes=("hn", "reddit"))], "subreddits": ["rust"]},
                                                [(("hn.algolia.com",), js(hits)), (("arctic-shift",), 503)])
        self.assertEqual(code, 0)
        self.assertEqual(self.lanes(lines), {"hn": "ok", "reddit": "failed: http 503"})
        self.assertEqual([i["id"] for i in result["items"]], ["hn:1"])

    def test_every_lane_failing_exits_1(self):
        code, lines, result, opener = self.run_pulse({"subqueries": [sub(lanes=("hn", "github"))]},
                                                     [(("hn.algolia.com",), 500), (("api.github.com",), (403, {"X-RateLimit-Remaining": "0"}))])
        self.assertEqual((code, result["items"]), (1, []))
        lanes = {f[1]: f[2:] for f in (line.split("\t") for line in lines) if f[0] == "LANE"}
        self.assertEqual((lanes["hn"][0], lanes["github"][0]), ("failed: http 500", "rate-limited"))
        self.assertIn("set GH_TOKEN", lanes["github"][1])
        self.assertEqual(sum("api.github.com" in u for u in opener.urls), 1)  # nothing more is asked once rate-limited

    def test_the_same_responses_give_the_same_output(self):
        routes = [(("hn.algolia.com", "/search?"), js({"hits": [story(1, "Widget engine 2 is out", "2026-10-20", points=50, url="https://example.com/we2"),
                                                               story(2, "Widget engine internals", "2026-10-12", points=20)]})),
                  (("/posts/search",), js({"data": [post("ab1", "rust", "Widget engine 2 released", "2026-10-21", score=40, url="https://example.com/we2"),
                                                     post("ab2", "rust", "Help with widget engine", "2026-10-15")]})),
                  (("search/repositories",), js({"items": [repo("acme/widget", "2026-10-28", stars=900, desc="Widget engine")]})),
                  (("search/issues",), js({"items": [issue("acme/widget", 7, "Widget engine crash on start", "2026-10-22", reactions=12)]}))]
        runs = []
        for n in (1, 2):
            code, lines, result, _ = self.run_pulse({"subqueries": [sub(lanes=("hn", "reddit", "github"))], "subreddits": ["rust"]},
                                                    routes, top=self.tmp / f"run{n}" / "topic")
            out = Path(lines[-1].split("\t")[1])
            runs.append((code, lines[:-1], out.read_text(encoding="utf-8"), out.with_name(out.stem + "-evidence.md").read_text(encoding="utf-8")))
        self.assertEqual(runs[0], runs[1])
        self.assertIn(["hn", "reddit"], [c["lanes"] for c in result["clusters"]])  # one URL from two lanes

    def test_comments_of_the_best_items(self):
        tree = {"id": 1, "children": [{"id": 11, "author": "x", "text": "<p>Short one</p>", "children": []},
                                      {"id": 12, "author": "y", "text": "Widget engine finally &amp; fast",
                                       "children": [{"id": 13, "text": "agree", "children": []}]},
                                      {"id": 14, "author": None, "text": None, "children": None}]}
        thread = {"data": [{"id": "c1", "author": "AutoModerator", "body": "Rules", "score": 99},
                           {"id": "c2", "author": "zed", "body": "[removed]", "score": 50},
                           {"id": "c3", "author": "amy", "body": "Works well for me", "score": 7},
                           {"id": "c4", "author": "rust-ModTeam", "body": "Removed", "score": 5}]}
        gh = [{"user": {"login": "lee"}, "body": "Same crash here", "reactions": {"total_count": 4}, "html_url": "https://github.com/acme/widget/issues/7#c1"},
              {"user": {"login": "kim"}, "body": "Fixed in main", "reactions": {"total_count": 9}, "html_url": "https://github.com/acme/widget/issues/7#c2"}]
        routes = [(("hn.algolia.com", "/search?"), js({"hits": [story(1, "Widget engine 2 is out", "2026-10-20", points=50, comments=3)]})),
                  (("hn.algolia.com", "/items/1"), js(tree)),
                  (("/posts/search",), js({"data": [post("ab1", "rust", "Widget engine 2 released", "2026-10-21", comments=4)]})),
                  (("/comments/search", "link_id=ab1"), js(thread)),
                  (("search/repositories",), js({"items": []})),
                  (("search/issues",), js({"items": [issue("acme/widget", 7, "Widget engine crash", "2026-10-22", comments=2)]})),
                  (("/repos/acme/widget/issues/7/comments?per_page=30",), js(gh))]
        code, lines, result, _ = self.run_pulse({"subqueries": [sub(lanes=("hn", "reddit", "github"))], "subreddits": ["rust"]}, routes)
        by = {i["id"]: i for i in result["items"]}
        self.assertEqual([(c["author"], c["score"], c["text"]) for c in by["hn:1"]["comments"]],
                         [("y", 1, "Widget engine finally & fast"), ("x", 0, "Short one")])
        self.assertEqual([(c["author"], c["url"]) for c in by["reddit:ab1"]["comments"]],
                         [("amy", "https://www.reddit.com/r/rust/comments/ab1/comment/c3/")])
        self.assertEqual([c["author"] for c in by["github:https://github.com/acme/widget/issues/7"]["comments"]], ["kim", "lee"])
        self.assertEqual({k: v["status"] for k, v in result["lanes"].items()}, {"hn": "ok", "reddit": "ok", "github": "ok"})
        evidence = (self.top / "pulse" / "2026-10-30-evidence.md").read_text(encoding="utf-8")
        self.assertIn("comment by amy (7) <https://www.reddit.com/r/rust/comments/ab1/comment/c3/>: Works well for me", evidence)

    def test_github_token_is_sent_and_never_printed(self):
        secret = "test-token-not-real-0123456789"
        routes = [(("search/repositories",), js({"items": [repo("acme/widget", "2026-10-28", desc="Widget engine")]})),
                  (("search/issues",), js({"items": []}))]
        with mock.patch.dict(os.environ, {"GH_TOKEN": secret}):
            code, lines, result, opener = self.run_pulse({"subqueries": [sub(lanes=("github",))]}, routes)
        self.assertEqual([h.get("Authorization") for h in opener.headers], [f"Bearer {secret}"] * 2)
        files = "".join(p.read_text(encoding="utf-8") for p in (self.top / "pulse").iterdir())
        self.assertNotIn(secret, "\n".join(lines) + files)

    def test_youtube_lane(self):
        plan = {"subqueries": [sub(lanes=("youtube",))]}
        code, lines, result, _ = self.run_pulse(plan, [])
        self.assertEqual((code, result["lanes"]["youtube"]), (1, {"status": "skipped", "count": 0, "note": "yt-dlp is not installed"}))
        calls = []

        def run(cmd, capture_output=True, timeout=None):
            calls.append(cmd)
            out = (js({"entries": [{"id": "vid000001", "title": "Widget engine in 10 minutes", "channel": "Chan", "view_count": 5000},
                                   {"id": "vid000002", "title": "Widget engine deep dive", "channel": "Chan", "view_count": 300}]})
                   if "--flat-playlist" in cmd else b"vid000001\t20261025\t5100\t240\t31\nvid000002\tNA\tNA\tNA\tNA\n")
            return SimpleNamespace(returncode=0, stdout=out, stderr=b"")
        code, lines, result, _ = self.run_pulse(plan, [], ytdlp=run, top=self.tmp / "yt" / "topic")
        by = {i["id"]: i for i in result["items"]}
        self.assertEqual((by["youtube:vid000001"]["date"], by["youtube:vid000001"]["engagement"]),
                         ("2026-10-25", {"youtube": {"views": 5100, "likes": 240, "comments": 31}}))
        self.assertIsNone(by["youtube:vid000002"]["date"])
        self.assertTrue(calls[0][-1].endswith("search_query=widget+engine&sp=EgIIBA%253D%253D"))  # uploaded this month
        self.assertEqual(calls[1][-2:], ["https://www.youtube.com/watch?v=vid000001", "https://www.youtube.com/watch?v=vid000002"])

    def test_arxiv_refuses_a_doctype_and_merges_across_versions(self):
        plan = {"subqueries": [sub(lanes=("hn", "arxiv"))]}
        evil = b'<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY a "x">]><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        code, lines, result, _ = self.run_pulse(plan, [(("hn.algolia.com",), js({"hits": []})), (("export.arxiv.org",), evil)])
        self.assertEqual((code, result["lanes"]["arxiv"]["status"], result["lanes"]["hn"]["status"]),
                         (0, "failed: unreadable response from arXiv", "no-results"))
        hits = {"hits": [story(1, "Widget engine scheduling paper", "2026-10-21", points=80, url="https://arxiv.org/pdf/2610.00001v2.pdf")]}
        papers = feed(("2610.00001", "Widget engine scheduling", "2026-10-20", "Widget engine study."))
        code, lines, result, _ = self.run_pulse(plan, [(("hn.algolia.com",), js(hits)), (("export.arxiv.org",), papers)],
                                                top=self.tmp / "b" / "topic")
        (item,) = result["items"]
        self.assertEqual((item["lanes"], m.norm_url(item["url"])), (["arxiv", "hn"], "arxiv.org/abs/2610.00001"))

    def test_dedicated_subreddits_skip_the_relevance_floor(self):
        plan = {"subqueries": [sub(lanes=("reddit",))], "subreddits": ["rust"], "dedicated_subreddits": ["widgets"]}
        routes = [(("subreddit=rust",), js({"data": [post("aa1", "rust", "Borrow checker question", "2026-10-20")]})),
                  (("subreddit=widgets&query",), js({"data": []})),
                  (("subreddit=widgets",), js({"data": [post("bb1", "widgets", "Show off your setup", "2026-10-22")]}))]
        code, lines, result, _ = self.run_pulse(plan, routes)
        self.assertEqual([(i["id"], i["exempt"]) for i in result["items"]], [("reddit:bb1", True)])

    def test_a_named_repository_is_an_item_kept_without_the_floor(self):
        plan = {"subqueries": [sub(lanes=("github",))], "github_repos": ["acme/gizmo"]}
        routes = [(("/repos/acme/gizmo/releases",), js([])), (("/repos/acme/gizmo",), js(repo("acme/gizmo", "2026-10-28", stars=84))),
                  (("search/repositories",), js({"items": [repo("acme/gizmo", "2026-10-28", stars=84)]})), (("search/issues",), js({"items": []}))]
        _, _, result, _ = self.run_pulse(plan, routes)
        self.assertEqual([(i["id"], i["exempt"], i["engagement"]) for i in result["items"]],
                         [("github:acme/gizmo", True, {"github": {"stars": 84}})])  # one item, exempt though the search found it too

    def test_a_rerun_never_overwrites(self):
        papers = feed(("2610.00001", "Widget engine scheduling", "2026-10-20", "x"))
        names = [Path(self.run_pulse({"subqueries": [sub(lanes=("arxiv",))]}, [(("export.arxiv.org",), papers)])[1][-1].split("\t")[1]).name
                 for _ in range(2)]
        self.assertEqual(names, ["2026-10-30.json", "2026-10-30-2.json"])

    def test_a_body_counts_past_the_snippet(self):
        body = "Release notes. " * 40 + "It is a widget engine written in Rust."
        hits = [story(1, "Gizmo 2.0 is out", "2026-10-20", points=50)]
        hits[0]["story_text"] = body
        _, _, result, _ = self.run_pulse({"entity": "Widget", "subqueries": [sub()]}, [(("hn.algolia.com",), js({"hits": hits}))])
        it = result["items"][0]
        self.assertEqual(it["relevance"], 0.5)  # widget, engine and rust only past the first 300 characters: half
        self.assertTrue(it["grounded"])
        self.assertEqual(len(it["snippet"]), m.SNIP)
        gh = {"items": [dict(issue("acme/gizmo", 1, "Gizmo 2.0 is out", "2026-10-20"), body=body)]}
        _, _, result, _ = self.run_pulse({"subqueries": [sub(lanes=("github",))]}, [(("search/issues",), js(gh)), (("search/",), js({}))])
        self.assertEqual(result["items"], [])  # an issue body is not read past its lead: under the floor
        _, lines, _, _ = self.run_pulse({"subqueries": [sub(lanes=("reddit",))], "subreddits": ["rust"]},
                                        [(("/posts/search",), js({"data": None, "error": "Timeout. Maybe slow down a bit"}))])
        self.assertIn("arctic-shift: Timeout. Maybe slow down a bit", next(x for x in lines if x.startswith("LANE	reddit")))

    def test_relevance_caps_generic_matches_and_rewards_the_phrase(self):
        sq = {"search_query": "open source model", "ranking_query": "open source model for widget engines"}
        self.assertEqual(m.relevance("A new open source model", sq), m.GENERIC_CAP)
        self.assertEqual(m.relevance("widget engines, an open model", sq), 0.8)
        self.assertEqual(m.relevance("Open source model for widget engines", sq), 1.0)

    def test_urls_compare_by_the_story_they_name(self):
        for a, b in (("https://www.youtube.com/watch?v=abc&t=10s", "https://youtu.be/abc"),
                     ("https://arxiv.org/pdf/2610.00001v2.pdf", "http://arxiv.org/abs/2610.00001"),
                     ("https://github.com/Acme/Widget/", "https://github.com/acme/widget"),
                     ("https://example.com/a/?utm_source=x&b=1#top", "http://www.example.com/a?b=1")):
            self.assertEqual(m.norm_url(a), m.norm_url(b))
        self.assertEqual(m.link_key("https://github.com/acme/widget/releases/tag/v2"), "github.com/acme/widget")
        self.assertEqual(m.link_key("https://github.com/acme/widget/issues/7"), "github.com/acme/widget/issues/7")

    def test_redirects_stay_on_the_host(self):
        req = urllib.request.Request("https://api.github.com/repos/a/b/releases", headers={"Authorization": "Bearer t"})
        with self.assertRaises(urllib.error.URLError):
            m._Redirect().redirect_request(req, None, 302, "Found", Message(), "https://example.com/x")
        self.assertIsNotNone(m._Redirect().redirect_request(req, None, 301, "Moved", Message(), "https://api.github.com/repositories/1"))

    def test_reddit_asks_each_reddit_query_once_per_subreddit(self):
        def subs(plan):
            _, _, _, opener = self.run_pulse(plan, [(("/posts/search",), js({"data": []}))])
            return sorted(u.split("&subreddit=")[1] for u in opener.urls if "/posts/search" in u)
        two = [sub(lanes=("reddit",)), sub("rust", "widget engine rust", lanes=("reddit",), weight=0.6)]
        self.assertEqual(subs({"entity": "Widget", "subqueries": two, "subreddits": ["rust", "programming"]}),
                         ["programming&query=Widget", "rust&query=Widget"])  # the entity, not each subquery
        self.assertEqual(subs({"subqueries": two, "subreddits": ["rust"], "reddit_queries": ["widget", "gadget box"]}),
                         ["rust&query=gadget+box", "rust&query=widget"])
        self.assertEqual(subs({"subqueries": two, "subreddits": ["rust"]}), ["rust&query=widget+engine"])
        for bad in ({"reddit_queries": ["a", "b", "c", "d"]}, {"reddit_queries": [""]}, {"reddit_queries": "widget"}):
            code, lines, _, opener = self.run_pulse({"subqueries": two, "subreddits": ["rust"], **bad}, [])
            self.assertEqual((code, opener.urls), (2, []), bad)
        code, _, _, _ = self.run_pulse({"subqueries": [sub(label="reddit")]}, [])
        self.assertEqual(code, 2)

    def test_arctic_shift_busy_is_retried(self):
        url = f"{m.ARCTIC}/posts/search?subreddit=rust&query=x"
        busy = (422, {}, b'{"data":null,"error":"Timeout. Maybe slow down a bit"}')
        with mock.patch.object(m, "OPENER", Opener([(("arctic-shift",), [busy, busy, b"{}"])])):
            self.assertEqual(m.fetch(url), b"{}")
        self.assertEqual([c.args for c in self.sleep.call_args_list if c.args[0] >= 2], [(2,), (4,)])
        opener = Opener([(("arctic-shift",), [(422, {}, b'{"error":"bad parameter"}'), b"{}"])])
        with mock.patch.object(m, "OPENER", opener), self.assertRaises(m.Fail) as e:
            m.fetch(url)
        self.assertEqual((str(e.exception), len(opener.urls)), ("http 422", 1))
        with mock.patch.object(m, "OPENER", Opener([(("arctic-shift",), [busy] * 4)])), self.assertRaises(m.Fail) as e:
            m.fetch(url)
        self.assertEqual((str(e.exception), e.exception.rate), ("busy (http 422)", False))

    def test_429_backs_off_unless_the_wait_passes_the_deadline(self):
        url = "https://hn.algolia.com/api/v1/search?query=x"
        with mock.patch.object(m, "OPENER", Opener([(("hn.algolia.com",), [429, b"{}"])])):
            self.assertEqual(m.fetch(url), b"{}")
        self.sleep.assert_any_call(2)
        opener = Opener([(("hn.algolia.com",), [(429, {"Retry-After": "30"}), b"{}"])])
        with mock.patch.object(m, "OPENER", opener), self.assertRaises(m.Fail) as e:
            m.fetch(url, end=time.monotonic() + 5)
        self.assertEqual((str(e.exception), e.exception.rate, len(opener.urls)), ("http 429", True, 1))
        with mock.patch.object(m, "OPENER", Opener([(("hn.algolia.com",), [(429, {"X-RateLimit-Reset": "13"}), b"{}"])])):
            self.assertEqual(m.fetch(url), b"{}")
        self.sleep.assert_any_call(13)


    def test_5xx_and_timeouts_are_retried_walls_and_github_limits_are_not(self):
        url = f"{m.ARCTIC}/posts/search?subreddit=rust&query=x"  # arctic-shift answers 500 for an uncached query
        flaky = [500, urllib.error.URLError(TimeoutError("timed out")), (503, {"Retry-After": "6"}), b"{}"]
        with mock.patch.object(m, "OPENER", Opener([(("arctic-shift",), flaky)])):
            self.assertEqual(m.fetch(url), b"{}")
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list if c.args[0] >= 2], [2, 4, 6])
        for reply, why, rate in (((503, {}, b"<title>Just a moment...</title>"), "http 503: bot check", False),
                                 ((403, {"X-RateLimit-Remaining": "0"}), "http 403", True)):
            opener = Opener([(("arctic-shift",), [reply, b"{}"])])
            with self.subTest(why=why), mock.patch.object(m, "OPENER", opener), self.assertRaises(m.Fail) as e:
                m.fetch(url)
            self.assertEqual((str(e.exception), e.exception.rate, len(opener.urls)), (why, rate, 1))


    def test_a_lane_error_keeps_its_message(self):
        def broken(st, ctx):
            raise KeyError("points")
            yield
        with mock.patch.dict(m.SEARCH, {"hn": (broken, None)}):
            code, lines, _, _ = self.run_pulse({"subqueries": [sub(lanes=("hn",))]}, [])
        lane = next(f for f in (line.split("\t") for line in lines) if f[0] == "LANE")
        self.assertIn("error: KeyError: 'points'", "\t".join(lane))
    # hf lane (Hugging Face): models created in the window, and daily papers

    def test_hf_lane_reads_models_and_daily_papers(self):
        models = [model("acme/widget-9b", "2026-10-29", likes=40, downloads=900, trending=12, tags=("multilingual", "region:us")),
                  model("acme/widget-1b", "2026-09-20")]  # created before the window
        papers = [daily("2610.00001", "Widget engines for multilingual speech", upvotes=42, comments=3, summary="We study widget engines.")]
        code, lines, result, opener = self.run_pulse(
            {"subqueries": [sub(query="widget", ranking="widget engine model", lanes=("hf",))]},
            [(("huggingface.co/api/models?",), js(models)), (("huggingface.co/api/daily_papers?date=2026-10-30",), js(papers)),
             (("huggingface.co/api/daily_papers?",), js([]))], "--days", "3")
        self.assertEqual(code, 0)
        self.assertEqual(opener.urls, [f"{m.HF}/api/models?search=widget&sort=createdAt&direction=-1&limit=50&full=true",
                                       f"{m.HF}/api/daily_papers?date=2026-10-30", f"{m.HF}/api/daily_papers?date=2026-10-29",
                                       f"{m.HF}/api/daily_papers?date=2026-10-28"])
        self.assertTrue(all("Authorization" not in h for h in opener.headers))  # keyless
        by = {i["id"]: i for i in result["items"]}
        self.assertEqual(sorted(by), ["hf:acme/widget-9b", "hf:paper/2610.00001"])
        mod, paper = by["hf:acme/widget-9b"], by["hf:paper/2610.00001"]
        self.assertEqual((mod["url"], mod["date"], mod["engagement"]),
                         ("https://huggingface.co/acme/widget-9b", "2026-10-29", {"hf": {"likes": 40, "downloads": 900, "trending": 12}}))
        self.assertIn("multilingual", mod["snippet"])
        self.assertNotIn("region:us", mod["snippet"])
        self.assertEqual((paper["url"], paper["links"]["hf"], paper["date"], paper["engagement"], paper["title"]),
                         ("https://arxiv.org/abs/2610.00001", "https://huggingface.co/papers/2610.00001", "2026-10-30",
                          {"hf": {"upvotes": 42, "comments": 3}}, "Widget engines for multilingual speech"))
        self.assertEqual(self.lanes(lines), {"hf": "ok"})
        self.assertIn("40 likes, 900 downloads, 12 trending", "\n".join(lines))

    def test_hf_runs_only_when_a_subquery_names_it(self):
        code, lines, result, opener = self.run_pulse({"subqueries": [{"search_query": "widget engine"}]}, [])
        self.assertFalse(any("huggingface.co" in u for u in opener.urls))
        self.assertNotIn("hf", self.lanes(lines))

    def test_hf_daily_paper_and_arxiv_item_are_one_story(self):
        papers = feed(("2610.00001", "Widget engine scheduling", "2026-10-29", "Widget engine study."))
        code, lines, result, _ = self.run_pulse(
            {"subqueries": [sub(lanes=("arxiv", "hf"))]},
            [(("export.arxiv.org",), papers), (("huggingface.co/api/models?",), js([])),
             (("huggingface.co/api/daily_papers?date=2026-10-30",), js([daily("2610.00001", "Widget engine scheduling", upvotes=30)])),
             (("huggingface.co/api/daily_papers?",), js([]))], "--days", "2")
        (item,) = result["items"]
        self.assertEqual((item["lanes"], item["engagement"]["hf"]), (["arxiv", "hf"], {"upvotes": 30, "comments": 0}))
        self.assertEqual(result["clusters"][0]["lanes"], ["arxiv", "hf"])

    def test_hf_changed_shape_is_a_lane_failure_with_a_reason(self):
        plan = {"subqueries": [sub(query="widget", lanes=("hf",))]}
        for models, papers, why in (({"error": "moved"}, {"error": "moved"}, "unexpected response from Hugging Face models: an object, not a list"),
                                    ([{"name": "acme/widget"}], [{"title": "no paper field"}],
                                     "Hugging Face models: none of 1 entries has an id and a creation date")):
            with self.subTest(why=why):
                code, lines, result, _ = self.run_pulse(plan, [(("huggingface.co/api/models?",), js(models)),
                                                               (("huggingface.co/api/daily_papers?",), js(papers))],
                                                        "--days", "1", top=self.tmp / why[:12] / "topic")
                lane = next(f for f in (line.split("\t") for line in lines) if f[0] == "LANE")
                self.assertEqual(code, 1)
                self.assertTrue(lane[2].startswith("failed: "), lane)
                self.assertIn(why, "\t".join(lane))
        code, lines, _, _ = self.run_pulse(plan, [(("huggingface.co/api/models?",), js([model("acme/widget-9b", "2026-10-30")])),
                                                  (("huggingface.co/api/daily_papers?",), js({"error": "moved"}))], "--days", "1")
        lane = next(f for f in (line.split("\t") for line in lines) if f[0] == "LANE")
        self.assertEqual(lane[2], "partial")
        self.assertIn("unexpected response from Hugging Face daily papers: an object, not a list", lane[3])

    def test_hf_models_page_back_to_the_window(self):
        page2 = f"{m.HF}/api/models?search=widget&sort=createdAt&direction=-1&limit=50&full=true&cursor=abc"
        first = Resp(js([model("acme/widget-new", "2026-10-31")]), {"Link": f'<{page2}>; rel="next"'})
        plan = {"subqueries": [sub(query="widget", ranking="widget model", lanes=("hf",))]}
        code, lines, result, opener = self.run_pulse(plan, [(("cursor=abc",), js([model("acme/widget-old", "2026-10-30")])),
                                                            (("huggingface.co/api/models?",), first),
                                                            (("huggingface.co/api/daily_papers?",), js([]))], "--days", "1")
        self.assertEqual([u for u in opener.urls if "/api/models" in u][1], page2)
        self.assertEqual([i["id"] for i in result["items"]], ["hf:acme/widget-old"])
        # a next link off the Hub is never followed, and a window never reached is said, not left silent
        away = Resp(js([model("acme/widget-new", "2026-10-31")]), {"Link": '<https://example.com/api/models?x>; rel="next"'})
        code, lines, result, opener = self.run_pulse(plan, [(("huggingface.co/api/models?",), away),
                                                            (("huggingface.co/api/daily_papers?",), js([]))], "--days", "1",
                                                     top=self.tmp / "away" / "topic")
        self.assertFalse(any("example.com" in u for u in opener.urls))
        self.assertIn("the newest 1 models all postdate the window", "\n".join(lines))

    def test_hf_daily_papers_read_at_most_the_newest_days(self):
        code, lines, result, opener = self.run_pulse({"subqueries": [sub(query="widget", lanes=("hf",))]},
                                                     [(("huggingface.co/api/",), js([]))], "--days", "60", "--deadline", "300")
        days = [u.rsplit("=", 1)[1] for u in opener.urls if "daily_papers" in u]
        self.assertEqual((len(days), days[0], days[-1]), (m.HF_DAYS, "2026-10-30", "2026-09-30"))
        self.assertIn(f"daily papers read for the newest {m.HF_DAYS} of 60 days", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
