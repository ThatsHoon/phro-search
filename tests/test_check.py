import json, subprocess, sys, tempfile, unittest
from pathlib import Path
from tests._load import ROOT, load

m = load("scripts/check.py")
SCRIPT = str(ROOT / "scripts/check.py")
FILL = "가나다라마바사아자차 "  # 10 body characters and no flagged phrase
EM, EN, BAR = "\U00002014", "\U00002013", "\U00002015"
CHECK, HEART, DOT, CIRCLED, ARROW, DARROW = "\U00002705", "\U00002764\U0000FE0F", "\U000025CF", "\U00002460", "\U00002192", "\U000021D2"


def rules(text):
    return [(line, rule) for line, rule, _ in m.check(text)]


def run(*args, data=None):
    r = subprocess.run([sys.executable, "-I", SCRIPT, *args], input=data, capture_output=True, timeout=60)
    return r.returncode, r.stdout.decode("utf-8").splitlines(), r.stderr.decode("utf-8")


class StyleRuleTest(unittest.TestCase):
    def test_clean_text_passes(self):
        self.assertEqual(m.check(FILL * 30 + "\n"), [])
        self.assertEqual(m.check("The parser reads 12 files in 4 s and writes one report.\n"), [])
        self.assertEqual(m.check(""), [])

    def test_hard_phrase_names_line_and_phrase(self):
        text = FILL + "\n\n결론적으로 좋다.\n혁신적인 방법이다.\n"
        self.assertEqual(m.check(text), [(3, "phrase", "결론적으로"), (4, "phrase", "혁신적")])

    def test_every_hard_phrase_is_found(self):
        for w in m.HARD_PHRASES:
            self.assertEqual(m.check(f"앞 {w} 뒤\n"), [(1, "phrase", w)], w)

    def test_english_hard_phrases(self):
        for s in ("In conclusion, it works.", "A game-changer for search.", "Generated with a tool.",
                  "Hope this helps!", "We delve into it.", "IN SUMMARY the tool works."):
            self.assertEqual([r for _, r, _ in m.check(s + "\n")], ["phrase"], s)

    def test_english_phrase_needs_whole_word(self):
        self.assertEqual(m.check("It was used as an aid by an aide.\n"), [])
        self.assertEqual(rules("AI-generated한 요약이다.\n"), [(1, "phrase")])

    def test_symbol(self):
        got = m.check(f"완료 {CHECK}\n")
        self.assertEqual([(l, r) for l, r, _ in got], [(1, "symbol")])
        self.assertIn("U+2705", got[0][2])
        self.assertIn("comma", got[0][2])
        self.assertEqual(m.check(HEART + "\n")[0][2].split(",")[0], "U+2764 U+FE0F")
        self.assertEqual(rules(f"{DOT} 항목\n"), [(1, "symbol")])
        self.assertEqual(m.check(f"{CIRCLED} 결과와 {ARROW} 화살표 하나\n"), [])

    def test_dash(self):
        for ch, name in ((EM, "em dash"), (EN, "en dash"), (BAR, "horizontal bar")):
            got = m.check(f"앞 {ch} 뒤\n")
            self.assertEqual([(l, r) for l, r, _ in got], [(1, "dash")], name)
            self.assertIn(f"U+{ord(ch):04X} {name}", got[0][2])
            self.assertIn("comma, a colon or parentheses", got[0][2])
        self.assertEqual(m.check("3-5개, 3~5개, 앞-뒤\n"), [])

    def test_invisible_characters(self):
        for cp in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x00A0, 0x202F):
            got = m.check(f"정상 문장이다.{chr(cp)} 다음 문장이다.\n")
            self.assertEqual([(l, r) for l, r, _ in got], [(1, "invisible")], hex(cp))
            self.assertIn(f"U+{cp:04X}", got[0][2])

    def test_translationese_density(self):
        hits = "\n".join(["이를 통해 풀었다."] * 5)
        got = m.check(FILL * 100 + "\n" + hits + "\n")
        self.assertEqual(got[0], (0, "density", "translationese: 5 hits, 4.8 per 1,000 characters (limit 4.0)"))
        self.assertEqual(got[1:], [(n, "density", "를 통해 풀었다.") for n in range(2, 7)])
        self.assertEqual(m.check(FILL * 100 + "\n" + "\n".join(["이를 통해 풀었다."] * 4) + "\n"), [])

    def test_empty_modifier_density(self):
        self.assertEqual(m.check("다양한 방법이다.\n" * 2), [])
        got = m.check("다양한 방법이다.\n" * 3)
        self.assertEqual(got[0], (0, "density", "empty modifiers: 3 hits, 3.0 per 1,000 characters (limit 2.0)"))
        self.assertEqual(len(got), 4)

    def test_density_scales_with_length(self):
        hit, long = "이를 통해 풀었다.\n", FILL * 500 + "\n"  # 5,000 body characters allow about 20 hits
        self.assertEqual(m.check(long + hit * 18), [])
        self.assertEqual(m.check(long + hit * 25)[0][:2], (0, "density"))

    def test_per_document_patterns(self):
        got = m.check("다음과 같이 정리한다.\n다음과 같은 결과다.\n")
        self.assertEqual(got[0], (0, "per-doc", "signpost sentence: 2 hits (limit 1)"))
        self.assertEqual([g[:2] for g in got[1:]], [(1, "per-doc"), (2, "per-doc")])
        self.assertEqual(m.check("다음과 같이 정리한다.\n"), [])
        self.assertEqual(m.check("정말일까요?\n"), [])
        got = m.check("좋다. 정말일까요?\n그럴까?\n")
        self.assertEqual(got, [(0, "per-doc", "rhetorical question: 2 hits (limit 1)"),
                               (1, "per-doc", "정말일까요?"), (2, "per-doc", "그럴까?")])
        self.assertEqual(m.check(f"가 {ARROW} 나 -> 다\n"), [])
        self.assertEqual(m.check(f"가 {ARROW} 나 {DARROW} 다 -> 라\n")[0], (0, "per-doc", "arrows: 3 hits (limit 2)"))

    def test_openers(self):
        got = m.check("\n".join(["또한 메모리를 줄였다."] * 4))
        self.assertEqual(got[0], (0, "opener", '"또한" starts 4 sentences (limit 3)'))
        self.assertEqual([g[0] for g in got[1:]], [1, 2, 3, 4])
        self.assertEqual(m.check("\n".join(["또한 메모리를 줄였다."] * 3)), [])
        self.assertEqual(rules("좋다. 또한 빠르다. 또한 작다. 또한 싸다. 또한 쉽다.\n")[0], (0, "opener"))
        self.assertEqual(rules("- 특히 하나다.\n" * 4)[0], (0, "opener"))
        self.assertEqual(rules("## 즉, 같다.\n" * 4)[0], (0, "opener"))

    def test_openers_must_start_a_sentence(self):
        self.assertEqual(m.check("이것도 또한 그렇다.\n" * 5), [])
        self.assertEqual(m.check("즉시 응답한다.\n" * 5), [])

    def test_bold_cap_grows_with_length(self):
        self.assertEqual(m.check("**가** **나** **다**\n"), [])
        got = m.check("**가** **나** **다** **라**\n")
        self.assertEqual(got[0], (0, "bold", "4 bold spans (limit 3)"))
        self.assertEqual(got[1][:2], (1, "bold"))
        self.assertEqual(rules("__가__ __나__ __다__ __라__\n")[0], (0, "bold"))
        long = FILL * 300 + "\n"
        self.assertEqual(m.check(long + "**가**\n" * 5), [])
        self.assertEqual(m.check(long + "**가**\n" * 6)[0], (0, "bold", "6 bold spans (limit 5)"))


