"""Lint a Markdown or plain-text deliverable for AI writing tells and print each spot.

usage: check.py [--kind report|pulse|models] <file>      (a lone - reads standard input)
output, one line per problem:  <line>:<rule>: <detail>   (line 0 for whole-document counts)
then  FAIL<TAB><n> problems  and exit 1, or  OK  and exit 0.
rules: phrase, symbol, dash, invisible: one hit fails.
       density, per-doc, opener, bold: fail over a limit; a line 0 summary, then each hit with a snippet.
Fenced code, quote lines (">"), inline code and URLs are not checked, except for invisible characters; a no-break
space (U+00A0, U+202F) or a soft hyphen in a quote line is allowed, since a quote keeps its source's characters.
--kind report also checks a report's structure against the claims.json and the evidence view beside it
       (extracts-<stem>.json for report-<stem>.md, else extracts.json):
       bluf: the title is followed by one paragraph, it cites a claim as [c1] or [c1, c2], and it names its
             as-of date as YYYY-MM-DD;
       section: a conclusion section exists (a ## heading that starts with the word for conclusion),
                and it and every ## section before it cite a claim;
       claim: every cited id is in claims.json, every central claim cited has a quote in the view, and the
              BLUF and the conclusion cite survived claims only;
       table: in a Markdown table above the evidence table (the title, the BLUF and every ## section up to
              and including the conclusion), every cell but the header row and the first column cites a
              claim or says unknown (or the word for unknown in the report's language);
       view: the evidence view exists.
--kind pulse also checks a pulse brief against the pulse.py result (<stem>.json) beside it:
       lanes: one line names every lane the run listed (Hacker News, Reddit, GitHub, arXiv, YouTube);
       quote: every quote (> lines) is found verbatim in the result's titles, snippets or comments ("..." may
              join pieces kept in order), with the quoted item's or comment's link on the line after it;
              a result with clusters needs at least one quote.
--kind models also checks a model choice against the topic folder it sits in:
       location: every <path>:<line> or <path>:<first>-<last> (path under sources/ or models/) names a file
                 in the folder and a line that file has, counted as grep -n counts.
"""
import argparse, itertools, json, re, sys
from pathlib import Path

VERSION = "0.4.0"

# One hit fails. English entries match whole words; Korean entries match anywhere in the text.
HARD_PHRASES = [
    "Generated with", "Co-Authored-By", "Written by Claude", "AI-generated", "as an AI", "ai_summary",
    "Claude가 작성", "AI가 작성", "AI 요약", "언어 모델로서",
    "알아보겠습니다", "살펴보겠습니다", "알아봅시다", "살펴봅시다", "소개해 드리겠습니다", "소개하겠습니다",
    "결론적으로", "요약하자면", "정리하자면", "귀추가 주목", "앞으로가 기대",
    "도움이 되셨으면", "궁금한 점이 있으시면", "언제든 말씀해", "좋은 질문입니다", "좋은 질문이네요",
    "혁신적", "획기적", "게임 체인저", "게임체인저", "판도를 바꾸", "패러다임 전환", "새로운 지평",
    "되어지", "되어진",
    "in conclusion", "in summary", "to summarize", "to sum up", "hope this helps", "let me know if",
    "important to note", "worth noting", "delve", "delves", "delving", "game-changer", "game changer",
    "groundbreaking", "revolutionary", "cutting-edge", "paradigm shift", "ever-evolving",
]
# Emoji and decorative symbols, as code point ranges (written as escapes on purpose).
DECOR = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U000025A0-\U000025FF\U00002B00-\U00002BFF\U0000FE0F]+")
DASHES = {"\U00002014": "em dash", "\U00002013": "en dash", "\U00002015": "horizontal bar"}
INVISIBLE = {0x200B: "zero-width space", 0x200C: "zero-width non-joiner", 0x200D: "zero-width joiner",
             0x2060: "word joiner", 0xFEFF: "byte-order mark", 0x00AD: "soft hyphen", 0x00A0: "no-break space",
             0x202F: "narrow no-break space"}  # hidden marks and copy traces
