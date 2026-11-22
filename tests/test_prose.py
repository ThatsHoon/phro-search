"""scripts/prose.py: a report's cited statements listed with their evidence, and a reader's reply counted."""
import contextlib, io, json, tempfile, unittest
from pathlib import Path

from tests._load import load

m = load("scripts/prose.py")

REPORT = """# Title

As of 2026-11-22 the test has 100 items [c1]. It runs in three steps and nobody measured it.

## Section

| Part | Format |
|---|---|
| Reading | 30 items [c1, c2] |

The pipeline kept 454 of 789 passages [c2]. A proposal follows [c9].

```
[c1] code is not prose, 55 items
```

## Evidence

| id | claim |
|---|---|
| c1 | 100 items [c1] |
"""
VIEW = {"unreached": ["the price list: walled"], "claims": [
    {"id": "c1", "claim": "The test has 100 items.", "quotes": [{"file": "a.txt", "line": 3, "text": "100\nitems", "support": "full"}]},
    {"id": "c2", "claim": "454 of 789 kept.", "quotes": [{"file": "b.md", "line": 9, "text": "454 of 789", "support": "full",
                                                         "qualifier": {"file": "b.md", "line": 12, "text": "after expert review"}}]}]}
CLAIMS = [{"id": "c1", "importance": "central", "label": "official", "venue": "ETS", "url": "https://x.example/h",
           "votes": [{"refuted": False, "confidence": "high", "withheld": "the item bank", "evidence": "the handbook\n page"},
                     {"refuted": False, "confidence": "high", "withheld": "the item bank"}]},
          {"id": "c3", "importance": "central", "votes": [{"refuted": False, "confidence": "medium"}]},
          {"id": "c4", "importance": "central", "votes": [{"refuted": False, "confidence": "low"}]},
          {"id": "c5", "importance": "supporting", "votes": [{"refuted": False, "confidence": "high"}]}]


class Prose(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.report = self.dir / "report-x.md"
        self.report.write_text(REPORT, encoding="utf-8")
        (self.dir / "extracts-x.json").write_text(json.dumps(VIEW), encoding="utf-8")
        (self.dir / "claims.json").write_text(json.dumps(CLAIMS), encoding="utf-8")
        self.brief = self.dir / "brief.txt"

    def run_cmd(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = m.main([str(a) for a in args])
        return code, out.getvalue().splitlines()

    def test_brief_numbers_the_cited_statements_with_their_evidence(self):
        self.assertEqual(self.run_cmd("brief", self.report, self.brief, "--plant", "0"),
                         (0, [f"BRIEF\t4 statements\t0 planted\t{self.brief}"]))
        body = self.brief.read_text(encoding="utf-8").split("S<number>")[1]
        self.assertIn("S1. As of 2026-11-22 the test has 100 items [c1].\n  c1: The test has 100 items.\n"
                      "    source: official, ETS, https://x.example/h\n    withheld: the item bank\n"
                      "    vote: held, high: the handbook page\n    vote: held, high: \n"
                      '    quote (full): "100 items"', body)
        self.assertIn("S2. | Reading | 30 items [c1, c2] |\n  c1:", body)
        self.assertIn("S3. The pipeline kept 454 of 789 passages [c2].\n  c2: 454 of 789 kept.\n"
                      '    quote (full): "454 of 789"\n    qualifier: "after expert review"', body)
        self.assertIn("S4. A proposal follows [c9].\n  c9: not in the evidence view", body)
        self.assertIn("Not reached:\n  - the price list: walled\n\nS1.", body)
        self.assertNotIn("code is not prose", body)
        self.assertNotIn("| c1 | 100 items", body)

    def test_planted_copies_are_added_and_a_missed_one_fails_the_reply(self):
        self.assertEqual(self.run_cmd("brief", self.report, self.brief)[1], [f"BRIEF\t4 statements\t2 planted\t{self.brief}"])
        planted = [l.split("\t") for l in Path(str(self.brief) + ".planted.tsv").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(planted, [["S5", "S1", "As of 2026-11-22 the test has 203 items [c1]."],
                                   ["S6", "S2", "| Reading | 64 items [c1, c2] |"]])
        text = self.brief.read_text(encoding="utf-8")
        self.assertIn("S1. As of 2026-11-22 the test has 100 items [c1].", text)
        self.assertIn("S6. | Reading | 64 items [c1, c2] |\n  c1:", text)
        reply = self.dir / "reply.txt"
        reply.write_text("S1\tstated\t-\nS2\tstated\t-\nS3.\tStretched\tkept, with no review named\nnoise line\n"
                         "S5\twrong\t203\nS6\tstated\t-\n", encoding="utf-8")
        code, lines = self.run_cmd("score", self.report, self.brief, reply)
        self.assertEqual((code, lines), (1, [
            "STRETCHED\tS3\t11\tkept, with no review named\tThe pipeline kept 454 of 789 passages [c2].",
            "MISSING\tS4",
            "UNCITED\t3\tIt runs in three steps and nobody measured it.",
            "UNUSED\tc3",
            "PLANTED\t1 of 2 changed statements not rated stated",
            "PROSE\t4 statements\t3 rated\t2 stated\t1 stretched\t0 unbacked\t0 wrong"]))
        reply.write_text("S1\tstated\nS2\tstated\nS3\tstated\nS4\tunbacked\tall\nS5\twrong\nS6\tstretched\n", encoding="utf-8")
        self.assertEqual(self.run_cmd("score", self.report, self.brief, reply)[0], 0)

    def test_a_report_without_a_view_fails(self):
        (self.dir / "extracts-x.json").unlink()
        self.assertEqual(self.run_cmd("brief", self.report, self.brief), (1, ["FAIL\tno evidence view beside report-x.md"]))
