"""dev/score_verifiers.py: false refutations of true claims and false survivals of false claims (R1, R6)."""
import contextlib, io, json, shutil, tempfile, unittest
from pathlib import Path

from tests._load import load

score = load("dev/score_verifiers.py")


def vote(refuted):
    return {"refuted": refuted, "confidence": "high", "evidence": "-", "counter_source": "", "checked": "2026-11-01"}


CLAIMS = [
    {"id": "c1", "claim": "true one", "votes": [vote(False), vote(False), vote(False)], "verdict": "survived"},
    {"id": "c2", "claim": "true two", "votes": [vote(True), vote(False), vote(False)], "verdict": "survived"},
    {"id": "c3", "claim": "true three", "votes": [vote(True), vote(True), vote(False)], "verdict": "refuted"},
    {"id": "c4", "claim": "false one", "votes": [vote(True), vote(True), vote(True)], "verdict": "refuted"},
    {"id": "c5", "claim": "false two", "votes": [vote(False), vote(False), vote(True)], "verdict": "survived"},
    {"id": "c6", "claim": "false three", "votes": [vote(True), {"refuted": "maybe"}], "verdict": "unverified"},
    {"id": "c9", "claim": "not planted", "votes": [vote(True)]},
]
PLANTED = "# id\ttruth\tvariant\nid\ttruth\tvariant\nc1\ttrue\ttrue\nc2\ttrue\ttrue\nc3\tTRUE\ttrue\nc4\tfalse\toverstated\nc5\tfalse\toutdated\nc6\tfalse\tcontradicted\nc7\ttrue\ttrue\n"


class VerifierScoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.planted = self.dir / "planted.tsv"
        self.planted.write_text(PLANTED, encoding="utf-8")
        self.claims = self.dir / "claims.json"
        self.claims.write_text(json.dumps(CLAIMS), encoding="utf-8")

    def run_score(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = score.main([str(self.planted), str(self.claims), *args])
        return code, out.getvalue().splitlines()

    def test_scores(self):
        code, out = self.run_score()
        self.assertEqual(code, 0)
        self.assertIn("CLAIM\tc1\ttrue\trefuted 0/3\tsurvived\tok", out)
        self.assertIn("CLAIM\tc3\ttrue\trefuted 2/3\trefuted\tfalse refutation", out)
        self.assertIn("CLAIM\tc5\tfalse\trefuted 1/3\tsurvived\tfalse survival", out)
        self.assertIn("CLAIM\tc6\tfalse\trefuted 1/1\tunverified\tno verdict", out)  # a vote that does not parse is no vote
        self.assertIn("MISSING\tc7\tnot in claims.json", out)
        self.assertIn("# c6: 1 of 3 votes", out)
        self.assertIn("TRUE\t3 claims\tvotes refuting 3/9 33.3%\tverdicts refuted 1/3 33.3%\tunverified 0", out)
        self.assertIn("FALSE\t3 claims\tvotes not refuting 2/7 28.6%\tverdicts survived 1/3 33.3%\tunverified 1", out)
        self.assertEqual(out[-1], "R6\tfalse refutations of true claims 1/3 33.3% of verdicts\tthreshold 10%\tcrossed\t"
                                  "switch to: refuted needs a stated reason from the check list; could not check is no vote")

    def test_verdict_from_votes_not_the_file(self):
        claims = [dict(c, verdict="survived") for c in CLAIMS]  # a stale verdict field
        self.claims.write_text(json.dumps(claims), encoding="utf-8")
        _, out = self.run_score()
        self.assertIn("CLAIM\tc3\ttrue\trefuted 2/3\trefuted\tfalse refutation", out)
        self.assertIn("# c3: verdict in claims.json is survived, the votes give refuted", out)

    def test_below_threshold(self):
        claims = CLAIMS[:2] + [dict(CLAIMS[0], id="c8")] + [CLAIMS[3]]
        self.planted.write_text("c1\ttrue\nc8\ttrue\nc4\tfalse\n", encoding="utf-8")
        self.claims.write_text(json.dumps(claims), encoding="utf-8")
        _, out = self.run_score()
        self.assertIn("TRUE\t2 claims\tvotes refuting 0/6 0.0%\tverdicts refuted 0/2 0.0%\tunverified 0", out)
        self.assertEqual(out[-1], "R6\tfalse refutations of true claims 0/2 0.0% of verdicts\tthreshold 10%\tnot crossed\tkeep the vote rule")

    def test_bad_inputs(self):
        self.planted.write_text("c1\tmaybe\n", encoding="utf-8")
        code, out = self.run_score()
        self.assertEqual(code, 1)
        self.assertTrue(out[0].startswith("FAIL\t"))
        self.planted.write_text("c1\ttrue\n", encoding="utf-8")
        self.claims.write_text("{not json", encoding="utf-8")
        code, out = self.run_score()
        self.assertEqual(code, 1)
        self.assertTrue(out[0].startswith("FAIL\t"))


if __name__ == "__main__":
    unittest.main()
