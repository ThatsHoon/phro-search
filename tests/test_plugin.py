import ast, json, re, subprocess, sys, unittest
from tests._load import ROOT

SKILL = ROOT / "skills/search/SKILL.md"
REFS = ROOT / "skills/search/references"
SCRIPTS = ROOT / "scripts"
MODES = ("dig", "report", "pulse", "docs", "models", "watch")
KO = re.compile(r"[\U00001100-\U000011ff\U00003130-\U0000318f\U0000ac00-\U0000d7a3]")
JA = re.compile(r"[\U00003040-\U000030ff\U000031f0-\U000031ff\U0000ff66-\U0000ff9f]")
KO_JA = re.compile(r"[\U00001100-\U000011ff\U00003130-\U0000318f\U0000ac00-\U0000d7a3\U00003040-\U000030ff\U000031f0-\U000031ff\U0000ff66-\U0000ff9f]")
TELLS = re.compile(r"[\U00002013\U00002014\U00002600-\U000027bf\U00002b50\U0000fe0f\U0001f300-\U0001faff]")
INVISIBLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\U0000061c\U0000200b-\U0000200f\U0000202a-\U0000202e"
                       r"\U00002060-\U00002064\U00002066-\U00002069\U0000feff]")
# Scripts run standalone, so they carry copies of shared code: (names, the original, scripts that must carry it).
SHARED = ((("egress_terms", "_edge", "egress_hit"), "hooks/egress.py", {"chain.py", "fetch.py", "models.py", "pulse.py", "watch.py"}),
          (("_CTRL", "_QUOTES", "clean"), "scripts/chain.py", set()),
          (("NAMES",), "scripts/pulse.py", {"check.py"}),
          (("OA_RANKS", "oa_kind", "oa_order"), "scripts/chain.py", {"fetch.py"}))


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def docs():
    """SKILL.md and the references written so far, as (name, text)."""
    paths = ([SKILL] if SKILL.exists() else []) + sorted(REFS.glob("*.md"))
    return [(p.name, read(p)) for p in paths]


def split_skill(text):
    """The one-line frontmatter description, and the file without that line."""
    end = text.index("\n---\n", 4)
    front, rest = text[:end], text[end:]
    m = re.search(r"^description: *(.*)$", front, re.M)
    return m.group(1), front[:m.start()] + front[m.end():] + rest


def doc_commands(text):
    """(script, subcommands, flags) for each script command shown in code spans or code blocks."""
    spans = [line for block in re.findall(r"```[^\n]*\n(.*?)```", text, re.S) for line in block.split("\n")]
    spans += re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S))
    found = []
    for span in spans:
        m = re.search(r"([\w-]+)\.py\b(.*)", span.replace("\\|", "|"))
        if not m:
            continue
        tokens = re.split(r"\s+(?:\||&&|;|>)\s+", m.group(2))[0].split()
        subs = tokens[0].split("|") if tokens and re.fullmatch(r"[a-z][\w-]*(\|[a-z][\w-]*)*", tokens[0]) else []
        flags = re.findall(r"--[a-z][\w-]*", " ".join(tokens))
        if subs or flags:
            found.append((m.group(1) + ".py", subs, flags))
    return found


def help_info(script):
    """Subcommands of a script and the --help text of the script and every subcommand."""
    def run(*args):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args, "--help"],
                           capture_output=True, encoding="utf-8", errors="replace", timeout=60)
        return r.stdout + r.stderr
    top = run()
    m = re.search(r"\{([\w,-]+)\}", top)
    subs = m.group(1).split(",") if m else []
    return subs, top + "".join(run(s) for s in subs)


def shared(path, names):
    """Source text of the top-level functions and assignments of a file that are called one of names."""
    text = read(path)
    out = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        else:
            name = getattr(node, "name", None)
        if name in names:
            out[name] = ast.get_source_segment(text, node)
    return out


