import json, os, subprocess, sys, tempfile, unittest, urllib.parse
from pathlib import Path
from types import SimpleNamespace
from tests._load import ROOT

HOOK = ROOT / "hooks" / "egress.py"


class EgressHookTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.home = root / "home"
        self.list_file = self.home / ".claude" / "phro-search" / "forbidden.txt"
        self.project_file = root / "proj" / ".phro" / "project.json"
        self.cwd = root / "proj" / "pkg" / "src"  # two folders below the project file
        for d in (self.list_file.parent, self.project_file.parent, self.cwd):
            d.mkdir(parents=True)
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home)}

    def forbid(self, *terms):
        self.list_file.write_text("\n".join(terms), encoding="utf-8")

    def project(self, *terms):
        self.project_file.write_text(json.dumps({"egress": {"forbidden_terms": terms}}, ensure_ascii=False),
                                     encoding="utf-8")

    def event(self, tool, tool_input):
        return {"session_id": "s1", "transcript_path": "", "cwd": str(self.cwd), "hook_event_name": "PreToolUse",
                "tool_name": tool, "tool_input": tool_input}

    def run_hook(self, event, cwd=None):
        data = event if isinstance(event, bytes) else json.dumps(event, ensure_ascii=False).encode("utf-8")
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", str(HOOK)], input=data, capture_output=True,
                           env=self.env, cwd=cwd, timeout=60)
        return SimpleNamespace(code=r.returncode, out=r.stdout.decode("utf-8"), err=r.stderr.decode("utf-8"))

    def search(self, query):
        return self.run_hook(self.event("WebSearch", {"query": query}))

    def assertBlocked(self, r, term, source):
        self.assertEqual((r.code, r.out), (2, ""), r.err)
        self.assertTrue(r.err.startswith("phro-search egress: blocked "), r.err)
        self.assertIn(f"the input contains '{term}', listed in {source}.", r.err)

    def assertAllowed(self, r):
        self.assertEqual((r.code, r.out, r.err), (0, "", ""))

    def assertClosed(self, r, *named):
        self.assertEqual((r.code, r.out), (2, ""), r.err)
        self.assertTrue(r.err.startswith("phro-search egress: "), r.err)
        for text in named:
            self.assertIn(text, r.err)

    def test_query_term_blocked_with_exact_message(self):
        self.forbid("orbit-9")
        r = self.search("how to tune orbit-9 telemetry")
        self.assertEqual(r.code, 2)
        self.assertEqual(r.err.strip(), "phro-search egress: blocked WebSearch: the input contains 'orbit-9', "
                         f"listed in {self.list_file}. Rewrite it as a generic problem statement without "
                         "project names, data or code names.")

    def test_percent_encoded_korean_term_in_url_blocked(self):
        self.forbid("푸른별")
        url = "https://example.com/wiki/" + urllib.parse.quote("푸른별 로그")
        r = self.run_hook(self.event("WebFetch", {"url": url, "prompt": "summarize"}))
        self.assertBlocked(r, "푸른별", self.list_file)

    def test_term_in_fetch_prompt_blocked(self):
        self.forbid("nimbus")
        r = self.run_hook(self.event("WebFetch", {"url": "https://example.com/", "prompt": "compare with nimbus"}))
        self.assertBlocked(r, "nimbus", self.list_file)

    def test_term_in_domain_list_blocked(self):
        self.forbid("orbit-9")
        r = self.run_hook(self.event("WebSearch", {"query": "telemetry", "allowed_domains": ["orbit-9.example.com"]}))
        self.assertBlocked(r, "orbit-9", self.list_file)

    def test_english_terms_match_case_insensitively(self):
        self.forbid("Nimbus")
        self.assertBlocked(self.search("nIMBUS roadmap"), "Nimbus", self.list_file)

    def test_korean_term_followed_by_particle_blocked(self):
        self.forbid("푸른별")
        self.assertBlocked(self.search("푸른별은 무엇인가"), "푸른별", self.list_file)

    def test_ascii_term_does_not_match_inside_a_longer_word(self):
        self.forbid("nimbus", "orbit-9")
        self.assertAllowed(self.search("cumulonimbus clouds"))
        self.assertAllowed(self.search("nimbuses"))
        self.assertBlocked(self.search("Orbit-9 results"), "orbit-9", self.list_file)

    def test_other_tools_pass_without_reading_any_list(self):
        self.forbid("orbit-9")
        self.assertAllowed(self.run_hook(self.event("Bash", {"command": "echo orbit-9"})))
        self.assertAllowed(self.run_hook(self.event("Read", {"file_path": "orbit-9.txt"})))
        self.project_file.write_text("{broken", encoding="utf-8")
        self.assertAllowed(self.run_hook(self.event("Bash", {"command": "echo orbit-9"})))

    def test_both_term_sources_are_read(self):
        self.forbid("# private names", "", "   ", "orbit-9", "  # indented comment")
        self.project("nimbus", "푸른별")
        self.assertBlocked(self.search("orbit-9"), "orbit-9", self.list_file)
        self.assertBlocked(self.search("nimbus"), "nimbus", self.project_file)
        self.assertBlocked(self.search("푸른별"), "푸른별", self.project_file)
        self.assertAllowed(self.search("# private names"))
        self.assertAllowed(self.search("# indented comment"))

    def test_no_list_anywhere_passes(self):
        self.assertAllowed(self.search("orbit-9 nimbus 푸른별"))

    def test_cwd_falls_back_to_the_process_cwd(self):
        self.project("nimbus")
        event = self.event("WebSearch", {"query": "nimbus"})
        del event["cwd"]
        self.assertBlocked(self.run_hook(event, cwd=self.cwd), "nimbus", self.project_file)

    def test_malformed_project_json_blocks_and_names_the_file(self):
        self.project_file.write_text('{"egress": {"forbidden_terms": "orbit-9"}}', encoding="utf-8")
        self.assertClosed(self.search("generic question"), str(self.project_file))
        self.project_file.write_text('{"egress": ', encoding="utf-8")
        self.assertClosed(self.search("generic question"), str(self.project_file))
        self.project_file.write_text('["orbit-9"]', encoding="utf-8")
        self.assertClosed(self.search("generic question"), str(self.project_file))

    def test_byte_order_mark_does_not_hide_the_first_term(self):
        # Windows editors often save UTF-8 with a BOM; it must not stick to the first term.
        self.list_file.write_text("orbit-9\nnimbus", encoding="utf-8-sig")
        self.assertBlocked(self.search("orbit-9"), "orbit-9", self.list_file)
        self.list_file.unlink()
        self.project_file.write_text(json.dumps({"egress": {"forbidden_terms": ["nimbus"]}}), encoding="utf-8-sig")
        self.assertBlocked(self.search("nimbus"), "nimbus", self.project_file)

    def test_unreadable_forbidden_txt_blocks_and_names_the_file(self):
        self.list_file.write_bytes(b"\xff\xfeorbit-9")
        self.assertClosed(self.search("generic question"), "forbidden.txt")

    def test_stdin_that_is_not_json_blocks(self):
        for data in (b"not json", b"", b"\xff\xfe"):
            with self.subTest(data=data):
                self.assertClosed(self.run_hook(data))


if __name__ == "__main__":
    unittest.main()