QUOTE_OK = {0x00A0, 0x202F, 0x00AD}  # allowed inside a quote line, which keeps its source's characters
HINT = "use a comma, a colon or parentheses"
# Natural words that read machine-made only when they pile up.
DENSITY = {  # name: (phrases, max per 1,000 body characters)
    "translationese": (["를 통해", "을 통해", "에 대해", "에 대한", "에 있어", "함으로써"], 4.0),
    "empty modifiers": (["다양한", "효과적", "효율적", "강력한", "원활한", "최적의", "중요한 역할"], 2.0),
}
PER_DOC = {  # name: (regex, max per document)
    "signpost sentence": (r"다음과 같", 1),
    "rhetorical question": (r"[^.!?\n]{0,40}까요?\?", 1),  # the lead-in is only for the snippet
    "arrows": (r"\U00002192|\U000021D2|->", 2),
}
OPENERS = ["또한", "특히", "이처럼", "따라서", "즉"]  # at most MAX_OPENER sentences per document start with each
MAX_OPENER = 3
MAX_BOLD, BOLD_STEP = 3, 1500  # bold spans per document, plus one per BOLD_STEP body characters
# Where a sentence can start: a line (after a list or heading marker), or after . ! ? and spaces.
SENTENCE = r"(?:^[ \t]*(?:(?:[-*+]|\d+[.)]|#+)[ \t]+)?|(?<=[.!?])[ \t]+)"
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?(?:^[ \t]*\1[`~]*[ \t]*$|\Z)", re.M | re.S)  # to its closing fence or the end
QUOTE = re.compile(r"^[ \t]*>.*$", re.M)
INLINE = re.compile(r"(`+).*?\1|https?://\S+")  # inline code and URLs
# --kind report. A conclusion heading starts with one of these words, after any numbering.
CONCLUSION = ("conclusion", "결론", "맺음", "結論", "まとめ")
CITE = re.compile(r"\[\s*(c\d+(?:\s*,\s*c\d+)*)\s*\]", re.I)  # [c3] or [c3, c7]
UNKNOWN = re.compile("(?<![A-Za-z])unknown(?![A-Za-z])|\uc54c \uc218 \uc5c6\uc74c|\uc54c\ub824\uc9c0\uc9c0 \uc54a\uc74c|\ubd88\uba85|\u4e0d\u660e|\u672a\u77e5",
                     re.I)  # unknown, and the words for it in Korean, Japanese and Chinese
TABLE_RULE = re.compile(r"[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")  # |---|:--:|
NOT_PROSE = re.compile(r"[ \t]*(?:[-*+](?=[ \t])|\d+[.)](?=[ \t])|[>|#])")  # a list, quote, table or heading line


def pattern(words):
    """One regex for a phrase list. A Latin edge may not touch another Latin letter: "as an AI" misses "as an aid"."""
    def edge(ch, look):
        return look if "a" <= ch.lower() <= "z" else ""
    return re.compile("|".join(edge(w[0], "(?<![A-Za-z])") + re.escape(w) + edge(w[-1], "(?![A-Za-z])")
                              for w in words), re.I)


def scope(raw):
    """The writer's own prose: fenced code, quote lines, inline code and URLs are blanked, line breaks stay."""
    raw = FENCE.sub(lambda m: "\n" * m.group().count("\n"), raw)
    return INLINE.sub(" ", QUOTE.sub("", raw))


def snippet(text, pos):
    """The rest of the line from pos: at most 80 characters, control characters removed."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", text[pos:pos + 80].split("\n")[0]).strip()


def check(raw):
    """Problems in a document as unique (line, rule, detail) tuples, grouped by rule."""
    raw = raw.replace("\r\n", "\n")
    text = scope(raw)
    found = []

    def add(src, pos, rule, detail):
        found.append((src.count("\n", 0, pos) + 1, rule, detail))

    def over(rule, starts, cap, title):  # a count over its cap: a line 0 summary, then every hit
        if len(starts) > cap:
            found.append((0, rule, title))
            for pos in starts:
                add(text, pos, rule, snippet(text, pos))

    for m in pattern(HARD_PHRASES).finditer(text):
        add(text, m.start(), "phrase", m.group())
    for m in DECOR.finditer(text):
        codes = " ".join(f"U+{ord(c):04X}" for c in m.group())
        add(text, m.start(), "symbol", f"{codes}, remove it or {HINT}")
    for m in re.finditer("[" + "".join(DASHES) + "]", text):
        add(text, m.start(), "dash", f"U+{ord(m.group()):04X} {DASHES[m.group()]}, {HINT}")
    unfenced = FENCE.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), raw)  # fences blanked, positions kept
    quoted = [(q.start(), q.end()) for q in QUOTE.finditer(unfenced)]
    for m in re.finditer("[" + "".join(map(chr, INVISIBLE)) + "]", raw):
        if ord(m.group()) in QUOTE_OK and any(a <= m.start() < b for a, b in quoted):
            continue
        add(raw, m.start(), "invisible", f"U+{ord(m.group()):04X} {INVISIBLE[ord(m.group())]}")
    body = len(re.sub(r"\s", "", text))
    per = max(body / 1000, 1)
    for name, (words, limit) in DENSITY.items():
        starts = [m.start() for m in pattern(words).finditer(text)]
        over("density", starts, limit * per,
             f"{name}: {len(starts)} hits, {len(starts) / per:.1f} per 1,000 characters (limit {limit})")
    for name, (rx, limit) in PER_DOC.items():
        starts = [m.start() for m in re.finditer(rx, text)]
        over("per-doc", starts, limit, f"{name}: {len(starts)} hits (limit {limit})")
    for w in OPENERS:
        starts = [m.start(1) for m in re.finditer(SENTENCE + rf"({w})(?=[\s,])", text, re.M)]
        over("opener", starts, MAX_OPENER, f'"{w}" starts {len(starts)} sentences (limit {MAX_OPENER})')
    starts = [m.start() for m in re.finditer(r"\*\*[^\n]+?\*\*|__[^\n]+?__", text)]
    cap = MAX_BOLD + body // BOLD_STEP
    over("bold", starts, cap, f"{len(starts)} bold spans (limit {cap})")
    return list(dict.fromkeys(found))


def cells(row):
    """A table row's cells, stripped; an escaped pipe stays inside its cell."""
    row = row.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def table_problems(block):
    """Each data cell of a Markdown table in block, past the first column, that neither cites a claim nor says unknown."""
    found, i = [], 0
    while i + 1 < len(block):
        head, rule = block[i][1], block[i + 1][1]
        if not ("|" in head and "|" in rule and TABLE_RULE.match(rule)):
            i += 1
            continue
        names, i = cells(head), i + 2
        while i < len(block) and "|" in block[i][1]:
            n, row = block[i]
            for k, cell in enumerate(cells(row)[1:], 1):
                if not CITE.search(cell) and not UNKNOWN.search(cell):
                    name = names[k] if k < len(names) and names[k] else f"column {k + 1}"
                    found.append((n, "table", f'{snippet(name, 0)}: "{snippet(cell, 0)}" cites no claim; '
                                              "cite it as [c1] or write unknown"))
            i += 1
    return found


def report_problems(raw, verdicts, unlocated=frozenset(), view="its evidence view"):
    """A report's structure as (line, rule, detail) tuples; verdicts maps each claims.json id, lowercase, to its verdict,
    and unlocated holds the central ids that the evidence view (named view) gives no quote."""
    lines = FENCE.sub(lambda m: "\n" * m.group().count("\n"), raw.replace("\r\n", "\n")).split("\n")
    parts = [[0, 0, "", []]]  # heading line, level (0 before any heading), heading, body as (line, text) pairs
    for n, line in enumerate(lines, 1):
        h = re.match(r"(#{1,2})[ \t]+(.*)", line)
        if h:
            parts.append([n, len(h.group(1)), h.group(2).strip(), []])
        else:
            parts[-1][3].append((n, line))

    def cites(block):
        return [(n, c.strip().lower()) for n, t in block for m in CITE.finditer(t) for c in m.group(1).split(",")]

    found = [(n, "claim", f"[{c}] is not in claims.json") for p in parts for n, c in cites(p[3]) if c not in verdicts]
    found += [(n, "claim", f"[{c}] is central, but {view} gives it no quote") for p in parts for n, c in cites(p[3])
              if c in unlocated]
    title = next((p for p in parts if p[1] == 1), None)
    if title is None:
        return found + [(0, "bluf", "no title line (# title)")]
    body = title[3]
    start = next((i for i, (_, t) in enumerate(body) if t.strip()), len(body))
    bluf = list(itertools.takewhile(lambda x: x[1].strip(), body[start:]))
    if not bluf or NOT_PROSE.match(bluf[0][1]):
        found.append((title[0], "bluf", "the title must be followed by one paragraph that answers the question"))
        bluf = []
    else:
        if not cites(bluf):
            found.append((bluf[0][0], "bluf", "the BLUF cites no claim; cite the claims it rests on as [c1]"))
        if not re.search(r"(?<!\d)\d{4}-\d\d-\d\d(?!\d)", " ".join(t for _, t in bluf)):  # a particle may follow it
            found.append((bluf[0][0], "bluf", "the BLUF names no as-of date; write it as YYYY-MM-DD"))
    sections = [p for p in parts if p[1] == 2]
    end = next((k for k, p in enumerate(sections)
                if re.sub(r"^[\d.)\s]+", "", p[2]).lower().startswith(CONCLUSION)), None)
    if end is None:
        return found + [(0, "section", "no conclusion: start one ## heading with the word for conclusion")]
    for p in sections[:end + 1]:
        if not cites(p[3]):
            found.append((p[0], "section", f'"{snippet(p[2], 0)}" cites no claim; cite as [c1] or [c1, c2]'))
    for p in parts[:parts.index(sections[end]) + 1]:  # the evidence table and what follows it are exempt
        found += table_problems(p[3])
    for where, block in (("BLUF", bluf), ("conclusion", sections[end][3])):
        for n, c in cites(block):
            if verdicts.get(c, "survived") != "survived":
                found.append((n, "claim", f"[{c}] is {verdicts[c]}; the {where} may cite survived claims only"))
    return found


# --kind pulse. pulse.py's lane names:
NAMES = {"hn": "Hacker News", "reddit": "Reddit", "github": "GitHub", "arxiv": "arXiv", "youtube": "YouTube"}
LINK = re.compile(r"https?://[^\s)>\]]+")
ELLIPSIS = re.compile(r"\.\.\.|\U00002026")
WRAP = "\"'\U0000201c\U0000201d\U00002018\U00002019"  # quote marks around a whole quote


def in_order(pieces, text):
    at = 0
    for p in pieces:
        at = text.find(p, at)
        if at < 0:
            return False
        at += len(p)
    return True


def pulse_problems(raw, result):
    """A pulse brief's structure as (line, rule, detail) tuples, against the pulse.py result beside it."""
    lines = FENCE.sub(lambda m: "\n" * m.group().count("\n"), raw.replace("\r\n", "\n")).split("\n")
    found = []
    want = [NAMES.get(k, k) for k in result.get("lanes", {})]
    best = max(lines, key=lambda t: sum(n in t for n in want), default="")
    missing = [n for n in want if n not in best]
    if missing:
        found.append((0, "lanes", f"no line names every lane the run listed; name {', '.join(missing)} on the coverage line"))
    sources = []  # (text, links) of everything a brief may quote
    for i in result.get("items", []):
        urls = {i.get("url"), *(i.get("links") or {}).values()}
        sources += [(t, urls) for t in (i.get("title"), i.get("snippet"))]
        sources += [(c.get("text"), urls | {c.get("url")}) for c in i.get("comments") or []]
    sources = [(" ".join(str(t or "").split()), u) for t, u in sources]
    quotes, n = 0, 0
    while n < len(lines):
        if not QUOTE.match(lines[n]):
            n += 1
            continue
        start = n
        while n < len(lines) and QUOTE.match(lines[n]):
            n += 1
        quotes += 1
        text = " ".join(re.sub(r"^[ \t]*>[ \t]?", "", t) for t in lines[start:n])
        pieces = [p for p in (" ".join(s.split()) for s in ELLIPSIS.split(text.strip().strip(WRAP))) if p]
        if pieces:
            pieces[-1] = pieces[-1].rstrip(".,;:!? ") or pieces[-1]  # a full stop the brief adds is not a misquote
        hits = [u for t, u in sources if pieces and in_order(pieces, t)]
        after = next((t for t in lines[n:] if t.strip()), "")
        links = {u.rstrip(".,;:") for u in LINK.findall(after)}
        if not hits:
            found.append((start + 1, "quote", f'not found verbatim in the pulse results: "{snippet(text, 0)}"'))
        elif not any(links & u for u in hits):
            found.append((start + 1, "quote", "put the quoted item's or comment's link on the line after the quote"))
    if result.get("clusters") and not quotes:
        found.append((0, "quote", "no quote; quote an item or comment of each cluster on a > line, with its link"))
    return found


# --kind models. A location cites a file of the topic folder by its line, or by a range of lines.
LOCATION = re.compile(r"(?<![\w./-])((?:sources|models)/[\w./+-]+):(\d+)(?:-(\d+))?")


def models_problems(raw, topic):
    """Each location the deliverable cites as (line, rule, detail) when its file or its line is missing."""
    found, count = [], {}
    for n, line in enumerate(raw.replace("\r\n", "\n").split("\n"), 1):
        for loc in LOCATION.finditer(line):
            path = topic / loc[1]
            if path not in count:
                data = path.read_bytes() if path.is_file() else None
                count[path] = None if data is None else data.count(b"\n") + (not data.endswith(b"\n"))
            first, last = int(loc[2]), int(loc[3] or loc[2])
            if count[path] is None:
                found.append((n, "location", f"{loc[0]}: no such file in the topic folder"))
            elif first < 1 or last > count[path]:
                found.append((n, "location", f"{loc[0]}: the file has {count[path]} lines"))
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="Markdown or text file; - reads standard input")
    ap.add_argument("--kind", choices=["report", "pulse", "models"], help="report: also check the structure against "
                    "claims.json beside the file; pulse: against the pulse.py result (<stem>.json) beside the brief; "
                    "models: every <path>:<line> cited against the files in the deliverable's folder")
    args = ap.parse_args(argv)
    if args.file != "-":
        args.file = str(Path(args.file).expanduser())  # a quoted ~ reaches the script unexpanded
    try:
        data = sys.stdin.buffer.read() if args.file == "-" else Path(args.file).read_bytes()
        raw = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"FAIL\tcannot read: {e}")
        return 1
    problems = check(raw)
    if args.kind == "report":
        if args.file == "-":
            print("FAIL\t--kind report reads the claims.json beside the report; pass the file, not -")
            return 1
        folder = Path(args.file).parent
        path = folder / "claims.json"
        try:
            claims = json.loads(path.read_text(encoding="utf-8-sig"))
            verdicts = {c["id"].lower(): c.get("verdict", "not checked") for c in claims}
            central = {c["id"].lower() for c in claims if c.get("importance") == "central"}
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            print(f"FAIL\tcannot read {path}: {e}")
            return 1
        stem = re.fullmatch(r"report-(.+)\.md", Path(args.file).name, re.I)
        views = ([folder / f"extracts-{stem.group(1)}.json"] if stem else []) + [folder / "extracts.json"]
        view, located = None, set()
        for v in (v for v in views if v.is_file()):
            try:
                rows = json.loads(v.read_text(encoding="utf-8-sig"))["claims"]
                ids = {str(c.get("id", "")).lower() for c in rows if c.get("quotes")}
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
                print(f"FAIL\tcannot read {v}: {e}")
                return 1
            if v == views[0] or any("id" in c for c in rows):  # dig's extracts.json cites no ids: not a report's view
                view, located = v, ids
                break
        if view is None:
            problems.append((0, "view", f"no {views[0].name} beside the report; write the report's evidence view"))
        problems += report_problems(raw, verdicts, central - located if view else frozenset(), view.name if view else "")
    if args.kind == "pulse":
        if args.file == "-":
            print("FAIL\t--kind pulse reads the pulse.py result beside the brief; pass the file, not -")
            return 1
        path = Path(args.file).with_suffix(".json")
        try:
            problems += pulse_problems(raw, json.loads(path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError, TypeError, AttributeError) as e:
            print(f"FAIL\tcannot read {path}: {e}")
            return 1
    if args.kind == "models":
        if args.file == "-":
            print("FAIL\t--kind models reads the files the deliverable cites; pass the file, not -")
            return 1
        problems += models_problems(raw, Path(args.file).parent)
    for line, rule, detail in problems:
        print(f"{line}:{rule}: {detail}")
    print(f"FAIL\t{len(problems)} problems" if problems else "OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