class ScopeTest(unittest.TestCase):
    BAD = f"결론적으로 {EM} {CHECK}\n"

    def test_unquoted_text_is_checked(self):
        self.assertEqual({r for _, r in rules(self.BAD)}, {"phrase", "dash", "symbol"})

    def test_blockquote_is_exempt(self):
        self.assertEqual(m.check("> " + self.BAD), [])
        self.assertEqual(m.check("   > " + self.BAD), [])
        self.assertEqual(rules("> 인용\n" + self.BAD)[0], (2, "phrase"))

    def test_inline_code_is_exempt(self):
        self.assertEqual(m.check(f"예시는 `결론적으로 {EM} {CHECK}` 형태다.\n"), [])
        self.assertEqual(m.check(f"예시는 ``a ` {EM}`` 형태다.\n"), [])

    def test_fenced_code_is_exempt(self):
        self.assertEqual(m.check("설명이다.\n```python\n" + self.BAD + "```\n끝이다.\n"), [])
        self.assertEqual(m.check("~~~\n" + self.BAD + "~~~\n"), [])
        self.assertEqual(m.check("- 항목\n    ```\n" + self.BAD + "    ```\n"), [])  # indented under a list item
        self.assertEqual(m.check("```\n" + self.BAD), [])  # an unclosed fence runs to the end
        self.assertEqual(m.check("````\n```\n" + self.BAD + "````\n"), [])  # a shorter fence does not close it

    def test_text_after_a_fence_is_checked_again(self):
        self.assertEqual(rules("```\ncode\n```\n결론적으로\n"), [(4, "phrase")])
        self.assertEqual(rules("```\ncode\n`````\n결론적으로\n"), [(4, "phrase")])
        self.assertEqual(rules("```\na\n```\n```\nb\n```\n결론적으로\n"), [(7, "phrase")])

    def test_url_is_exempt(self):
        self.assertEqual(m.check(f"자료: https://example.com/a{EM}b/in-conclusion 참고.\n"), [])

    def test_invisible_characters_fail_everywhere(self):
        text = "> 인용\U0000200B\n```\n코드\U000000A0\n```\n`인라인\U00002060`\n"
        self.assertEqual(rules(text), [(1, "invisible"), (3, "invisible"), (5, "invisible")])

    def test_hits_in_quotes_do_not_count(self):
        self.assertEqual(m.check("> 또한 인용이다.\n" * 5 + "**가** **나** **다**\n"), [])

    def test_windows_line_endings(self):
        self.assertEqual(m.check("좋다.\r\n결론적으로\r\n"), [(2, "phrase", "결론적으로")])


