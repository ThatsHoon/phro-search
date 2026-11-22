"""dev/plant_verifiers.py: the briefs of a planted set come from report.md as it stands, and replies become votes."""
import contextlib, io, json, shutil, tempfile, unittest
from pathlib import Path

from tests._load import load

plant = load("dev/plant_verifiers.py")
NL = chr(10)
CLAIM = {"id": "c1", "claim": "The tool reads seven formats.", "quote": "reads seven formats", "url": "https://a.example/x",
         "label": "official", "standing": "reviewed", "venue": "A Conf", "importance": "central"}
SPEC = [{"id": "p01", "topic": "t", "claim": "c1", "truth": True, "variant": "true"},
        {"id": "p02", "topic": "t", "claim": "c1", "truth": False, "variant": "altered",
         "claim_text": "The tool reads nine formats.", "replace": [["seven", "nine"]]}]


class PlantTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        topic = self.dir / "root" / "t"
        (topic / "sources").mkdir(parents=True)
        (topic / "claims.json").write_text(json.dumps([CLAIM]), encoding="utf-8")
        (topic / "map.md").write_text("## Brief" + NL + "Object: which tool reads the files" + NL, encoding="utf-8")
        (topic / "sources" / "a.md").write_text(NL.join(["# Tool", "", "It was tested.", "It reads seven formats.", "", "Other."]), encoding="utf-8")
        view = {"claims": [{"id": "c1", "quotes": [{"file": "a.md", "line": 4, "text": "reads seven formats"}]}]}
        (topic / "extracts-2026-11-01.json").write_text(json.dumps(view), encoding="utf-8")
        (self.dir / "spec.json").write_text(json.dumps(SPEC), encoding="utf-8")
        self.run_dir = self.dir / "run"

    def call(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = plant.main([str(a) for a in argv])
        return code, out.getvalue().splitlines()

    def test_build_fills_the_live_brief_and_collect_reads_the_votes(self):
        self.assertEqual(self.call("build", self.dir / "spec.json", self.dir / "root", self.run_dir)[0], 0)
        first = (self.run_dir / "briefs" / "p01-1.txt").read_text(encoding="utf-8")
        self.assertTrue(first.startswith("You are a verifier."))
        self.assertNotIn("<", first.split("Reply with one JSON object")[0])
        for part in ("Claim: The tool reads seven formats.", '"reads seven formats" from https://a.example/x (official)',
                     "Source standing: reviewed, A Conf", "It was tested." + NL + "It reads seven formats.",
                     "Start with: what is withheld", "It serves the question: which tool reads the files", "Review vouched"):
            self.assertIn(part, first)
        self.assertIn("Start with: counter-evidence", (self.run_dir / "briefs" / "p01-2.txt").read_text(encoding="utf-8"))
        altered = (self.run_dir / "briefs" / "p02-1.txt").read_text(encoding="utf-8")
        self.assertIn("Claim: The tool reads nine formats.", altered)
        self.assertIn("It reads nine formats.", altered)
        self.assertNotIn("seven", altered)
        self.assertEqual((self.run_dir / "planted.tsv").read_text(encoding="utf-8").splitlines()[1:],
                         ["p01\ttrue\ttrue", "p02\tfalse\taltered"])
        votes = self.run_dir / "votes"
        (votes / "p01-1.json").write_text('Here it is: {"refuted": false, "confidence": "high", "evidence": "e"}', encoding="utf-8")
        (votes / "p01-2.json").write_text("I could not decide.", encoding="utf-8")
        (votes / "p02-1.json").write_text('{"refuted": true, "confidence": "high", "evidence": "e"}', encoding="utf-8")
        code, lines = self.call("collect", self.run_dir)
        self.assertEqual((code, lines), (0, ["VOTE\tp01-1\theld", "VOTE\tp01-2\tno vote", "VOTE\tp02-1\trefuted", "VOTE\tp02-2\tno vote",
                                             "COLLECTED\t2 votes on 2 claims, 2 missing"]))
        saved = json.loads((self.run_dir / "claims.json").read_text(encoding="utf-8"))
        self.assertEqual([[v["refuted"] for v in c["votes"]] for c in saved], [[False], [True]])

    def test_a_spec_that_names_no_claim_or_no_text_to_replace_fails(self):
        (self.dir / "spec.json").write_text(json.dumps([dict(SPEC[0], claim="c9")]), encoding="utf-8")
        self.assertEqual(self.call("build", self.dir / "spec.json", self.dir / "root", self.run_dir)[0], 1)
        (self.dir / "spec.json").write_text(json.dumps([dict(SPEC[1], replace=[["eight", "nine"]])]), encoding="utf-8")
        self.assertEqual(self.call("build", self.dir / "spec.json", self.dir / "root", self.run_dir)[0], 1)


if __name__ == "__main__":
    unittest.main()
