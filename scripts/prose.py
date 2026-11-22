"""Check a report's prose against the claims it cites: the brief for one reader, then the count of its reply.

The verifiers test a claim against the web and the support pass tests a quote against its claim; this tests the last
step, each sentence of the report against the claims it cites. The reader gets only the report's statements and
their evidence, so its reply measures what the writer did with them.

Usage:
  prose.py brief <report file> <brief out> [--plant N]
  prose.py score <report file> <brief out> <reply file>

brief numbers every statement above the evidence table that cites a claim (a sentence of the prose, or a table row)
and writes a brief that lists each with the claims it cites: the claim's text, its source (label, venue, URL), what
the verifiers found (votes and what is withheld), and its quotes and qualifiers, with the view's unreached
items first, from claims.json and the evidence view beside the report
(extracts-<stem>.json for report-<stem>.md). --plant N (default 2) adds N more statements at the end, each a copy of
an earlier one with a number changed, and writes them to <brief out>.planted.tsv: a reader that rates one of those
as stated did not read closely, so that reply is not used.
score prints, tab-separated:
  STRETCHED|UNBACKED|WRONG <statement> <line> <what the reply says> <the statement's first 80 characters>
  MISSING <statement>                      a statement of the brief the reply has no line for
  UNCITED <line> <first 80 characters>     a sentence of the prose that cites nothing (headings, code and the
                                           evidence table are not prose)
  UNUSED <claim id>                        a central survived claim the report never cites
  PLANTED <caught> of <planted> changed statements not rated stated
  PROSE <n> statements <r> rated <s> stated <x> stretched <u> unbacked <w> wrong
and exits 1 when a planted statement was rated stated or a statement has no line, else 0.
"""
import argparse
import json
import re
import sys
from pathlib import Path

VERSION = "0.7.2"

CITE = re.compile(r"\[(c\d+(?:,\s*c\d+)*)\]")
RATINGS = ("stated", "stretched", "unbacked", "wrong")
BRIEF = """You are checking a report's sentences against the evidence they cite.

Below are numbered statements from a report. Under each are the claims it cites, each with its source, what its
checkers found (their votes, and what the source keeps closed), the quotes that back the claim and, where the source
limits it, a qualifier. A list of what the research did not reach may come first.
Judge each statement from that text alone: use no other knowledge, open no file and search nothing. The statement
and the evidence may be in different languages.

Rate each statement:
- stated: everything the statement asserts is in its claims, their sources' names, the votes, the withheld notes, the quotes
  or the list of what was not reached.
- stretched: it says more than they do: a stronger verb, a wider scope, a number, unit or condition that differs, a
  limit from a qualifier left out where it changes the meaning, a cause where they show only a sequence, or the
  writer's own inference or advice worded as a fact.
- unbacked: a part of it is in none of them.
- wrong: it contradicts them.
A sentence that names itself as the report's own proposal or reading is stated when the facts it leans on are, and so
is the part of a sentence that says what this research did not find or did not read.

Reply with one line per statement and nothing else, tab-separated:
S<number>\t<rating>\t<the words of the statement that go beyond or against the evidence, or ->

"""


