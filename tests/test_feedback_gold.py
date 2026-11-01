"""dev/feedback_gold.py: the items users said were missing, as gold-item candidates for the eval sets."""
import contextlib, io, re, shutil, tempfile, unittest
from pathlib import Path

from tests._load import ROOT, load

gold = load("dev/feedback_gold.py")

LOG_A = """# log: asr-small

## 2026-10-02 intake
brief: mode=models; object=small ASR models; deliverable=table; scope=-; evidence=boards; budget=-

## 2026-10-02 stop
stop: answered
feedback: fit=partly; missing=Korean WER on noisy speech | the Whisper turbo variant
- feedback, verbatim: "\uc7a1\uc74c \uc788\ub294 \ud55c\uad6d\uc5b4 WER\uc774 \uc5c6\uc5b4\uc694"

## 2026-10-20 intake
brief: mode=pulse; object=ASR releases; deliverable=brief; scope=30 days; evidence=-; budget=-

## 2026-10-20 stop
feedback: fit=yes; missing=none
"""
LOG_B = """# log: old-topic

## 2026-09-01 stop
feedback: "too shallow"
"""


class FeedbackGoldTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        for topic, text in (("asr-small", LOG_A), ("old-topic", LOG_B)):
            (self.root / topic).mkdir()
            (self.root / topic / "log.md").write_text(text, encoding="utf-8")

    def run_gold(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gold.main([str(self.root), *args])
        return code, out.getvalue().splitlines()

    def test_missing_items_become_gold_lines(self):
        code, out = self.run_gold()
        self.assertEqual(code, 0)
        self.assertEqual(out, [
            "GOLD\tasr-small\t2026-10-02\tmodels\tpartly\tKorean WER on noisy speech",
            "GOLD\tasr-small\t2026-10-02\tmodels\tpartly\tthe Whisper turbo variant",
            "# old-topic/log.md:4: feedback line not normalized",
            "# 2 feedback lines: 1 yes, 1 partly, 0 no; 2 gold items",
        ])

    def test_since_keeps_later_lines(self):
        _, out = self.run_gold("--since", "2026-10-10")
        self.assertEqual(out, ["# old-topic/log.md:4: feedback line not normalized",
                               "# 1 feedback lines: 1 yes, 0 partly, 0 no; 0 gold items"])

    def test_missing_root_fails(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gold.main([str(self.root / "nope")])
        self.assertEqual(code, 1)
        self.assertTrue(out.getvalue().startswith("FAIL\t"))

    def test_normalized_line_matches_the_log_template(self):
        formats = (ROOT / "skills/search/references/formats.md").read_text(encoding="utf-8")
        line = re.search(r"^feedback: .*$", formats, re.M).group(0)
        self.assertEqual(line, "feedback: fit=<yes|partly|no>; missing=<what the answer says is missing or off: item | item, or none>")
        self.assertRegex(formats, r'(?m)^- feedback, verbatim: "<the user\'s answer>"$')
        self.assertTrue(gold.NORMAL.match("feedback: fit=no; missing=a | b"))
        skill = (ROOT / "skills/search/SKILL.md").read_text(encoding="utf-8")
        rule = re.search(r"^- Close a delivered result with the feedback question.*$", skill, re.M).group(0)
        for words in ("verbatim", "`feedback: fit=yes|partly|no; missing=", "no further question"):
            self.assertIn(words, rule)
