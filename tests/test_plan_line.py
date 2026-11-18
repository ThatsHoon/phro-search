import importlib.util, json, os, shutil, subprocess, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "plan_line.py"
SH = shutil.which("sh")


def skill():
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "phro-search:search"}}]}}


def read(path):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": path}}]}}


def say(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


REPORT = "C:\\cache\\phro-search\\0.4.0\\skills\\search\\references\\report.md"


class PlanLine(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def transcript(self, *lines):
        path = self.dir / "t.jsonl"
        path.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines), encoding="utf-8")
        return path

    def run_hook(self, path):
        event = json.dumps({"transcript_path": str(path), "tool_name": "WebSearch", "tool_input": {"query": "x"}})
        return subprocess.run(["python", "-I", "-X", "utf8", str(HOOK)], input=event, capture_output=True, text=True, encoding="utf-8")

    def test_blocks_a_call_after_the_mode_reference_with_no_plan_line(self):
        r = self.run_hook(self.transcript(skill(), read(REPORT), say("Starting now.")))
        self.assertEqual(r.returncode, 2)
        self.assertIn("PLAN:", r.stderr)

    def test_allows_once_the_plan_line_is_sent(self):
        path = self.transcript(skill(), read(REPORT), say("PLAN: report; 2 rounds; ceiling 9 agent calls"))
        self.assertEqual(self.run_hook(path).returncode, 0)

    def test_waits_for_a_plan_line_still_being_written(self):
        path = self.transcript(skill(), read(REPORT))
        def late():
            time.sleep(.5)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(say("PLAN: report; 2 rounds; ceiling 9 agent calls")) + "\n")
        t = threading.Thread(target=late)
        t.start()
        self.addCleanup(t.join)
        self.assertEqual(self.run_hook(path).returncode, 0)

    def test_allows_the_probe_before_a_mode_reference(self):
        intake = REPORT.replace("report.md", "intake.md")
        self.assertEqual(self.run_hook(self.transcript(skill(), read(intake))).returncode, 0)

    def test_allows_sessions_without_the_skill(self):
        self.assertEqual(self.run_hook(self.transcript(read(REPORT), say("hello"))).returncode, 0)

    def test_a_new_run_of_the_skill_needs_its_own_plan_line(self):
        path = self.transcript(skill(), read(REPORT), say("PLAN: report; 2 rounds; ceiling 9 agent calls"), skill(), read(REPORT))
        self.assertEqual(self.run_hook(path).returncode, 2)

    def test_a_slash_command_starts_the_skill_too(self):
        slash = {"type": "user", "message": {"content": "<command-name>/phro-search:search</command-name>"}}
        self.assertEqual(self.run_hook(self.transcript(slash, read(REPORT))).returncode, 2)

    def test_plan_in_the_middle_of_a_line_does_not_count(self):
        path = self.transcript(skill(), read(REPORT), say("the PLAN: comes later"))
        self.assertEqual(self.run_hook(path).returncode, 2)

    def test_fails_open(self):
        for path in (self.dir / "missing.jsonl", self.transcript("not json", skill(), "{broken", read(REPORT).__repr__())):
            with self.subTest(path=path.name):
                self.assertEqual(self.run_hook(path).returncode, 0)
        r = subprocess.run(["python", "-I", "-X", "utf8", str(HOOK)], input="not json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    @unittest.skipUnless(SH, "needs sh")
    def test_wrapper_runs_the_check_and_skips_python_without_the_skill(self):
        def wrap(path):
            event = json.dumps({"transcript_path": str(path)})
            return subprocess.run([SH, (ROOT / "hooks" / "plan_line.sh").as_posix()], input=event, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(wrap(self.transcript(skill(), read(REPORT))).returncode, 2)
        self.assertEqual(wrap(self.transcript(say("hello"))).returncode, 0)
        self.assertEqual(wrap(self.dir / "missing.jsonl").returncode, 0)

    def big(self, *lines, filler_mb=20):
        path = self.dir / "big.jsonl"
        row = json.dumps(say("x" * 1000)) + "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(row * (filler_mb * 1024))
            f.write("".join(json.dumps(x) + "\n" for x in lines))
        return path

    def test_a_long_transcript_is_read_from_its_tail(self):
        path = self.big(skill(), read(REPORT))
        self.assertEqual(self.run_hook(path).returncode, 2)
        spec = importlib.util.spec_from_file_location("plan_line", HOOK)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        lines, end = m.read_lines(path)
        self.assertEqual((len(lines), end), (2, path.stat().st_size))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(say("PLAN: report; 2 rounds; ceiling 9 agent calls")) + "\n" + '{"partial')
        more, after = m.read_lines(path, end)
        self.assertEqual((len(more), after), (1, path.stat().st_size - len('{"partial')), "a retry reads only the new complete lines")

    def test_a_run_older_than_the_tail_does_not_block(self):
        path = self.big(skill(), read(REPORT), filler_mb=0)
        with open(path, "a", encoding="utf-8") as f:
            f.write((json.dumps(say("x" * 1000)) + "\n") * (10 * 1024))
        self.assertEqual(self.run_hook(path).returncode, 0)

    @unittest.skipUnless(SH, "needs sh")
    def test_wrapper_finds_the_skill_in_a_long_transcript(self):
        event = json.dumps({"transcript_path": str(self.big(skill(), read(REPORT)))})
        r = subprocess.run([SH, (ROOT / "hooks" / "plan_line.sh").as_posix()], input=event, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)

    def test_registered_in_hooks_json(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        entry = next(h for h in hooks if "plan_line.sh" in h["hooks"][0]["command"])
        self.assertEqual(entry["matcher"], "Agent|Task|WebSearch|WebFetch")


if __name__ == "__main__":
    unittest.main()
