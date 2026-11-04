"""scripts/locate.py: findings in the notes located in their sources, and the picks written as claims and a view."""
import contextlib, io, json, shutil, tempfile, unittest
from pathlib import Path

from tests._load import load

loc = load("scripts/locate.py")
rep = load("scripts/report.py")
ELL = "\U00002026"
HEAD = "\t".join(rep.INDEX_HEAD)
NOTE = ('## Q1 x\nTakeaway: t\n'
        '- F1. The model reaches 95 percent. Quote: "The model reaches 95 percent accuracy." https://arxiv.org/html/2401.00001v2 (paper)\n'
        '- F2. It spans two lines. Quote: "first half second half" (same page) https://example.org/a/ (official)\n'
        '- F3. Two pieces. Quote (as returned): "Intro ... 95 percent" https://arxiv.org/abs/2401.00001 (paper)\n'
        '- F4. Paraphrased. Quote: "not in the page" https://arxiv.org/abs/2401.00001 (paper)\n'
        '- F5. Unfetched. Quote: "anything" https://example.org/gone (summary)\n'
        '- F6. No quote at all https://example.org/a\n')


def row(name, url, files):
    return "\t".join((name, url, "-", "t", "-", "-", "html", "-", "-", files))


class LocateTest(unittest.TestCase):
    def setUp(self):
        self.topic = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.topic)
        (self.topic / "notes").mkdir()
        (self.topic / "notes" / "flood.md").write_text(NOTE, encoding="utf-8")
        src = self.topic / "sources"
        src.mkdir()
        (src / "p.md").write_text("Intro\n\nThe **model** reaches 95 percent accuracy.\n", encoding="utf-8")
        (src / "a.md").write_text("x\nfirst half\n\nsecond half\n", encoding="utf-8")
        (src / "index.tsv").write_text("\n".join((HEAD, row("p", "https://arxiv.org/abs/2401.00001", "p.pdf,p.md"),
                                                  row("a", "https://example.org/a", "a.md"))) + "\n", encoding="utf-8")

    def run_it(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = loc.main([str(self.topic), *args])
        return code, out.getvalue().splitlines()

    def picks(self, *claims):
        path = self.topic / "picks.json"
        path.write_text(json.dumps({"title": "T", "question": "Q", "stopped": "S", "claims": list(claims)}), encoding="utf-8")
        return str(path)

    def test_lists_every_finding(self):
        code, out = self.run_it()
        self.assertEqual(code, 0)
        self.assertEqual(out, ["FOUND\tflood F1\tp.md:3\tpaper\tThe model reaches 95 percent.",
                               "FOUND\tflood F2\ta.md:2-4\tofficial\tIt spans two lines.",
                               "FOUND\tflood F3\tp.md:1-3\tpaper\tTwo pieces.",
                               "MISS\tflood F4\tnot found in p.md\thttps://arxiv.org/abs/2401.00001",  # too little in common for a hint
                               "MISS\tflood F5\tno source for the URL\thttps://example.org/gone",
                               "MISS\tflood F6\tno quote\t-"])

    def test_picks_pass_the_report_check(self):
        code, out = self.run_it("2026-11-02", "--picks", self.picks(
            {"id": "c1", "findings": ["flood F1", "flood F3"], "importance": "central", "claim": "95 %"},
            {"id": "c2", "findings": ["flood F2"], "importance": "supporting", "claim": "둘"}))
        self.assertEqual(code, 0, out)
        self.assertIn("2 claims, 3 quotes, 2 new in claims.json", out[0])
        view = json.loads((self.topic / "extracts-2026-11-02.json").read_text(encoding="utf-8"))
        self.assertEqual(view["claims"][0]["quotes"][1], {"file": "p.md", "line": 1, "text": f"Intro{ELL}95 percent", "end": 3})
        claims = json.loads((self.topic / "claims.json").read_text(encoding="utf-8"))
        self.assertEqual(claims[0]["quote"], "The **model** reaches 95 percent accuracy")  # the source's text, not the note's
        self.assertEqual(claims[0]["claim"], "The model reaches 95 percent.")  # English from the note, the view has the user's words
        self.assertEqual((claims[1]["label"], claims[1]["url"]), ("official", "https://example.org/a/"))
        with contextlib.redirect_stdout(io.StringIO()) as checked:
            self.assertEqual(rep.main([str(self.topic), "2026-11-02", "--check"]), 0)
        self.assertIn("3 quotes in 2 claims match", checked.getvalue())

    def test_an_id_already_in_claims_keeps_its_votes(self):
        vote = {"refuted": False, "confidence": "high", "evidence": "e"}
        kept = {"id": "c1", "claim": "old", "quote": "q", "url": "u", "label": "paper", "importance": "central",
                "votes": [vote], "verdict": "survived"}
        (self.topic / "claims.json").write_text(json.dumps([kept]), encoding="utf-8")
        self.assertEqual(self.run_it("s", "--picks", self.picks(
            {"id": "c1", "findings": ["flood F1"], "importance": "central", "claim": "x"}))[0], 0)
        self.assertEqual(json.loads((self.topic / "claims.json").read_text(encoding="utf-8")), [kept])

    def test_a_pick_sets_the_standing_and_keeps_the_votes(self):
        vote = {"refuted": False, "confidence": "high", "evidence": "e"}
        kept = {"id": "c1", "claim": "old", "quote": "q", "url": "u", "label": "paper", "importance": "central",
                "votes": [vote], "verdict": "survived"}
        (self.topic / "claims.json").write_text(json.dumps([kept]), encoding="utf-8")
        self.assertEqual(self.run_it("s", "--picks", self.picks(
            {"id": "c1", "findings": ["flood F1"], "importance": "central", "claim": "x", "standing": "reviewed", "venue": "A Conf"},
            {"id": "c2", "findings": ["flood F2"], "importance": "central", "claim": "y", "standing": "open-post"}))[0], 0)
        claims = json.loads((self.topic / "claims.json").read_text(encoding="utf-8"))
        self.assertEqual(claims[0], dict(kept, standing="reviewed", venue="A Conf"))
        self.assertEqual(claims[1]["standing"], "open-post")
        code, out = self.run_it("s", "--picks", self.picks(
            {"id": "c3", "findings": ["flood F1"], "importance": "central", "claim": "x", "standing": "famous"}))
        self.assertEqual(code, 1)
        self.assertIn("standing must be one of open-post, reviewed, unknown", out[0])

    def test_a_pick_that_did_not_locate_blocks_the_write(self):
        code, out = self.run_it("s", "--picks", self.picks(
            {"id": "c1", "findings": ["flood F4"], "importance": "supporting", "claim": "x"},
            {"id": "c2", "findings": ["flood F9"], "importance": "supporting", "claim": "x"}))
        self.assertEqual(code, 1)
        self.assertEqual(out, ["PICK\tc1\tflood F4\tnot found in p.md", "PICK\tc2\tflood F9\tno such finding",
                               "FAIL\t2 picks cannot be used; nothing written"])
        self.assertFalse((self.topic / "claims.json").exists())

    def test_a_miss_points_at_the_nearest_line_and_a_pick_can_quote_it(self):
        (self.topic / "notes" / "flood.md").write_text(
            NOTE + '- F7. Reworded. Quote: "The model reaches 95 percent on every test" https://arxiv.org/abs/2401.00001 (summary)\n',
            encoding="utf-8")
        self.assertIn("MISS\tflood F7\tnot found in p.md, nearest line 3\thttps://arxiv.org/abs/2401.00001", self.run_it()[1])
        code, out = self.run_it("s", "--picks", self.picks(
            {"id": "c1", "findings": ["flood F7"], "importance": "supporting", "claim": "x",
             "quotes": [{"file": "p.md", "line": 3, "text": "reaches 95 percent accuracy"}]}))
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads((self.topic / "claims.json").read_text(encoding="utf-8"))[0]["quote"], "reaches 95 percent accuracy")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rep.main([str(self.topic), "s", "--check"]), 0)

    def test_a_short_quote_is_not_placed(self):
        self.assertIsNone(loc.find(self.topic / "sources", "p.md", "95 percent"))
        self.assertEqual(loc.find(self.topic / "sources", "p.md", "the MODEL reaches 95")[:2], (3, 3))  # case and markup ignored

    def test_bad_inputs(self):
        self.assertEqual(self.run_it("s")[1], ["FAIL\ta stem and --picks go together"])
        self.assertEqual(self.run_it("../x", "--picks", self.picks())[1], ["FAIL\tbad stem"])
        bad = self.picks({"id": "c1", "findings": [], "importance": "central", "claim": "x"})
        code, out = self.run_it("s", "--picks", bad)
        self.assertEqual(code, 1)
        self.assertIn("needs findings", out[0])


if __name__ == "__main__":
    unittest.main()
