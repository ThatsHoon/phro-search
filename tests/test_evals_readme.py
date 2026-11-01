"""evals/README.md names only flags the dev scripts take."""
import contextlib, io, re, unittest

from tests._load import ROOT, load


class ReadmeTest(unittest.TestCase):
    def test_flags_match_help(self):
        readme = (ROOT / "evals/README.md").read_text(encoding="utf-8")
        named = {}
        for script, rest in re.findall(r"dev/([\w]+\.py)([^`\n]*)", readme):
            named.setdefault(script, set()).update(re.findall(r"--[a-z][\w-]*", rest))
        self.assertLessEqual({"routing.py", "score_round0.py", "score_verifiers.py"}, set(named))
        for script, flags in named.items():
            mod = load("dev/" + script)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                mod.main(["--help"])
            with self.subTest(script=script):
                self.assertEqual(sorted(f for f in flags if f not in out.getvalue()), [])


if __name__ == "__main__":
    unittest.main()
