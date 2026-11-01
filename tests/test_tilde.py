"""A quoted ~ path reaches a script unexpanded by the shell; every path argument expands it itself (B1)."""
import contextlib, io, json, os, shutil, tempfile, unittest
from pathlib import Path
from unittest import mock

from tests._load import load


class TildeTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.cwd = Path(tempfile.mkdtemp()).resolve()  # an unexpanded ~ would land here, not in the repository
        self.addCleanup(shutil.rmtree, self.cwd, True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.cwd)

    def main(self, mod, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mod.main(argv)
        return code, out.getvalue()

    def test_fetch(self):
        m = load("scripts/fetch.py")
        (self.home / "saved.md").write_text("First line\n" + "word " * 400, encoding="utf-8")
        with mock.patch.object(m, "egress_terms", lambda: []):
            code, out = self.main(m, ["~/topic/sources", "note", "~/saved.md"])
        self.assertEqual(code, 0, out)
        self.assertTrue((self.home / "topic" / "sources" / "note.md").is_file())
        self.assertFalse((self.cwd / "~").exists())

    def test_report(self):
        m = load("scripts/report.py")
        topic = self.home / "topic"
        (topic / "sources").mkdir(parents=True)
        (topic / "sources" / "a.md").write_text("alpha beta\n", encoding="utf-8")
        claim = {"claim": "A holds.", "status": "sourced",
                 "quotes": [{"file": "a.md", "line": 1, "text": "alpha beta", "url": "https://example.org/a",
                             "mark": "paper", "support": "full"}]}
        data = {"title": "Evidence", "question": "Does it hold?", "stopped": "saturated", "claims": [claim]}
        (topic / "extracts.json").write_text(json.dumps(data), encoding="utf-8")
        code, out = self.main(m, ["~/topic", "--check"])
        self.assertEqual(code, 0, out)

    def test_check(self):
        m = load("scripts/check.py")
        (self.home / "note.md").write_text("The parser reads 12 files in 4 s.\n", encoding="utf-8")
        self.assertEqual(self.main(m, ["~/note.md"]), (0, "OK\n"))
        self.assertEqual(self.main(m, ["--kind", "models", "~/note.md"]), (0, "OK\n"))

    def test_models(self):
        m = load("scripts/models.py")
        seen = []
        with mock.patch.object(m, "egress_terms", lambda cwd=None: []), \
                mock.patch.object(m, "shortlist", lambda args, topic: seen.append(topic) or 0):
            self.assertEqual(self.main(m, ["shortlist", "~/topic", "--board", "asr"])[0], 0)
        self.assertEqual(seen, [self.home / "topic"])

    def test_pulse(self):
        m = load("scripts/pulse.py")
        (self.home / "plan.json").write_text("[]", encoding="utf-8")
        code, out = self.main(m, ["~/topic", "--plan", "~/plan.json"])
        self.assertEqual(code, 2)
        self.assertNotIn("cannot read", out)  # the plan was read: it fails only for its shape

    def test_watch(self):
        m = load("scripts/watch.py")
        (self.home / "topic").mkdir()
        (self.home / "topic" / "watch.tsv").write_text("kind\tname\tfeed\tsource\nrss\tblog\thttps://e.example/f\t-\n",
                                                       encoding="utf-8")
        self.assertEqual(self.main(m, ["list", "~/topic"]), (0, "rss\tblog\thttps://e.example/f\t-\n"))


if __name__ == "__main__":
    unittest.main()
