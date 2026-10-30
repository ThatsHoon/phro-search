r"""Check that every quote in a topic's extracts.json sits at its stated source line, then build report.html.

Usage:
  report.py <topic_dir>          check every quote, then write <topic_dir>/report.html
  report.py <topic_dir> --check  check only; write nothing

Lines count like grep -n. A quote matches when it appears within lines line-2 to
end+2 of sources/<file>, both sides normalized the same way: on each line a leading
caption timestamp ([mm:ss], [h:mm:ss]) and list marker are dropped, then every
whitespace character is removed. Pieces split by the ellipsis character (U+2026)
must appear in that order. Any mismatch blocks the page and leaves an existing
report.html as it is.

Output, tab-separated:
  MISMATCH\t<claim|disagreement> <i> quote <j>\t<file>:<line>\t<reason>\t<quote head>
  FAIL\t<k> of <m> quotes do not match; report.html not written
  FAIL\t<reason>       extracts.json missing, not valid JSON or the wrong shape
  OK\t<m> quotes in <c> claims match\t<report.html path or "check only">
Reasons: no file, bad file path, line out of range (file has N lines),
not found near the line, piece <k> not found in order.
"""
import argparse
import functools
import html
import json
import pathlib
import re
import sys
import urllib.parse

VERSION = "0.1.0"

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\U0000061c\U0000200b-\U0000200f\U0000202a-\U0000202e\U00002060-\U00002064\U00002066-\U00002069\U0000feff]")
_QUOTES = str.maketrans("\U00002018\U00002019\U0000201a\U0000201b\U00002032\U0000201c\U0000201d\U0000201e\U0000201f\U00002033\U0000ff02\U0000ff07", "'''''\"\"\"\"\"\"'")


def clean(s, cap=300):
    """One printable line: control, bidi and zero-width characters dropped, quote lookalikes made ASCII, whitespace collapsed."""
    return " ".join(_CTRL.sub("", str(s)).translate(_QUOTES).split())[:cap]


# Legacy values written by the older tool, Japanese then Korean: "attached", "partly", "not attached", "partly".
STATUS = {"sourced": "sourced", "partial": "partial", "none": "none",
          "付いた": "sourced", "一部だけ": "partial", "付かなかった": "none", "일부만": "partial"}
# Expected keys and types; a key ending in ? may be absent, unknown keys are ignored. "ja" is the legacy translation.
TOP = {"title": str, "question": str, "stopped": str, "claims": list, "disagreements?": list, "unreached?": list}
CLAIM = {"claim": str, "status": str, "note?": str, "quotes": list}
DISAGREEMENT = {"topic": str, "quotes": list}
QUOTE = {"file": str, "line": int, "end?": int, "text": str, "translation?": str, "ja?": str, "mark?": str, "who?": str}
ELLIPSIS = "\U00002026"
# A caption timestamp, then a list marker: a bullet glyph, or -, *, +, 1. or 1) with whitespace after it.
_LEAD = re.compile(r"^\s*(?:\[(?:\d+:)?\d+:\d\d\])?\s*(?:[\U000000b7\U00002022\U00002023\U00002043\U000025a0\U000025a1"
                   r"\U000025aa\U000025c6\U000025cb\U000025cf\U000025e6\U000030fb]|(?:[-*+]|\d+[.)])(?!\S))?")
esc = html.escape

