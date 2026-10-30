import json, re, subprocess, sys, unittest
from tests._load import ROOT

SKILL = ROOT / "skills/search/SKILL.md"
REFS = ROOT / "skills/search/references"
SCRIPTS = ROOT / "scripts"
MODES = ("dig", "report", "pulse", "docs", "models", "watch")
KO = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣]")
JA = re.compile(r"[぀-ヿㇰ-ㇿｦ-ﾟ]")
KO_JA = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣぀-ヿㇰ-ㇿｦ-ﾟ]")
TELLS = re.compile(r"[–—☀-➿⭐️\U0001f300-\U0001faff]")


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
