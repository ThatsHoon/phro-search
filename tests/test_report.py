"""scripts/report.py: quotes checked against their source lines, and the evidence page."""
import contextlib
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

from tests._load import ROOT, load

m = load("scripts/report.py")
ELL = "\U00002026"
LEGACY_STATUS = ["付いた", "一部だけ", "付かなかった", "일부만"]  # sourced, partial, none, partial
KO_SOURCE = "사고\U000000a0차량의 위치는\n자동으로 전송된다.\n"
KO_QUOTE = "사고 차량의 위치는 자동으로 전송된다."
KO_PARAPHRASE = "사고 차량의 위치가 자동으로 전송된다."
JA_SOURCE = "はじめに\n事故車両の位置は\n自動的に送信される。\n"
JA_QUOTE = "事故車両の位置は自動的に送信される。"
KO_TRANSLATION = "알파의 번역"


def quote(file, line, text, **extra):
    return {"file": file, "line": line, "text": text, "support": "full", **extra}


def claim(*quotes, status="sourced"):
    return {"claim": "A claim", "status": status, "quotes": list(quotes)}


class ReportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)

    def topic(self, sources, claims, **extra):
        """A new topic folder with these source files, written byte for byte, and an extracts.json."""
        topic = pathlib.Path(tempfile.mkdtemp(dir=self.root))
        for name, text in sources.items():
            path = topic / "sources" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        data = {"title": "Evidence", "question": "Does it hold?", "stopped": "saturated", "claims": claims, **extra}
        (topic / "extracts.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return topic

    def report(self, topic, *flags):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = m.main([str(topic), *flags])
        return code, out.getvalue()

    def page(self, topic):
        code, out = self.report(topic)
        self.assertEqual(code, 0, out)
        return (topic / "report.html").read_text(encoding="utf-8")

    def test_verbatim_quote_passes_and_writes_page(self):
        topic = self.topic({"a.md": "Intro\nThe model reaches 95 percent accuracy on the test set.\nEnd\n"},
                           [claim(quote("a.md", 2, "reaches 95 percent accuracy"))])
        self.assertEqual(self.report(topic), (0, f"OK\t1 quotes in 1 claims match\t{topic / 'report.html'}\n"))
        html = (topic / "report.html").read_text(encoding="utf-8")
        self.assertIn("<blockquote>reaches 95 percent accuracy</blockquote>", html)

    def test_paraphrase_blocks_page_and_names_the_quote(self):
        sources = {"a.md": "Intro\nThe model reaches 95 percent accuracy.\n", "b.md": "x\ny\nz\nThe method needs no labels.\n"}
        topic = self.topic(sources, [claim(quote("a.md", 2, "reaches 95 percent accuracy"),
                                           quote("b.md", 4, "The method requires no labels."))],
                           disagreements=[{"topic": "Labels", "quotes": [quote("b.md", 1, "nothing like it", who="Lab A")]}])
        expected = ["MISMATCH\tclaim 1 quote 2\tb.md:4\tnot found near the line\tThe method requires no labels.",
                    "MISMATCH\tdisagreement 1 quote 1\tb.md:1\tnot found near the line\tnothing like it",
                    "FAIL\t2 of 3 quotes do not match; report.html not written"]
        code, out = self.report(topic)
        self.assertEqual((code, out.splitlines()), (1, expected))
        self.assertFalse((topic / "report.html").exists())
        (topic / "report.html").write_text("previous page", encoding="utf-8")
        self.assertEqual(self.report(topic)[0], 1)
        self.assertEqual((topic / "report.html").read_text(encoding="utf-8"), "previous page")

    def test_ellipsis_pieces_match_in_order_only(self):
        sources = {"a.md": "left column one\nright column two\nleft column three\n"}
        in_order = self.topic(sources, [claim(quote("a.md", 2, f"left column one {ELL} column three"))])
        self.assertEqual(self.report(in_order, "--check")[0], 0)
        swapped = self.topic(sources, [claim(quote("a.md", 2, f"column three {ELL} left column one"))])
        code, out = self.report(swapped, "--check")
        self.assertEqual((code, out.splitlines()[0].split("\t")[3]), (1, "piece 2 not found in order"))
        only_ellipsis = self.topic(sources, [claim(quote("a.md", 2, f" {ELL} "))])
        code, out = self.report(only_ellipsis, "--check")
        self.assertEqual((code, out.splitlines()[0].split("\t")[3]), (1, "not found near the line"))

    def test_legacy_status_values_and_ja_key(self):
        claims = [claim(quote("a.md", 1, "alpha"), status=s) for s in LEGACY_STATUS]
        claims[0]["quotes"][0].update(ja=KO_TRANSLATION, context_note="old extra key")
        html = self.page(self.topic({"a.md": "alpha\n"}, claims))
        self.assertEqual(re.findall(r'<span class="status \w+">(\w+)</span>', html), ["sourced", "partial", "none", "partial"])
        self.assertIn(f'<p class="tr"><span class="tag">translation</span> {KO_TRANSLATION}</p>', html)
        self.assertNotIn("old extra key", html)
        unknown = self.topic({"a.md": "alpha\n"}, [claim(quote("a.md", 1, "alpha"), status="done")])
        self.assertEqual(self.report(unknown), (1, 'FAIL\tclaim 1: unknown status "done"\n'))

    def test_context_shows_neighbor_lines_and_marks_the_quote(self):
        rows = "".join(f"row{n:02d}\n" for n in range(1, 31))
        html = self.page(self.topic({"a.md": rows}, [claim(quote("a.md", 10, "row10 row11", end=11))]))
        self.assertEqual(re.findall(r'<span class="n">(\d+)</span>', html), [str(n) for n in range(5, 17)])
        self.assertEqual(re.findall(r'<mark><span class="n">(\d+)</span>row(\d+)</mark>', html), [("10", "10"), ("11", "11")])
        self.assertIn('<span class="n">5</span>row05', html)
        self.assertIn('<span class="n">16</span>row16', html)
        self.assertNotIn("row04", html)
        self.assertNotIn("row17", html)
        self.assertIn('<a href="sources/a.md">sources/a.md:10-11</a>', html)

    def test_form_feed_and_other_breaks_keep_grep_numbering(self):
        # grep -n sees 10 lines; splitlines() would split at each separator and put the target at 19.
        seps = ["\f", "\x0b", "\x1c", "\x1d", "\x1e", "\x85", "\U00002028", "\U00002029", "\r"]
        text = "".join(f"page {i}{sep}more\n" for i, sep in enumerate(seps, 1)) + "target sentence here\r\n"
        topic = self.topic({"a.txt": text}, [claim(quote("a.txt", 10, "target sentence here")),
                                             claim(quote("a.txt", 11, "target sentence here"))])
        code, out = self.report(topic, "--check")
        self.assertEqual((code, out.splitlines()), (1, [
            "MISMATCH\tclaim 2 quote 1\ta.txt:11\tline out of range (file has 10 lines)\ttarget sentence here",
            "FAIL\t1 of 2 quotes do not match; report.html not written"]))

    def test_cjk_quote_across_a_line_break(self):
        topic = self.topic({"ko.md": KO_SOURCE, "ja.md": JA_SOURCE},
                           [claim(quote("ko.md", 1, KO_QUOTE, end=2), quote("ja.md", 2, JA_QUOTE))])
        self.assertEqual(self.report(topic, "--check"), (0, "OK\t2 quotes in 1 claims match\tcheck only\n"))
        bad = self.topic({"ko.md": KO_SOURCE}, [claim(quote("ko.md", 1, KO_PARAPHRASE))])
        run = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/report.py"), str(bad), "--check"],
                             capture_output=True, encoding="utf-8", timeout=60)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn(f"\tnot found near the line\t{KO_PARAPHRASE}\n", run.stdout)

    def test_caption_timestamps_are_ignored(self):
        text = "[12:34] so the trick is\n[12:36] to warm the model up first\n[1:02:03] and then lower the rate\n"
        topic = self.topic({"talk.txt": text}, [claim(quote("talk.txt", 1, "so the trick is to warm the model", end=2),
                                                      quote("talk.txt", 2, "up first and then lower the rate", end=3))])
        self.assertEqual(self.report(topic, "--check")[0], 0)

    def test_bullet_list_across_lines(self):
        text = "Steps:\n- check the airway\n* call for help\n\U00002022 keep them warm\n1. stay\n2) wait\n"
        topic = self.topic({"l.md": text}, [
            claim(quote("l.md", 2, "check the airway call for help keep them warm stay wait", end=6),
                  quote("l.md", 2, "- check the airway\n* call for help", end=3))])
        self.assertEqual(self.report(topic, "--check")[0], 0)

    def test_paths_outside_sources_are_rejected(self):
        files = ["../extracts.json", "sub/../a.md", "/etc/hosts", "C:/a.md", "gone.md"]
        topic = self.topic({"a.md": "alpha\n"}, [claim(*(quote(f, 1, "alpha") for f in files))])
        code, out = self.report(topic, "--check")
        reasons = [line.split("\t")[3] for line in out.splitlines()[:-1]]
        self.assertEqual((code, reasons), (1, ["bad file path"] * 4 + ["no file"]))

    def test_check_writes_no_file(self):
        topic = self.topic({"a.md": "alpha\n"}, [claim(quote("a.md", 1, "alpha"))])
        self.assertEqual(self.report(topic, "--check"), (0, "OK\t1 quotes in 1 claims match\tcheck only\n"))
        self.assertFalse((topic / "report.html").exists())

    def test_page_escapes_html(self):
        topic = self.topic({"x.md": "plain line\n<script>alert(1)</script>\n"},
                           [claim(quote("x.md", 2, "<script>alert(1)</script>", mark="<b>fig</b>"))],
                           disagreements=[{"topic": "<i>who</i>", "quotes": [quote("x.md", 1, "plain line", who="<u>Lab</u>")]}],
                           unreached=["<em>paywalled</em>"])
        html = self.page(topic)
        self.assertIn("<blockquote>&lt;script&gt;alert(1)&lt;/script&gt;</blockquote>", html)
        self.assertEqual([raw for raw in ("<script>", "<b>", "<i>", "<u>", "<em>") if raw in html], [])
        self.assertIn("<h2>Disagreements</h2>", html)
        self.assertIn("<h2>Not reached</h2>", html)

    def test_report_view_is_checked_and_written_apart(self):
        topic = self.topic({"a.md": "Intro\nThe model reaches 95 percent accuracy.\n"}, [claim(quote("a.md", 2, "reaches 95"))])
        view = {"title": "Report", "question": "q", "stopped": "answered", "claims": [claim(quote("a.md", 2, "95 percent accuracy"))]}
        (topic / "extracts-2026-11-01.json").write_text(json.dumps(view), encoding="utf-8")
        page = topic / "evidence-2026-11-01.html"
        self.assertEqual(self.report(topic, "2026-11-01"), (0, f"OK\t1 quotes in 1 claims match\t{page}\n"))
        self.assertTrue(page.exists())
        self.assertFalse((topic / "report.html").exists())
        self.assertEqual(self.report(topic, "2026-11-01", "--check"), (0, "OK\t1 quotes in 1 claims match\tcheck only\n"))
        view["claims"][0]["quotes"][0]["text"] = "99 percent accuracy"
        (topic / "extracts-2026-11-01.json").write_text(json.dumps(view), encoding="utf-8")
        self.assertEqual(self.report(topic, "2026-11-01")[1].splitlines()[-1],
                         "FAIL\t1 of 1 quotes do not match; evidence-2026-11-01.html not written")
        self.assertEqual(self.report(topic, "2026-11-02"), (1, f"FAIL\tcannot read {topic / 'extracts-2026-11-02.json'}\n"))
        self.assertEqual(self.report(topic, "../x"), (1, "FAIL\tbad stem: ../x\n"))

    def test_page_shows_source_dates_from_the_index(self):
        topic = self.topic({"a.md": "alpha\n"}, [claim(quote("a.md", 1, "alpha"))])
        head = "name\turl\tfinal\tfetched\tpublished\tmodified\textraction\tversion\tmarks\tfiles"
        row = "a\thttps://example.org/a\t-\t2026-11-01T09:00:00Z\t2025-05-01\t-\thtml\taccepted\t-\ta.md"
        (topic / "sources" / "index.tsv").write_text(f"{head}\n{row}\nbroken row\n", encoding="utf-8")
        html = self.page(topic)
        self.assertIn('<span class="when">published 2025-05-01; fetched 2026-11-01; version accepted</span>', html)

    def test_retracted_sources_back_no_claim(self):
        r = quote("a.md", 1, "alpha", mark="paper, retracted")
        topic = self.topic({"a.md": "alpha\n", "b.md": "beta\n"},
                           [claim(r), claim(r, status="partial"), claim(r, quote("b.md", 1, "beta")), claim(r, status="none")])
        self.assertEqual(self.report(topic, "--check")[1].splitlines(),
                         ["CLAIM\tclaim 1\tevery quote comes from a retracted source; a retracted work backs no claim",
                          "CLAIM\tclaim 2\tevery quote comes from a retracted source; a retracted work backs no claim",
                          "FAIL\t2 claim problems; report.html not written"])
        # fetch.py's retracted mark in sources/index.tsv counts too
        topic = self.topic({"a.md": "alpha\n"}, [claim(quote("a.md", 1, "alpha"))])
        head = "name\turl\tfinal\tfetched\tpublished\tmodified\textraction\tversion\tmarks\tfiles"
        (topic / "sources" / "index.tsv").write_text(f"{head}\na\tdoi:x\t-\t2026-11-01T00:00:00Z\t-\t-\thtml\t-\tretracted\ta.md\n",
                                                     encoding="utf-8")
        self.assertEqual(self.report(topic, "--check")[1].splitlines()[0],
                         "CLAIM\tclaim 1\tevery quote comes from a retracted source; a retracted work backs no claim")

    def test_pdf_dates_read_as_created(self):
        topic = self.topic({"a.txt": "alpha\n"}, [claim(quote("a.txt", 1, "alpha"))])
        head = "name\turl\tfinal\tfetched\tpublished\tmodified\textraction\tversion\tmarks\tfiles"
        row = "a\tlocal:a.pdf\t-\t2026-11-01T09:00:00Z\t2021-03-04\t2021-04-05\tpdftotext\t-\t-\ta.pdf,a.txt"
        (topic / "sources" / "index.tsv").write_text(f"{head}\n{row}\n", encoding="utf-8")
        self.assertIn('<span class="when">created 2021-03-04; modified 2021-04-05; fetched 2026-11-01</span>', self.page(topic))

    def test_support_pass(self):
        src = {"a.md": "Intro\nThe model reaches 95 percent accuracy.\nOnly on English test data.\n"}
        limit = {"file": "a.md", "line": 3, "text": "Only on English test data."}
        topic = self.topic(src, [claim(quote("a.md", 2, "reaches 95 percent", support="partial", qualifier=limit)),
                                 claim(quote("a.md", 2, "reaches 95 percent", support="partial"), status="partial"),
                                 claim({"file": "a.md", "line": 2, "text": "reaches 95 percent"})])
        self.assertEqual(self.report(topic, "--check")[1].splitlines(),
                         ["CLAIM\tclaim 1\tsourced, but no quote gives full support; run the support pass",
                          "CLAIM\tclaim 3\tsourced, but no quote gives full support; run the support pass",
                          "FAIL\t2 claim problems; report.html not written"])
        good = self.topic(src, [claim(quote("a.md", 2, "reaches 95 percent", qualifier=limit))])
        html = self.page(good)
        self.assertIn('<span class="tag">support: full</span>', html)
        self.assertIn('<p class="limit"><span class="tag">limit</span> Only on English test data. (sources/a.md:3)</p>', html)
        moved = self.topic(src, [claim(quote("a.md", 2, "reaches 95 percent", qualifier=dict(limit, text="Only on French data.")))])
        self.assertEqual(self.report(moved, "--check")[1].splitlines()[0],
                         "MISMATCH\tclaim 1 quote 1 qualifier\ta.md:3\tnot found near the line\tOnly on French data.")
        odd = self.topic(src, [claim(quote("a.md", 2, "reaches 95 percent", support="mostly"))])
        self.assertEqual(self.report(odd), (1, "FAIL\tclaim 1 quote 1: support must be full, partial, none or contradicts\n"))

    def test_bad_extracts_fail(self):
        empty = pathlib.Path(tempfile.mkdtemp(dir=self.root))
        self.assertEqual(self.report(empty), (1, f"FAIL\tcannot read {empty / 'extracts.json'}\n"))
        (empty / "extracts.json").write_text("{not json", encoding="utf-8")
        self.assertTrue(self.report(empty)[1].startswith("FAIL\textracts.json is not valid JSON: "))
        topic = self.topic({"a.md": "alpha\n"}, [claim(quote("a.md", "1", "alpha"))])
        self.assertEqual(self.report(topic), (1, "FAIL\tclaim 1 quote 1: line must be int\n"))