class PluginTest(unittest.TestCase):
    def test_version_sync(self):
        version = json.loads(read(ROOT / ".claude-plugin/plugin.json"))["version"]
        for path in sorted(SCRIPTS.glob("*.py")):
            m = re.search(r'^VERSION = "([^"]+)"', read(path), re.M)
            self.assertEqual(m and m.group(1), version, path.name)

    def test_named_paths_exist(self):
        texts = docs() + [(p.name, read(p)) for p in sorted(ROOT.glob("hooks/*.json"))]
        missing = [(name, rel) for name, text in texts
                   for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text)
                   if not (ROOT / rel.rstrip(".")).exists()]
        self.assertEqual(missing, [])

    def test_named_references_exist(self):
        missing = [(name, ref) for name, text in docs()
                   for ref in re.findall(r"references/([\w-]+\.md)", text) if not (REFS / ref).exists()]
        self.assertEqual(missing, [])

    def test_documented_commands_match_help(self):
        seen = {}
        for name, text in docs():
            for script, subs, flags in doc_commands(text):
                with self.subTest(doc=name, script=script):
                    self.assertTrue((SCRIPTS / script).exists(), "no such script")
                    if script not in seen:
                        seen[script] = help_info(script)
                    known, help_text = seen[script]
                    self.assertEqual([s for s in subs if s not in known], [])
                    self.assertEqual([f for f in flags if not re.search(re.escape(f) + r"(?![\w-])", help_text)], [])

    def test_every_subcommand_is_documented(self):
        named = {}
        for _, text in docs():
            for script, subs, _ in doc_commands(text):
                named.setdefault(script, set()).update(subs)
        for path in sorted(SCRIPTS.glob("*.py")):
            r = subprocess.run([sys.executable, "-I", str(path), "--help"], capture_output=True, encoding="utf-8",
                               errors="replace", timeout=60)
            m = re.search(r"^usage: \S+ \[-h\] \{([\w,-]+)\} \.\.\.", r.stdout, re.M)
            with self.subTest(script=path.name):
                self.assertEqual(sorted(set(m.group(1).split(",") if m else []) - named.get(path.name, set())), [])

    def test_dig_disconfirm_searcher(self):
        method = re.search(r"^Your method: (.*)$", read(REFS / "briefs.md"), re.M).group(1)
        self.assertIn("find criticism, failed or partial replications, negative results, errata and corrections of "
                      "<work or claim>", method)
        dig = read(REFS / "dig.md")
        self.assertIn("ceiling 10 searcher calls", dig)
        self.assertRegex(dig, r"(?i)disconfirm searcher")

    def test_standards_section(self):
        report = read(REFS / "report.md")
        m = re.search(r"^## Standards\n(.*?)(?=^## )", report, re.M | re.S)
        self.assertTrue(m, "report.md has no Standards section")
        section = m.group(1)
        for word in ("OGC", "ISO/TC 211", "TC 204", "OpenDRIVE", "OpenSCENARIO", "REP", "IETF", "W3C", "obsoleted by",
                     "errata", "edition", "withdrawn", "normative", "informative", "superseded", "draft", "central claim",
                     "catalog page", "IEC", "IEEE", "browser"):
            self.assertIn(word, section)
        self.assertRegex(read(REFS / "dig.md"), r"Standards section of `references/report\.md`")
        homes = [name for name, text in docs() if re.search(r"(?i)\bnormative\b", text)]
        self.assertEqual(homes, ["report.md"])  # one home for the rule

    def test_report_decision_template(self):
        report = read(REFS / "report.md")
        before = re.search(r"^## Before spawning\n(.*?)(?=^## )", report, re.M | re.S).group(1)
        self.assertNotIn("measurements) when the question is contested", before)  # every choice, not only contested ones
        self.assertRegex(before, r"choice between options[^\n]*independent viewpoint")
        self.assertRegex(before, r"\| a choice between options on criteria \| 4 or 5")
        self.assertIn('"PLAN: report; 5 researchers, 1 support reader, up to 30 verifier calls; ceiling 38 agent calls"', before)
        write = re.search(r"^## Write\n(.*?)(?=^## Deliver)", report, re.M | re.S).group(1)
        for words in ("decision table", "When another option wins", "What would change this answer", "1 to 3",
                      "unknown", "unverified", "entities", "key questions", "landscape", "standards"):
            self.assertIn(words.lower(), write.lower())
        homes = [name for name, text in docs() if re.search(r"(?i)what would change this answer", text)]
        self.assertEqual(homes, ["report.md"])  # one home for the rule

    def test_single_mode_formats_live_in_their_mode(self):
        formats = read(REFS / "formats.md")
        heads = re.findall(r"^## (.+)$", re.sub(r"```.*?```", "", formats, flags=re.S), re.M)
        self.assertEqual(heads, ["map.md", "Labels and marks", "File names and locations", "log.md", "sources/index.tsv",
                                 "extracts.json"])
        homes = {"pulse.md": ('"subqueries"', "pulse/<stem>-evidence.md", "- run: pulse/<stem>.json"),
                 "models.md": ("models/shortlist.json", "models/hub/<org>--<name>.json", "line 1 `# board="),
                 "watch.md": ("one feed per line: kind, name", "the item URLs already seen"),
                 "report.md": ('"votes": [', "votes: <n> central claims", "never reused in a topic")}
        for ref, marks in homes.items():
            for mark in marks:
                with self.subTest(ref=ref, mark=mark):
                    self.assertEqual([name for name, text in docs() if mark in text], [ref])
        pointers = [(name, line) for name, text in docs() if name != "SKILL.md" for line in text.splitlines()
                    if re.search(r"(claims\.json|plan\.json|notes/)[^\n]*`references/formats\.md`", line)]
        self.assertEqual(pointers, [])

    def test_check_loop_on_a_saved_file(self):
        rules = read(SKILL).split("## Rules for every mode", 1)[1]
        self.assertRegex(" ".join(rules.split()), r"(?i)write the whole reply[^\n]*to a file[^\n]*`check\.py`[^\n]*edit only the "
                                                  r"spans it flags")
        texts = docs() + [("STYLE.md", read(ROOT / "STYLE.md"))] + [(p.name, read(p)) for p in sorted((ROOT / "agents").glob("*.md"))]
        self.assertEqual([name for name, text in texts if re.search(r"(?i)flagged spot|flagged span|spans it flags|until it prints|exact reply", text)],
                         ["SKILL.md"])  # one home for the loop

    def test_intake_reads_related_topics_only(self):
        step = re.search(r"^1\. Harvest context silently:(.*)$", read(SKILL), re.M).group(1)
        self.assertIn("`*/map.md`", step)
        self.assertIn("`^(brief|feedback):`", step)
        self.assertNotIn("`*/log.md`", step)  # not every topic's log
        self.assertRegex(step, r"related")
        self.assertEqual([n for n, t in docs() if "^(brief|feedback):" in t], ["SKILL.md"])
        self.assertRegex(read(REFS / "intake.md"), r"^# Intake\n")
        for p in sorted(REFS.glob("*.md")):
            self.assertTrue(read(p).startswith("# "), p.name)

    def test_plan_line_is_literal(self):
        step = re.search(r"^4\. (.*)$", read(SKILL).split("## Routing", 1)[1], re.M).group(1)
        self.assertIn("`PLAN: <mode>; <rounds, agents or steps>; ceiling <n> <calls>", step)
        self.assertRegex(step, r"English whatever the user's language")
        self.assertRegex(step, r"first line")
        lines = [(name, line) for name, text in docs() for line in text.splitlines() if "Plan line" in line]
        self.assertEqual(sorted(name for name, _ in lines), ["dig.md", "docs.md", "models.md", "pulse.md", "report.md"])
        for name, line in lines:
            with self.subTest(ref=name):
                mode = name[:-3]
                self.assertRegex(line, rf'Plan line: "PLAN: {mode}; [^";]+; ceiling \d+ [a-z ]+calls"')

    def test_default_scope_is_english(self):
        row = next(l for l in read(REFS / "intake.md").splitlines() if l.startswith("| Scope |"))
        default = row.rstrip(" |").rsplit("|", 1)[1]
        self.assertIn("sources in English", default)
        self.assertRegex(default, r"the user's language too only when the topic is specific to that language's region")
        self.assertNotIn("English and the user's language", default)

    def test_doc_command_parser(self):
        sample = ("Run `python -I ${CLAUDE_PLUGIN_ROOT}/scripts/models.py snapshot <topic> --board asr`.\n"
                  "| `chain.py find\\|refs` | `fetch.py` alone |\n"
                  "```\npulse.py <topic> --days 7 | head -n 3\n```\n")
        self.assertEqual(doc_commands(sample), [
            ("pulse.py", [], ["--days"]),
            ("models.py", ["snapshot"], ["--board"]),
            ("chain.py", ["find", "refs"], []),
        ])

    def test_size_caps(self):
        for p in sorted(REFS.glob("*.md")):
            self.assertLess(len(read(p).splitlines()), 200, p.name)
        if not SKILL.exists():
            self.skipTest("SKILL.md comes in T1.7")
        self.assertLess(len(read(SKILL).splitlines()), 150)

    def test_description(self):
        if not SKILL.exists():
            self.skipTest("SKILL.md comes in T1.7")
        desc = split_skill(read(SKILL))[0]
        self.assertLess(len(desc), 600)
        self.assertEqual([m for m in MODES if not re.search(rf"\b{m}\b", desc)], [])
        korean = [q for q in re.findall(r'"([^"]+)"', desc) if KO.search(q)]
        self.assertTrue(1 <= len(korean) <= 6 and all(len(q) <= 20 for q in korean), korean)
        self.assertIsNone(KO.search(re.sub(r'"[^"]+"', "", desc)), "Hangul outside the quoted trigger phrases")
        self.assertIsNone(JA.search(desc))

    def test_english_where_the_model_reads(self):
        for name, text in docs():
            body = split_skill(text)[1] if name == "SKILL.md" else text
            self.assertIsNone(KO_JA.search(body), name)
        for path in sorted(SCRIPTS.glob("*.py")):
            lines = [l.strip() for l in read(path).splitlines()
                     if KO_JA.search(l) and re.search(r"print\(|exit\(|help=|description=|Error\(", l)]
            self.assertEqual(lines, [], path.name)
            self.assertIsNone(KO_JA.search(help_info(path.name)[1]), path.name)

    def test_no_dashes_or_emoji(self):
        bad = [str(p.relative_to(ROOT)) for p in sorted(ROOT.rglob("*"))
               if p.is_file() and p.suffix in (".md", ".py", ".json")
               and not {".git", "tests", "__pycache__"} & set(p.relative_to(ROOT).parts)
               and TELLS.search(read(p))]
        self.assertEqual(bad, [])

    def test_no_invisible_characters(self):
        # Tests too: a literal bidi or zero-width character hides what code does. Write escapes instead.
        bad = [str(p.relative_to(ROOT)) for p in sorted(ROOT.rglob("*"))
               if p.is_file() and p.suffix in (".md", ".py", ".json")
               and not {".git", "__pycache__"} & set(p.relative_to(ROOT).parts) and INVISIBLE.search(read(p))]
        self.assertEqual(bad, [])

    def test_agents_isolate_tools(self):
        want = {"web-gatherer": {"WebSearch", "WebFetch", "ToolSearch"}, "verifier": {"WebSearch", "WebFetch", "ToolSearch"},
                "local-reader": {"Read", "Grep", "Glob"}}
        found = {}
        for path in sorted((ROOT / "agents").glob("*.md")):
            text = read(path)
            front = dict(re.findall(r"^([A-Za-z]+): *(.*)$", text[4:text.index("\n---\n", 4)], re.M))
            found[front["name"]] = front
            with self.subTest(agent=path.name):
                self.assertEqual(path.stem, front["name"])
                self.assertEqual({x.strip() for x in front["tools"].split(",")}, want[front["name"]])
                self.assertEqual((front["model"], front["omitClaudeMd"]), ("sonnet", "true"))
                self.assertTrue(front["maxTurns"].isdecimal())
                self.assertIn("Internal to the phro-search search skill", front["description"])
        self.assertEqual(set(found), set(want))
        self.assertEqual(found["verifier"].get("effort"), "high")
        named = {n for _, text in docs() for n in re.findall(r"phro-search:([a-z][\w-]*)", text)}
        self.assertEqual(named - set(found), {"search"} & named)  # phro-search:search is the skill itself

    def test_shared_code_copies_match(self):
        for names, original, needed in SHARED:
            want = shared(ROOT / original, names)
            self.assertEqual(sorted(want), sorted(names), original)
            copies = {p.name: got for p in sorted(SCRIPTS.glob("*.py")) if (got := shared(p, names))}
            self.assertLessEqual(needed, set(copies))
            for name, got in copies.items():
                with self.subTest(copy=name, of=original):
                    self.assertEqual(got, want)
