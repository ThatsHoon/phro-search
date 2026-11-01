"""dev/routing.py: the routing set (R1) run headless, and the stream-json parsing that grades it."""
import contextlib, csv, io, json, re, shutil, tempfile, unittest
from pathlib import Path

from tests._load import ROOT, load

routing = load("dev/routing.py")

SAMPLE = ROOT / "tests/fixtures/routing/dig-fired.jsonl"
PROMPTS = ROOT / "evals/routing/prompts.tsv"
MODES = ("dig", "report", "pulse", "docs", "models", "watch")


def events():
    return [json.loads(l) for l in SAMPLE.read_text(encoding="utf-8").splitlines() if l.strip()]


def tool_use(name, inp, i=90):
    return {"type": "assistant", "parent_tool_use_id": None,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": f"toolu_{i}", "name": name, "input": inp}]}}


def text(t):
    return {"type": "assistant", "parent_tool_use_id": None, "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}}


def result(cost=0.2, error=False):
    return {"type": "result", "subtype": "error_during_execution" if error else "success", "is_error": error,
            "result": "", "total_cost_usd": cost}


def lines(evs):
    return [json.dumps(e, ensure_ascii=False) for e in evs]


class StreamTest(unittest.TestCase):
    def test_recorded_sample_fires_dig(self):
        got = routing.parse_stream(SAMPLE.read_text(encoding="utf-8").splitlines())
        self.assertEqual((got["fired"], got["mode"], got["via"], got["others"]), (True, "dig", "read", []))
        self.assertAlmostEqual(got["cost"], 0.3121)
        self.assertIsNone(got["error"])
        self.assertTrue(got["listed"])
        self.assertEqual(routing.outcome(got), "dig")  # the first mode reference read wins (report.md comes later)

    def test_other_skill(self):
        evs = [events()[0], tool_use("Skill", {"skill": "huggingface-best"}), text("Try bge-small."), result(0.11)]
        got = routing.parse_stream(lines(evs))
        self.assertEqual((got["fired"], got["mode"], got["others"]), (False, None, ["huggingface-best"]))
        self.assertEqual(routing.outcome(got), "other:huggingface-best")

    def test_no_skill(self):
        got = routing.parse_stream(lines([events()[0], text("Yes, two writers cannot."), result(0.05)]))
        self.assertEqual(routing.outcome(got), "none")
        self.assertAlmostEqual(got["cost"], 0.05)

    def test_mode_from_plan_line_when_no_mode_reference(self):
        evs = [events()[0], tool_use("Skill", {"command": "/phro-search:search"}),
               tool_use("Read", {"file_path": "C:\\Users\\u\\phro-search\\skills\\search\\references\\intake.md"}, 91),
               text("PLAN: pulse; 5 lanes; ceiling 1 script calls"), result()]
        got = routing.parse_stream(lines(evs))
        self.assertEqual((got["fired"], got["mode"], got["via"]), (True, "pulse", "plan"))
        self.assertEqual(routing.outcome(got), "pulse")

    def test_fired_without_mode(self):
        evs = [tool_use("Skill", {"skill": "phro-search:search"}), text("Which do you mean, A or B?"), result()]
        got = routing.parse_stream(lines(evs))
        self.assertEqual(routing.outcome(got), "search?")
        self.assertIsNone(got["listed"])  # no init event, so nobody knows whether the skill was listed

    def test_windows_path_and_bad_lines(self):
        evs = lines([tool_use("Skill", {"skill": "phro-search:search"}),
                     tool_use("Read", {"file_path": "D:\\a\\skills\\search\\references\\models.md"}, 92), result()])
        got = routing.parse_stream(["not json", ""] + evs)
        self.assertEqual(routing.outcome(got), "models")

    def test_errors(self):
        self.assertEqual(routing.outcome(routing.parse_stream(lines([text("partial")]))), "error:no result event")
        self.assertEqual(routing.outcome(routing.parse_stream(lines([result(error=True)]))), "error:error_during_execution")

    def test_skill_not_listed(self):
        init = dict(events()[0], skills=["huggingface-best"], slash_commands=["compact"])
        self.assertFalse(routing.parse_stream(lines([init, result()]))["listed"])


class RunTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.prompts = self.dir / "prompts.tsv"
        self.prompts.write_text("id\tkind\texpect\tlang\tprompt\tnote\n"
                                "dig-en-1\tin\tdig\ten\tTrace speculative decoding to its original papers.\t-\n"
                                "report-ko-1\tin\treport\tko\t\ubcf4\uace0\uc11c\ub85c \uc815\ub9ac\ud574\uc918: A vs B\t-\n"
                                "near-en-1\tnear\tnone\ten\tCheck for new posts in our Slack channel.\t-\n", encoding="utf-8")

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = routing.main(["--prompts", str(self.prompts), *args])
        return code, out.getvalue().splitlines()

    def save(self, rid, n, evs):
        (self.dir / "runs").mkdir(exist_ok=True)
        (self.dir / "runs" / f"{rid}-{n}.jsonl").write_text("\n".join(lines(evs)), encoding="utf-8")

    def test_dry_run_lists_commands_only(self):
        code, out = self.run_main("--dry-run", "--runs", "2", "--plugin-dir", str(self.dir))
        self.assertEqual(code, 0)
        cmds = [l for l in out if l.startswith("CMD\t")]
        self.assertEqual(len(cmds), 6)
        first = cmds[0].split("\t")
        self.assertEqual(first[1:3], ["dig-en-1", "1"])
        for part in ("claude", "-p", "--output-format", "stream-json", "--verbose", "--plugin-dir", "--tools",
                     "Skill,Read,Glob,Grep", "--max-budget-usd"):
            self.assertIn(part, first[3])
        self.assertNotIn("WebSearch", first[3])
        self.assertEqual(first[4:], ["stdin", "Trace speculative decoding to its original papers."])
        self.assertFalse((self.dir / "runs").exists())

    def test_installed_plugin_has_no_plugin_dir(self):
        _, out = self.run_main("--dry-run", "--installed")
        self.assertNotIn("--plugin-dir", out[0])

    def test_scores_saved_streams(self):
        fired = events()
        for n in (1, 2):
            self.save("dig-en-1", n, fired)
        self.save("report-ko-1", 1, [tool_use("Skill", {"skill": "phro-search:search"}),
                                     tool_use("Read", {"file_path": "/p/skills/search/references/report.md"}, 93), result(0.4)])
        self.save("report-ko-1", 2, [text("no skill"), result(0.1)])
        self.save("near-en-1", 1, [text("I cannot reach Slack."), result(0.05)])
        self.save("near-en-1", 2, [tool_use("Skill", {"skill": "phro-search:search"}),
                                   tool_use("Read", {"file_path": "/p/skills/search/references/watch.md"}, 94), result(0.3)])
        code, out = self.run_main("--from", str(self.dir / "runs"), "--runs", "2")
        self.assertEqual(code, 1)
        self.assertIn("RUN\tdig-en-1\t1\tdig\t0.3121", out)
        self.assertIn("RUN\treport-ko-1\t2\tnone\t0.1000", out)
        self.assertIn("PROMPT\tdig-en-1\tin\tdig\tfired 2/2\tright 2/2\tPASS", out)
        self.assertIn("PROMPT\treport-ko-1\tin\treport\tfired 1/2\tright 1/2\tFAIL", out)
        self.assertIn("PROMPT\tnear-en-1\tnear\tnone\tfired 1/2\tFAIL", out)
        self.assertIn("IN\tfired 3/4 75.0%\tright mode 3/4 75.0%\tthreshold 90%\tFAIL", out)
        self.assertIn("NEAR\tfired 1/2 50.0%\tthreshold 10%\tFAIL", out)
        self.assertIn("OUT\tfired 0/0\tthreshold 10%\t-", out)
        self.assertIn("ROUTING\tFAIL", out)
        self.assertEqual(out[-1], "COST\t1.4742 USD\t6 runs")

    def test_missing_stream_is_incomplete(self):
        for rid in ("dig-en-1", "report-ko-1"):
            self.save(rid, 1, events())
        self.save("near-en-1", 1, [text("no"), result()])
        code, out = self.run_main("--from", str(self.dir / "runs"), "--runs", "2")
        self.assertIn("RUN\tdig-en-1\t2\terror:no stream\t-", out)
        self.assertIn("ROUTING\tINCOMPLETE\t3 runs failed", out)
        self.assertEqual(code, 1)

    def test_filters(self):
        _, out = self.run_main("--dry-run", "--kind", "near", "--runs", "1")
        self.assertEqual([l.split("\t")[1] for l in out if l.startswith("CMD")], ["near-en-1"])
        _, out = self.run_main("--dry-run", "--ids", "report-ko-1,dig-en-1", "--runs", "1")
        self.assertEqual([l.split("\t")[1] for l in out if l.startswith("CMD")], ["dig-en-1", "report-ko-1"])

    def test_bad_prompt_file(self):
        self.prompts.write_text("id\tkind\texpect\tlang\tprompt\tnote\nx\tin\tnone\ten\thi\t-\n", encoding="utf-8")
        code, out = self.run_main("--dry-run")
        self.assertEqual(code, 2)
        self.assertTrue(out[0].startswith("FAIL\t"))


class PromptSetTest(unittest.TestCase):
    def rows(self):
        with PROMPTS.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))

    def test_shape(self):
        rows = self.rows()
        self.assertEqual(list(rows[0]), ["id", "kind", "expect", "lang", "prompt", "note"])
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        self.assertEqual(routing.load_prompts(PROMPTS), routing.load_prompts(PROMPTS))  # loads without error
        inn = [r for r in rows if r["kind"] == "in"]
        near = [r for r in rows if r["kind"] == "near"]
        out = [r for r in rows if r["kind"] == "out"]
        self.assertGreaterEqual(len(inn), 28)
        self.assertGreaterEqual(len(near), 12)
        self.assertGreaterEqual(len(out), 6)
        for mode in MODES:
            with self.subTest(mode=mode):
                langs = {r["lang"] for r in inn if r["expect"] == mode}
                self.assertEqual(langs, {"ko", "en"})
        self.assertTrue(all(r["expect"] == "none" for r in near + out))
        self.assertEqual({r["lang"] for r in near}, {"ko", "en"})

    def test_near_misses_from_r1_and_p9(self):
        near = " ".join(r["prompt"] for r in self.rows() if r["kind"] == "near")
        for words in ("\ubcf4\uace0\uc11c\ub85c \uc815\ub9ac\ud574\uc918", "scikit-learn", "best model for",
                      "\uc0c8 \uae00 \ud655\uc778", "Slack"):
            self.assertIn(words, near)
        self.assertRegex(near, r"(?i)test|build")  # coding-session complaints

    def test_t51_prompts_kept(self):
        prompts = [r["prompt"] for r in self.rows()]
        self.assertIn("best small embedding model for on-device semantic search on a phone", prompts)
        self.assertIn("Does SQLite in WAL mode allow two writers? Cite the official docs.", prompts)


if __name__ == "__main__":
    unittest.main()