def prose(report):
    """(line number, text, is a table row) of the report above its evidence table, without headings and code."""
    out, fenced = [], False
    for n, line in enumerate(Path(report).read_text(encoding="utf-8-sig").splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            fenced = not fenced
            continue
        if re.match(r"\|\s*id\s*\|", s, re.I):
            break
        if fenced or not s or s.startswith("#") or re.fullmatch(r"\|[\s:|-]+\|?", s):
            continue
        out.append((n, s, s.startswith("|")))
    return out


def ids(text):
    return list(dict.fromkeys(i.strip() for group in CITE.findall(text) for i in group.split(",")))


def statements(report):
    """(cited [(line, text, ids)], uncited [(line, text)]): table rows whole, prose split into sentences."""
    cited, uncited, header = [], [], True
    for n, text, row in prose(report):
        if row:
            if not header and CITE.search(text):
                cited.append((n, text, ids(text)))
            header = False
            continue
        header = True
        for s in re.split(r"(?<=[.!?。])\s+(?=\S)", text):
            if CITE.search(s):
                cited.append((n, s, ids(s)))
            elif len(s) > 20:
                uncited.append((n, s))
    return cited, uncited


def evidence(report):
    """(view claims by id, claims.json entries by id, the view's unreached items) from the files beside the report."""
    report = Path(report)
    stem = report.stem.removeprefix("report-")
    view = next((p for p in (report.with_name(f"extracts-{stem}.json"), report.with_name("extracts.json")) if p.is_file()), None)
    if view is None:
        raise ValueError(f"no evidence view beside {report.name}")
    claims_json = report.with_name("claims.json")
    entries = json.loads(claims_json.read_text(encoding="utf-8-sig")) if claims_json.is_file() else []
    data = json.loads(view.read_text(encoding="utf-8-sig"))
    return {str(c.get("id")): c for c in data["claims"]}, {str(c.get("id")): c for c in entries}, data.get("unreached") or []


def plant(text, n):
    """text with its first number outside a citation or a date changed, or None when it has none."""
    for m in re.finditer(r"(?<![\w\[-])\d+(?![\w\]-])", text):
        if not any(c.start() <= m.start() < c.end() for c in CITE.finditer(text)):
            return text[:m.start()] + str(int(m.group()) * 2 + 3 + n) + text[m.end():]
    return None


def listed(text, cites, view, entries):
    lines = []
    for i in cites:
        c, e = view.get(i), entries.get(i, {})
        if c is None:
            lines.append(f"  {i}: not in the evidence view")
            continue
        lines.append(f"  {i}: {c['claim']}")
        source = ", ".join(str(e[k]) for k in ("label", "venue", "url") if e.get(k))
        if source:
            lines.append(f"    source: {source}")
        withheld = list(dict.fromkeys(v["withheld"] for v in e.get("votes") or [] if v.get("withheld")))
        if withheld:
            lines.append(f"    withheld: {' | '.join(withheld)}")
        for v in e.get("votes") or []:
            lines.append(f"    vote: {'refuted' if v.get('refuted') else 'held'}, {v.get('confidence')}: {' '.join(str(v.get('evidence') or '').split())[:400]}")
        for q in c.get("quotes") or []:
            lines.append(f'    quote ({q.get("support") or "unrated"}): "{" ".join(q["text"].split())}"')
            if q.get("qualifier"):
                lines.append(f'    qualifier: "{" ".join(q["qualifier"]["text"].split())}"')
    return [text] + lines + [""]


def brief(a):
    cited, _ = statements(a.report)
    view, entries, unreached = evidence(a.report)
    numbered = [n for n, (_, text, _) in enumerate(cited) if plant(text, 0)]
    want = min(a.plant, len(numbered))
    picks = [numbered[k * len(numbered) // want] for k in range(want)]
    parts, planted = [BRIEF], []
    if unreached:
        parts += ["Not reached:"] + [f"  - {' '.join(str(u).split())}" for u in unreached] + [""]
    for n, (_, text, cites) in enumerate(cited, 1):
        parts += listed(f"S{n}. {text}", cites, view, entries)
    for k, n in enumerate(picks):
        changed = plant(cited[n][1], k)
        planted.append(f"S{len(cited) + k + 1}\tS{n + 1}\t{changed}\n")
        parts += listed(f"S{len(cited) + k + 1}. {changed}", cited[n][2], view, entries)
    Path(a.out).write_text("\n".join(parts), encoding="utf-8", newline="\n")
    Path(a.out + ".planted.tsv").write_text("".join(planted), encoding="utf-8", newline="\n")
    print(f"BRIEF\t{len(cited)} statements\t{len(planted)} planted\t{a.out}")
    return 0


def survived(entry):
    votes = entry.get("votes") or []
    return sum(bool(v.get("refuted")) for v in votes) < 2 and any(not v.get("refuted") and v.get("confidence") in ("high", "medium") for v in votes)


def score(a):
    cited, uncited = statements(a.report)
    _, entries, _ = evidence(a.report)
    planted = [line.split("\t")[0] for line in Path(a.out + ".planted.tsv").read_text(encoding="utf-8").splitlines() if line]
    reply = {}
    for line in Path(a.reply).read_text(encoding="utf-8-sig", errors="replace").splitlines():
        cells = [c.strip() for c in line.split("\t")]
        if len(cells) >= 2 and re.fullmatch(r"S\d+\.?", cells[0]) and cells[1].lower() in RATINGS:
            reply[cells[0].rstrip(".")] = (cells[1].lower(), cells[2] if len(cells) > 2 else "-")
    counts, missing = dict.fromkeys(RATINGS, 0), 0
    for n, (line, text, _) in enumerate(cited, 1):
        got = reply.get(f"S{n}")
        if got is None:
            missing += 1
            print(f"MISSING\tS{n}")
            continue
        counts[got[0]] += 1
        if got[0] != "stated":
            print(f"{got[0].upper()}\tS{n}\t{line}\t{got[1]}\t{text[:80]}")
    for line, text in uncited:
        print(f"UNCITED\t{line}\t{text[:80]}")
    used = {i for _, _, cites in cited for i in cites}
    for i, e in entries.items():
        if e.get("importance") == "central" and survived(e) and i not in used:
            print(f"UNUSED\t{i}")
    caught = sum(reply.get(s, ("stated",))[0] != "stated" for s in planted)
    if planted:
        print(f"PLANTED\t{caught} of {len(planted)} changed statements not rated stated")
    print(f"PROSE\t{len(cited)} statements\t{sum(counts.values())} rated\t" + "\t".join(f"{counts[r]} {r}" for r in RATINGS))
    return int(missing > 0 or caught < len(planted))


def main(argv=None):
    p = argparse.ArgumentParser(prog="prose.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief", help="write the reader brief for a report's cited statements")
    b.add_argument("report")
    b.add_argument("out")
    b.add_argument("--plant", type=int, default=2, help="how many changed copies to add (default 2)")
    s = sub.add_parser("score", help="count a saved reply's ratings")
    s.add_argument("report")
    s.add_argument("out")
    s.add_argument("reply")
    a = p.parse_args(argv)
    try:
        return {"brief": brief, "score": score}[a.cmd](a)
    except (OSError, ValueError, KeyError) as e:
        print(f"FAIL\t{getattr(e, 'strerror', None) or e}")
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