CSS = """
:root{color-scheme:light dark;--bg:#faf9f6;--fg:#1f2328;--muted:#5f6670;--line:#d8dde3;--card:#fff;
--accent:#0b5cad;--partial:#8a5a00;--none:#b42318;--hit:#fff1a6}
@media (prefers-color-scheme:dark){:root{--bg:#111317;--fg:#e6e9ee;--muted:#9aa3ad;--line:#30363d;
--card:#181c22;--accent:#6cb6ff;--partial:#d9a62e;--none:#ff7b72;--hit:#574600}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 system-ui,sans-serif;overflow-wrap:break-word}
main{max-width:48rem;margin:0 auto;padding:2rem 16px 4rem}
h1{font-size:1.6rem;line-height:1.3}
h2{font-size:1.15rem;line-height:1.4;margin:2.5rem 0 .5rem;padding-top:1rem;border-top:1px solid var(--line)}
h3{font-size:1rem;margin:1.5rem 0 .5rem}
.lead,.note,figcaption,summary,.n{color:var(--muted)}
.status{font-size:.75rem;font-weight:500;border:1px solid;border-radius:1em;padding:0 .6em;white-space:nowrap}
.sourced{color:var(--accent)}.partial{color:var(--partial)}.none{color:var(--none)}
figure{margin:1rem 0;padding:1rem;background:var(--card);border:1px solid var(--line);border-radius:8px}
blockquote{margin:0;padding-left:.8rem;border-left:3px solid var(--accent);white-space:pre-wrap}
.who{font-weight:600;margin:0 0 .5rem}
.tr{margin:.6rem 0 0}
.tag{font-size:.75rem;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 .35em}
figcaption{font-size:.85rem;margin-top:.6rem}
a{color:var(--accent)}
summary{cursor:pointer;font-size:.85rem;margin-top:.5rem}
pre{font:.8rem/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;max-height:24rem;overflow:auto;margin:.5rem 0 0}
.n{display:inline-block;min-width:3em;padding-right:1em;text-align:right;user-select:none}
mark{background:var(--hit);color:inherit}
"""


def need(obj, spec, where):
    """Raise ValueError unless obj is an object whose spec keys have the spec types."""
    if type(obj) is not dict:
        raise ValueError(f"{where} must be an object")
    for key, kind in spec.items():
        name = key.rstrip("?")
        if (name in obj or not key.endswith("?")) and type(obj.get(name)) is not kind:
            raise ValueError(f"{where}: {name} must be {kind.__name__}")


def load(path):
    """extracts.json and its quotes as (where, quote) pairs; raises ValueError naming the first problem."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        raise ValueError(f"cannot read {path}") from None
    except ValueError as e:
        raise ValueError(f"extracts.json is not valid JSON: {e}") from None
    need(data, TOP, "extracts.json")
    if any(type(u) is not str for u in data.get("unreached", [])):
        raise ValueError("extracts.json: unreached must hold strings only")
    quotes = []
    for key, name, spec in (("claims", "claim", CLAIM), ("disagreements", "disagreement", DISAGREEMENT)):
        for i, item in enumerate(data.get(key, []), 1):
            need(item, spec, f"{name} {i}")
            if name == "claim" and item["status"] not in STATUS:
                raise ValueError(f'claim {i}: unknown status "{clean(item["status"], 40)}"')
            for j, q in enumerate(item["quotes"], 1):
                need(q, QUOTE, f"{name} {i} quote {j}")
                quotes.append((f"{name} {i} quote {j}", q))
    return data, quotes


@functools.cache
def read_lines(path):
    """The file's lines numbered as grep -n numbers them, or None when it cannot be read."""
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
    except (OSError, ValueError):
        return None
    # Split on \n only: splitlines() also breaks on \f, \x0b, \x1c-\x1e, \x85, U+2028 and U+2029,
    # and text-mode reads turn a lone \r into \n.
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]


def norm(text):
    """Text as compared: per line a leading timestamp and list marker dropped, then every whitespace character removed."""
    return "".join("".join(_LEAD.sub("", line) for line in text.split("\n")).split())


def check(src, q):
    """Why the quote does not match its source lines, or None when it does."""
    path = pathlib.PureWindowsPath(q["file"])  # Windows rules on every OS: drives, UNC roots and backslashes count too
    if path.anchor or ".." in path.parts:
        return "bad file path"
    lines = read_lines(src / q["file"])
    if lines is None:
        return "no file"
    first, last = q["line"], q.get("end", q["line"])
    if not 1 <= first <= last <= len(lines):
        return f"line out of range (file has {len(lines)} lines)"
    window = norm("\n".join(lines[max(first - 3, 0):last + 2]))
    pieces = [p for p in map(norm, q["text"].split(ELLIPSIS)) if p]
    pos = 0
    for k, piece in enumerate(pieces, 1):
        at = window.find(piece, pos)
        if at < 0:
            return f"piece {k} not found in order" if len(pieces) > 1 else "not found near the line"
        pos = at + len(piece)
    return None if pieces else "not found near the line"


