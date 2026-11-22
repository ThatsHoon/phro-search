"""dev/replay_support.py: the support pass replayed on a delivered view's quotes."""
import contextlib, io, json, shutil, tempfile, unittest
from pathlib import Path

from tests._load import load

replay = load("dev/replay_support.py")
NL, TAB = chr(10), chr(9)
VIEW = {"claims": [{"id": "c2", "claim": "B holds.", "quotes": [{"file": "b.md", "line": 7, "text": "b text", "support": "full"}]},
                   {"claim": "A holds.", "quotes": [{"file": "a.md", "line": 3, "text": "a text", "support": "partial"},
                                                    {"file": "a.md", "line": 9, "text": "late", "support": "full"}]}]}


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.view = self.dir / "extracts.json"
        self.view.write_text(json.dumps(VIEW), encoding="utf-8")

    def call(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = replay.main([str(a) for a in argv])
        return code, out.getvalue().splitlines()

    def test_build_lists_the_quotes_by_file_in_the_live_brief(self):
        out = self.dir / "brief.txt"
        self.assertEqual(self.call("build", self.dir, self.view, out), (0, [TAB.join(["BUILT", "3 quotes", "2 files", str(out)])]))
        brief = out.read_text(encoding="utf-8")
        self.assertTrue(brief.startswith("You are a support reader. Read only files in " + self.dir.as_posix() + "/sources."))
        self.assertIn(NL.join(['2. A holds. | a.md:3 "a text"', '2. A holds. | a.md:9 "late"', 'c2. B holds. | b.md:7 "b text"']), brief)
        self.call("build", self.dir, self.view, out, "--limit", "1")
        self.assertNotIn("b.md:7", out.read_text(encoding="utf-8"))

    def test_score_compares_the_reply_with_the_view(self):
        reply = self.dir / "reply.txt"
        reply.write_text(NL.join([TAB.join(["2", "a.md:3", "full", "-", "-", "They measured it."]),
                                  TAB.join(["c2", "b.md:7", "full", "-", "-", "-"]), "not a line"]), encoding="utf-8")
        self.assertEqual(self.call("score", self.dir, self.view, reply),
                         (0, [TAB.join(["CHANGED", "2", "a.md:3", "partial", "full"]), TAB.join(["MISSING", "2", "a.md:9"]),
                              TAB.join(["REPLAY", "3 quotes sent", "2 rated", "1 of 2 agree with the view", "1 with a gist"])]))
        self.assertEqual(self.call("score", self.dir, self.view, reply, "--sent", "1")[1][-1],
                         TAB.join(["REPLAY", "1 quotes sent", "1 rated", "0 of 1 agree with the view", "1 with a gist"]))
        self.assertEqual(self.call("score", self.dir, self.view, self.dir / "none.txt")[0], 1)


if __name__ == "__main__":
    unittest.main()