def vote(refuted, evidence="checked the release notes", **extra):
    return {"refuted": refuted, "confidence": "high", "evidence": evidence, **extra}


def claimed(id, importance="central", votes=(), **extra):
    return {"id": id, "claim": f"Claim {id}", "quote": "reaches 95 percent", "url": "https://example.org/a",
            "label": "paper", "importance": importance, "votes": list(votes), **extra}


class ClaimsTest(unittest.TestCase):
    """claims.json (report mode): verdicts follow the votes, and the page shows them next to each claim."""
    SOURCE = {"a.md": "Intro\nThe model reaches 95 percent accuracy.\n"}
    setUp, report, page = ReportTest.setUp, ReportTest.report, ReportTest.page

    def topic(self, claims_json, ids=("c1",)):
        """A topic whose extracts.json claims carry these ids, all quoting the same line, and this claims.json."""
        topic = ReportTest.topic(self, self.SOURCE, [dict(claim(quote("a.md", 2, "reaches 95 percent")), id=i) for i in ids])
        (topic / "claims.json").write_text(json.dumps(claims_json), encoding="utf-8")
        return topic

    def test_votes_shown_next_to_the_claim(self):
        held, against = vote(False), vote(True, "a later benchmark disagrees", counter_source="https://example.org/b")
        topic = self.topic([claimed("c1", votes=[held, held, against], verdict="survived"), claimed("c2", "supporting")])
        code, out = self.report(topic)
        self.assertEqual((code, out), (0, f"OK\t1 quotes in 1 claims match; votes: 1 survived, 0 refuted, 0 unverified\t{topic / 'report.html'}\n"))
        html = (topic / "report.html").read_text(encoding="utf-8")
        votes = html[html.index('<div class="votes">'):html.index("<figure>")]
        self.assertIn('<span class="status survived">survived</span> central, paper, <a href="https://example.org/a">original</a>', votes)
        self.assertEqual(votes.count("<li>held (high): checked the release notes</li>"), 2)
        self.assertIn('<li>refuted (high): a later benchmark disagrees (<a href="https://example.org/b">counter source</a>)</li>', votes)

    def test_only_web_urls_become_links(self):
        bad = vote(True, counter_source="javascript:alert(1)")
        html = self.page(self.topic([claimed("c1", votes=[bad, bad], verdict="refuted", url="file:///etc/passwd")]))
        self.assertNotIn('href="javascript', html)
        self.assertNotIn('href="file', html)
        self.assertIn("(javascript:alert(1))", html)

    def test_verdict_must_follow_the_votes(self):
        cases = [([vote(True), vote(True), vote(False)], "survived", "refuted"),
                 ([vote(False)], "survived", "unverified"),
                 ([], "refuted", "unverified"),
                 ([vote(False), vote(True)], None, "survived")]
        for votes, stored, expected in cases:
            topic = self.topic([claimed("c1", votes=votes, **({"verdict": stored} if stored else {}))])
            code, out = self.report(topic)
            self.assertEqual((code, out.splitlines()),
                             (1, [f"CLAIM\tclaims.json c1\tverdict {stored or 'missing'}, but the votes give {expected}",
                                  "FAIL\t1 claim problems; report.html not written"]), (votes, stored))
            self.assertFalse((topic / "report.html").exists())
        self.assertEqual(self.report(self.topic([claimed("c1", votes=[vote(True)] * 2, verdict="refuted")]))[0], 0)
        self.assertEqual(self.report(self.topic([claimed("c1", "supporting")]))[0], 0)  # not checked: no votes, no verdict
        bare = {k: v for k, v in claimed("c1", "supporting").items() if k != "votes"}
        self.assertEqual(self.report(self.topic([bare]))[0], 0)  # the votes key may be left out

    def test_central_claims_are_located_capped_and_ids_known(self):
        topic = self.topic([claimed("c1", verdict="unverified"), claimed("c2", verdict="unverified"),
                            claimed("c3", "tangential", votes=[vote(False)] * 4, verdict="survived"),
                            claimed("c4", verdict="unverified")], ids=("c1", "c9"))
        data = json.loads((topic / "extracts.json").read_text(encoding="utf-8"))
        data["claims"].append({"claim": "Claim c2", "status": "none", "quotes": [], "id": "c2"})  # cited, but no quote
        (topic / "extracts.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.report(topic, "--check")[1].splitlines(),
                         ['CLAIM\tclaim 2\tid "c9" is not in claims.json',
                          "CLAIM\tclaims.json c2\tcentral, but this view gives it no quote",
                          "CLAIM\tclaims.json c3\t4 votes (limit 3)",
                          "FAIL\t3 claim problems; report.html not written"])  # c4 is not in this view
        ids = [f"c{i}" for i in range(1, 12)]
        out = self.report(self.topic([claimed(i, verdict="unverified") for i in ids], ids=ids))[1]
        self.assertIn("CLAIM\tclaims.json\t11 central claims in this view (limit 10)", out)
        self.assertEqual(self.report(self.topic([claimed(i, verdict="unverified") for i in ids], ids=ids[:2]))[0], 0)

    def test_dig_view_beside_a_report_claims_file(self):
        # A dig's extracts.json cites no claim ids, so a report's claims.json beside it no longer blocks its page.
        topic = self.topic([claimed("c1", votes=[vote(False)] * 2, verdict="survived")], ids=())
        self.assertEqual(self.report(topic), (0, f"OK\t0 quotes in 0 claims match\t{topic / 'report.html'}\n"))
        both = self.topic([claimed("c1", votes=[vote(False)] * 2, verdict="survived"),
                           claimed("c2", votes=[vote(True)] * 2, verdict="refuted")], ids=("c1",))
        self.assertIn("votes: 1 survived, 0 refuted, 0 unverified", self.report(both)[1])  # only the claims this view cites

    def test_vote_check_dates(self):
        dated = vote(False, checked="2026-11-01")
        html = self.page(self.topic([claimed("c1", votes=[dated, dated], verdict="survived")]))
        self.assertIn("<li>held (high, checked 2026-11-01): checked the release notes</li>", html)
        bad = self.topic([claimed("c1", votes=[vote(False, checked="11/01/2026")] * 2, verdict="survived")])
        self.assertEqual(self.report(bad), (1, "FAIL\tclaims.json c1 vote 1: checked must be a date written YYYY-MM-DD\n"))

    def test_central_claim_on_retracted_quotes_only(self):
        topic = self.topic([claimed("c1", verdict="unverified")])
        data = json.loads((topic / "extracts.json").read_text(encoding="utf-8"))
        data["claims"][0].update(status="partial")
        data["claims"][0]["quotes"][0]["mark"] = "retracted"
        (topic / "extracts.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.report(topic, "--check")[1].splitlines()[0],
                         "CLAIM\tclaim 1\tevery quote comes from a retracted source; a retracted work backs no claim")
        self.assertIn("CLAIM\tclaims.json c1\tcentral, but every quote in this view comes from a retracted source",
                      self.report(topic, "--check")[1])

    def test_bad_claims_json_fails(self):
        cases = (({"c1": {}}, "claims.json must be a list"),
                 ([claimed("c1"), claimed("c1")], "claims.json c1: the id appears twice"),
                 ([claimed("c1", "key")], "claims.json c1: importance must be one of central, supporting, tangential;"
                                          " verdict one of survived, refuted, unverified"),
                 ([claimed("c1", votes=[{"refuted": "yes", "confidence": "high", "evidence": "x"}])],
                  "claims.json c1 vote 1: refuted must be bool"),
                 ([dict(claimed("c1"), url=None)], "claims.json item 1: url must be str"))
        for data, reason in cases:
            self.assertEqual(self.report(self.topic(data)), (1, f"FAIL\t{reason}\n"), reason)
        topic = self.topic([])
        (topic / "claims.json").write_text("[oops", encoding="utf-8")
        self.assertTrue(self.report(topic)[1].startswith("FAIL\tclaims.json is not valid JSON: "))

    def test_without_claims_json_ids_are_ignored(self):
        topic = ReportTest.topic(self, self.SOURCE, [dict(claim(quote("a.md", 2, "reaches 95 percent")), id="c1")])
        self.assertEqual(self.report(topic, "--check"), (0, "OK\t1 quotes in 1 claims match\tcheck only\n"))


if __name__ == "__main__":
    unittest.main()