def quote_html(src, q):
    """One quote: who, the text, its translation, the source link and mark, and the numbered lines around it."""
    first, last = q["line"], q.get("end", q["line"])
    lo = max(first - 5, 1)
    rows = []
    for n, line in enumerate(read_lines(src / q["file"])[lo - 1:last + 5], lo):
        row = f'<span class="n">{n}</span>{esc(line)}'
        rows.append(f"<mark>{row}</mark>" if first <= n <= last else row)
    context = "\n".join(rows)
    loc = f"sources/{q['file']}:{first}" + (f"-{last}" if last != first else "")
    mark = f' <span class="tag">{esc(q["mark"])}</span>' if q.get("mark") else ""
    tr = q.get("translation", q.get("ja"))
    out = ["<figure>"]
    if q.get("who"):
        out.append(f'<p class="who">{esc(q["who"])}</p>')
    out.append(f"<blockquote>{esc(q['text'])}</blockquote>")
    if tr:
        out.append(f'<p class="tr"><span class="tag">translation</span> {esc(tr)}</p>')
    out.append(f'<figcaption><a href="sources/{esc(urllib.parse.quote(q["file"]))}">{esc(loc)}</a>{mark}</figcaption>')
    out.append(f"<details><summary>context</summary><pre>{context}</pre></details></figure>")
    return "\n".join(out)


def page(src, data):
    """report.html: the question, each claim with its quotes, then disagreements and what was not reached."""
    body = [f"<h1>{esc(data['title'])}</h1>",
            f'<p class="lead">Question: {esc(data["question"])}</p>',
            f'<p class="lead">Stopped: {esc(data["stopped"])}</p>']
    for c in data["claims"]:
        status = STATUS[c["status"]]
        body.append(f'<section><h2>{esc(c["claim"])} <span class="status {status}">{status}</span></h2>')
        if c.get("note"):
            body.append(f'<p class="note">{esc(c["note"])}</p>')
        body += [quote_html(src, q) for q in c["quotes"]]
        body.append("</section>")
    if data.get("disagreements"):
        body.append("<section><h2>Disagreements</h2>")
        for d in data["disagreements"]:
            body.append(f"<h3>{esc(d['topic'])}</h3>")
            body += [quote_html(src, q) for q in d["quotes"]]
        body.append("</section>")
    if data.get("unreached"):
        items = "".join(f"<li>{esc(u)}</li>" for u in data["unreached"])
        body.append(f"<section><h2>Not reached</h2><ul>{items}</ul></section>")
    main_html = "\n".join(body)
    return (f'<!doctype html>\n<html><head><meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{esc(data['title'])}</title>\n<style>{CSS}</style></head>\n"
            f"<body><main>\n{main_html}\n</main></body></html>\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topic_dir", help="topic folder holding extracts.json and sources/")
    ap.add_argument("--check", action="store_true", help="only check the quotes; do not write report.html")
    args = ap.parse_args(argv)
    topic = pathlib.Path(args.topic_dir)
    try:
        data, quotes = load(topic / "extracts.json")
    except ValueError as e:
        print(f"FAIL\t{e}")
        return 1
    src = topic / "sources"
    bad = 0
    for where, q in quotes:
        reason = check(src, q)
        if reason:
            bad += 1
            print(f"MISMATCH\t{where}\t{clean(q['file'])}:{q['line']}\t{reason}\t{clean(q['text'], 60)}")
    if bad:
        print(f"FAIL\t{bad} of {len(quotes)} quotes do not match; report.html not written")
        return 1
    out = topic / "report.html"
    if not args.check:
        out.write_text(page(src, data), encoding="utf-8")
    print(f"OK\t{len(quotes)} quotes in {len(data['claims'])} claims match\t{'check only' if args.check else out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