class OutputTest(unittest.TestCase):
    def test_snippet_is_short_and_clean(self):
        s = m.snippet("앞 줄이다.\n" + "a\tb\x1b[0m\r" + "x" * 200, 7)
        self.assertLessEqual(len(s), 80)
        self.assertFalse([c for c in s if ord(c) < 32 or 127 <= ord(c) < 160], repr(s))
        self.assertTrue(s.startswith("a b"), repr(s))

    def test_snippet_starts_at_the_hit_and_stops_at_the_line_end(self):
        got = m.check("앞" * 100 + "다음과 같이 쓴다." + "뒤" * 100 + "\n다음과 같다.\n")
        self.assertEqual([g[0] for g in got], [0, 1, 2])
        self.assertEqual(got[1][2], "다음과 같이 쓴다." + "뒤" * 70)  # 80 characters in all
        self.assertEqual(got[2][2], "다음과 같다.")

    def test_repeats_on_one_line_are_one_problem(self):
        self.assertEqual(m.check("결론적으로 그리고 결론적으로\n"), [(1, "phrase", "결론적으로")])
        self.assertEqual(rules(f"a{EM}b{EM}c\n"), [(1, "dash")])


class CliTest(unittest.TestCase):
    def test_file_with_problems(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.md"
            path.write_text(f"좋다.\n결론적으로 {EM} 끝.\n", encoding="utf-8")
            code, out, _ = run(str(path))
        self.assertEqual(code, 1)
        self.assertEqual(out[0], "2:phrase: 결론적으로")
        self.assertTrue(out[1].startswith("2:dash: U+2014 em dash"), out)
        self.assertEqual(out[2:], ["FAIL\t2 problems"])

    def test_clean_file_prints_ok(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.md"
            path.write_text("모델은 열두 개 파일을 4초에 읽는다.\n", encoding="utf-8")
            self.assertEqual(run(str(path))[:2], (0, ["OK"]))

    def test_stdin(self):
        code, out, _ = run("-", data="좋다.\n결론적으로 끝.\n".encode("utf-8"))
        self.assertEqual((code, out), (1, ["2:phrase: 결론적으로", "FAIL\t1 problems"]))
        self.assertEqual(run("-", data="모델은 빠르다.\n".encode("utf-8"))[:2], (0, ["OK"]))
        code, out, _ = run("-", data=b"\xef\xbb\xbf" + "좋다.\n".encode("utf-8"))
        self.assertEqual(out[0], "1:invisible: U+FEFF byte-order mark")

    def test_unreadable_input(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = run(str(Path(d) / "missing.md"))
        self.assertEqual(code, 1)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("FAIL\t"), out)
        code, out, _ = run("-", data=b"\xff\xfe\x00")
        self.assertEqual((code, len(out), out[0][:5]), (1, 1, "FAIL\t"))

    def test_bad_usage_exits_2(self):
        self.assertEqual(run()[0], 2)
        self.assertEqual(run("a.md", "b.md")[0], 2)

    def test_help_is_english(self):
        code, out, _ = run("--help")
        text = "\n".join(out)
        self.assertEqual(code, 0)
        self.assertTrue(text.isascii())
        self.assertIn("<line>:<rule>: <detail>", text)

    def test_style_md_passes_its_own_check(self):
        self.assertEqual(m.check((ROOT / "STYLE.md").read_text(encoding="utf-8")), [])


REPORT = """# Polars or pandas for one machine

Polars ran the measured joins faster [c1], and pandas keeps the widest library support [c2]. Both held on 2026-10-30.

## Polars is faster on joins

The benchmark ran joins on a 10 GB table [c1].

### Method

It used one machine with 32 GB of memory.

## Pandas keeps the ecosystem

Most plotting tools read pandas frames [c2]. A vendor claim of a 30 times gain did not hold [c3].

## Conclusion

Start new pipelines in Polars and keep pandas at the plotting edge [c1, c2].

## Evidence

| id | claim |
|---|---|
| c1 | faster joins |
"""
VERDICTS = [{"id": "c1", "verdict": "survived"}, {"id": "C2", "verdict": "survived"},
            {"id": "c3", "verdict": "refuted"}, {"id": "c4"}]


class ReportKindTest(unittest.TestCase):
    """--kind report: BLUF first, every section up to the conclusion cites, the BLUF and the conclusion cite survivors."""

    def run_report(self, text, claims=VERDICTS, located=("c1", "c2"), view="extracts-2026-10-30.json"):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report-2026-10-30.md"
            path.write_text(text, encoding="utf-8")
            if claims is not None:
                (Path(d) / "claims.json").write_text(json.dumps(claims), encoding="utf-8")
            if view:
                rows = [{"claim": i, "status": "sourced", "id": i, "quotes": [{"file": "a.md", "line": 1, "text": "x"}]}
                        for i in located]
                (Path(d) / view).write_text(json.dumps({"claims": rows}), encoding="utf-8")
            code, out, _ = run("--kind", "report", str(path))
        return code, out

    def test_review_fixes(self):
        korean = REPORT.replace("Both held on 2026-10-30.", "2026-10-30에 확인했다.")
        self.assertEqual(self.problems(korean), [])
        with tempfile.TemporaryDirectory() as d:  # a report not named report-<stem>.md uses extracts.json
            path = Path(d) / "report.md"
            path.write_text(REPORT, encoding="utf-8")
            (Path(d) / "claims.json").write_text(json.dumps(VERDICTS), encoding="utf-8")
            self.assertEqual(run("--kind", "report", str(path))[:2], (1, ["0:view: no extracts.json beside the report; write the report's evidence view", "FAIL\t1 problems"]))
            (Path(d) / "extracts.json").write_text(json.dumps({"claims": [{"id": "c1", "quotes": [{}]}]}), encoding="utf-8")
            self.assertEqual(run("--kind", "report", str(path))[:2], (0, ["OK"]))
        code, out = self.run_report(REPORT, located=(), view="extracts.json")  # dig's view, which cites no ids
        self.assertEqual((code, out[0]), (1, "0:view: no extracts-2026-10-30.json beside the report; write the report's evidence view"))

    def test_bluf_names_its_date(self):
        self.assertEqual(m.report_problems(REPORT.replace(" Both held on 2026-10-30.", ""), {"c1": "survived", "c2": "survived", "c3": "refuted"}),
                         [(3, "bluf", "the BLUF names no as-of date; write it as YYYY-MM-DD")])

    def test_central_claims_it_cites_have_quotes_in_its_view(self):
        claims = [dict(VERDICTS[0], importance="central")] + VERDICTS[1:]
        self.assertEqual(self.run_report(REPORT, claims), (0, ["OK"]))
        code, out = self.run_report(REPORT, claims, located=("c2",))
        self.assertEqual((code, [line.split(":")[:2] for line in out[:-1]]), (1, [["3", "claim"], ["7", "claim"], ["19", "claim"]]))
        self.assertIn("[c1] is central, but extracts-2026-10-30.json gives it no quote", out[0])
        self.assertEqual(self.run_report(REPORT, claims, view="extracts.json"), (0, ["OK"]))  # an older topic's single view
        code, out = self.run_report(REPORT, claims, view=None)
        self.assertEqual((code, out[0]), (1, "0:view: no extracts-2026-10-30.json beside the report; write the report's evidence view"))

    def problems(self, text):
        return [(line, rule) for line, rule, _ in m.report_problems(text, {c["id"].lower(): c.get("verdict", "not checked")
                                                                           for c in VERDICTS})]

    def test_good_report_passes(self):
        self.assertEqual(self.run_report(REPORT), (0, ["OK"]))
        korean = REPORT.replace("## Conclusion", "## 5. 결론: Polars")
        self.assertEqual(self.problems(korean), [])

    def test_bluf_must_be_a_citing_paragraph(self):
        self.assertEqual(self.problems(REPORT.replace("\nPolars ran", "\n- Polars ran")), [(1, "bluf")])
        self.assertEqual(self.problems(REPORT.replace("\nPolars ran", "\n## Answer\nPolars ran")), [(1, "bluf")])
        got = m.report_problems(REPORT.replace(" [c1], and", ", and").replace(" support [c2].", " support."), {"c1": "survived", "c2": "survived", "c3": "refuted"})
        self.assertEqual(got, [(3, "bluf", "the BLUF cites no claim; cite the claims it rests on as [c1]")])
        self.assertEqual(self.problems(REPORT.replace("**", "").replace("\nPolars ran", "\n**Polars** ran")), [])
        self.assertEqual(self.problems(REPORT.split("\n", 1)[1]), [(0, "bluf")])

    def test_sections_up_to_the_conclusion_cite(self):
        text = REPORT.replace("table [c1].", "table.")
        self.assertEqual(m.report_problems(text, {"c1": "survived", "c2": "survived", "c3": "refuted"}),
                         [(5, "section", '"Polars is faster on joins" cites no claim; cite as [c1] or [c1, c2]')])
        self.assertEqual(self.problems(REPORT.replace("[c1, c2].", ".")), [(17, "section")])
        self.assertEqual(self.problems(REPORT.replace("## Conclusion", "## Outlook")),
                         [(0, "section")])

    def test_bluf_and_conclusion_cite_survived_claims_only(self):
        text = REPORT.replace("support [c2].", "support [c4].").replace("[c1, c2].", "[c1, c3].")
        self.assertEqual(m.report_problems(text, {c["id"].lower(): c.get("verdict", "not checked") for c in VERDICTS}),
                         [(3, "claim", "[c4] is not checked; the BLUF may cite survived claims only"),
                          (19, "claim", "[c3] is refuted; the conclusion may cite survived claims only")])

    def test_cited_ids_must_exist(self):
        text = REPORT.replace("did not hold [c3]", "did not hold [c9]") + "\n```\nsee [c8]\n```\n"
        self.assertEqual(m.report_problems(text, {"c1": "survived", "c2": "survived"}),
                         [(15, "claim", "[c9] is not in claims.json")])

    def test_claims_json_is_required(self):
        code, out = self.run_report(REPORT, claims=None)
        self.assertEqual((code, len(out), out[0][:17]), (1, 1, "FAIL\tcannot read "))
        code, out = self.run_report(REPORT, claims={"c1": "survived"})
        self.assertEqual((code, out[0][:17]), (1, "FAIL\tcannot read "))
        code, out, _ = run("--kind", "report", "-", data=REPORT.encode("utf-8"))
        self.assertEqual((code, out), (1, ["FAIL\t--kind report reads the claims.json beside the report; pass the file, not -"]))

    def test_style_rules_still_apply(self):
        code, out = self.run_report(REPORT.replace("faster [c1]", "faster [c1] \U00002014 by far"))
        self.assertEqual((code, out[0][:7]), (1, "3:dash:"))


BRIEF = """# 위젯 엔진 30일 동향

위젯 엔진 2가 나왔고 반응이 좋다.

출처: Hacker News 1건, Reddit 실패(http 503), YouTube 건너뜀(yt-dlp 없음)

## 위젯 엔진 2 출시

> "Works well for me, and the new scheduler halves latency."

amy, Hacker News: https://news.ycombinator.com/item?id=12
"""
RESULT = {"lanes": {"hn": {"status": "ok"}, "reddit": {"status": "failed: http 503"}, "youtube": {"status": "skipped"}},
          "items": [{"url": "https://example.com/we2", "links": {"hn": "https://news.ycombinator.com/item?id=1"},
                     "title": "Widget engine 2 is out", "snippet": "A rewrite of the   scheduler.",
                     "comments": [{"author": "amy", "text": "Works well for me, and the new scheduler halves latency.",
                                   "url": "https://news.ycombinator.com/item?id=12"}]},
                    {"url": "https://example.com/other", "links": {"hn": "https://news.ycombinator.com/item?id=2"},
                     "title": "Other story", "snippet": "", "comments": []}],
          "clusters": [{"id": "k1", "items": ["hn:1"]}]}


class PulseKindTest(unittest.TestCase):
    """--kind pulse: one line names every lane the run listed; quotes are verbatim and linked."""

    def problems(self, text, result=RESULT):
        return [(line, rule) for line, rule, _ in m.pulse_problems(text, result)]

    def test_good_brief_passes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "2026-10-30.md"
            path.write_text(BRIEF, encoding="utf-8")
            (Path(d) / "2026-10-30.json").write_text(json.dumps(RESULT), encoding="utf-8")
            self.assertEqual(run("--kind", "pulse", str(path))[:2], (0, ["OK"]))

    def test_one_line_names_every_lane(self):
        self.assertEqual(m.pulse_problems(BRIEF.replace(", Reddit 실패(http 503)", ""), RESULT),
                         [(0, "lanes", "no line names every lane the run listed; name Reddit on the coverage line")])
        self.assertEqual(self.problems(BRIEF.replace("출처: Hacker News 1건, ", "출처: ")), [(0, "lanes")])

    def test_quotes_are_verbatim(self):
        self.assertEqual(self.problems(BRIEF.replace("halves latency", "cuts latency in half")), [(9, "quote")])
        self.assertEqual(self.problems(BRIEF.replace("for me, and the new", "for me ... the new")), [])
        self.assertEqual(self.problems(BRIEF.replace("Works well for me, and the new", "the new ... Works well")), [(9, "quote")])
        self.assertEqual(self.problems(BRIEF.replace("for me, and", "for me,\n>   and")), [])
        snippet = BRIEF.replace('"Works well for me, and the new scheduler halves latency."', "A rewrite of the scheduler")
        self.assertEqual(self.problems(snippet.replace("item?id=12", "item?id=1")), [])
        self.assertEqual(self.problems(BRIEF + "\n```\n> not checked\n```\n"), [])

    def test_quotes_carry_their_link(self):
        self.assertEqual(self.problems(BRIEF.replace("item?id=12", "item?id=2")), [(9, "quote")])  # another item's link
        self.assertEqual(self.problems(BRIEF.replace("Hacker News: https://news.ycombinator.com/item?id=12", "Hacker News")),
                         [(9, "quote")])

    def test_a_result_with_clusters_needs_a_quote(self):
        no_quote = BRIEF.split("\n> ")[0]
        self.assertEqual(self.problems(no_quote), [(0, "quote")])
        self.assertEqual(self.problems(no_quote, {**RESULT, "clusters": []}), [])

    def test_the_result_is_required(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "2026-10-30.md"
            path.write_text(BRIEF, encoding="utf-8")
            code, out, _ = run("--kind", "pulse", str(path))
        self.assertEqual((code, out[0][:17]), (1, "FAIL\tcannot read "))
        code, out, _ = run("--kind", "pulse", "-", data=BRIEF.encode("utf-8"))
        self.assertEqual((code, out), (1, ["FAIL\t--kind pulse reads the pulse.py result beside the brief; pass the file, not -"]))


class ModelsKindTest(unittest.TestCase):
    """--kind models: every <path>:<line> the deliverable cites names a file of its folder and a line that file has."""

    def test_locations_name_files_and_lines(self):
        with tempfile.TemporaryDirectory() as d:
            topic = Path(d)
            (topic / "sources").mkdir()
            (topic / "sources" / "board.tsv").write_bytes(b"# board\nRank\tModel\n1\tacme/a\n")
            (topic / "sources" / "card.md").write_bytes(b"one\ftwo\nthree")  # a form feed is not a line break
            path = topic / "models-2026-10-31.md"
            good = "| acme/a | 4.0 [1] |\n\n[1] sources/board.tsv:3\n[2] sources/card.md:2, sources/board.tsv:1-3\n"
            path.write_text(good, encoding="utf-8")
            self.assertEqual(run("--kind", "models", str(path))[:2], (0, ["OK"]))
            bad = good + "[3] sources/board.tsv:4\n[4] sources/card.md:0 and models/hub/acme--a.json:7\n[5] sources/board.tsv:2-9\n"
            self.assertEqual(m.models_problems(bad, topic),
                             [(5, "location", "sources/board.tsv:4: the file has 3 lines"),
                              (6, "location", "sources/card.md:0: the file has 2 lines"),
                              (6, "location", "models/hub/acme--a.json:7: no such file in the topic folder"),
                              (7, "location", "sources/board.tsv:2-9: the file has 3 lines")])
            path.write_text(bad, encoding="utf-8")
            code, out, _ = run("--kind", "models", str(path))
            self.assertEqual((code, out[-1]), (1, "FAIL\t4 problems"))
        code, out, _ = run("--kind", "models", "-", data=good.encode("utf-8"))
        self.assertEqual((code, out), (1, ["FAIL\t--kind models reads the files the deliverable cites; pass the file, not -"]))
