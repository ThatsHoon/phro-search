r"""Locate each finding of a report's notes in its archived source; from the picks, write claims.json and the view.

Usage:
  locate.py <topic_dir>                       list every finding of notes/*.md with where its quote sits
  locate.py <topic_dir> <stem> --picks <file> add the picked findings to claims.json and write extracts-<stem>.json

A finding is a line of the researcher's notes (references/report.md):
  - F<n>. <claim>. Quote: "<quote>" <URL> (<label>)
Its key is "<note name> F<n>". The URL finds the source through sources/index.tsv, and the quote is searched in that
source's text files by its letters and digits alone, ignoring case, so markup and quote styles do not block a match.
A quote may have several pieces split by "..." or the ellipsis character. What goes into claims.json and the view is
the source's own text, which report.py then checks.

The picks file is JSON:
  {"title": "...", "question": "...", "stopped": "...", "disagreements?": [], "unreached?": [],
   "claims": [{"id": "c1", "findings": ["flood F3"], "importance": "central", "claim": "<in the user's language>",
               "standing?": "open-post|reviewed|unknown", "venue?": "<name>",
               "quotes?": [{"file": "a.md", "line": 12, "end?": 13, "text": "<exact text>"}]}]}
A new id is appended to claims.json with the finding's English claim, its first quote, URL and label, and no votes; an
id already there keeps its entry and its votes. A pick's standing and venue are written to either. The view lists each picked claim with its located quotes and status
partial; the support pass sets the rest. A pick whose finding did not locate blocks the write, unless the pick gives
"quotes" itself: text read from the source, which replaces what the findings located and which report.py checks.

Output, tab-separated:
  FOUND\t<key>\t<file>:<line>[-<end>]\t<label>\t<claim head>
  MISS\t<key>\t<reason>\t<url>       reasons: no source for the URL, not found in <file>[, nearest line <n>], no quote
  PICK\t<id>\t<key>\t<reason>        a pick that cannot be used
  OK\t<c> claims, <q> quotes, <n> new in claims.json\t<view path>
  FAIL\t<reason>
"""
import argparse
import difflib
import functools
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import report as rep  # noqa: E402  (python -I leaves the script's folder off the path)

VERSION = "0.6.1"
FINDING = re.compile(r"^- F(\d+)\.\s*(.*?)\s*Quote[^:\"]*:\s*\"(.*)\"(.*?)(https?://\S+)(.*)$")
LABEL = re.compile(r"\(([a-z-]+)\)")
TEXT = (".md", ".txt")
MIN_QUOTE = 12


def url_key(url):
    """A URL as the index and the notes both can spell it: no fragment or trailing slash, an arXiv link by its id."""
    url = url.split("#")[0].rstrip("/.,;)")
    m = re.search(r"arxiv\.org/(?:abs|html|pdf)/(\d{4}\.\d+)", url)
    return f"arxiv:{m.group(1)}" if m else url.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")


def source_files(src):
    """{url key: [text files in sources/]} from sources/index.tsv, under the URL given and the final one; a later row wins."""
    out = {}
    for row in rep.index_rows(src):
        files = [f for f in row["files"].split(",") if f.endswith(TEXT)]
        for url in (row["url"], row["final"]):
            if url != "-":
                out[url_key(url)] = files
    return out


def squeeze(text):
    """Letters and digits only, in lower case, so markup, punctuation and quote styles do not block a match."""
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text if c.isalnum())


@functools.cache
def letters(path):
    """A source as (lines numbered like grep -n, its squeezed text, the (line, column) of each squeezed character)."""
    lines = rep.read_lines(path)
    if lines is None:
        return None
    at = [(i, j) for i, line in enumerate(lines) for j, c in enumerate(line) if c.isalnum()]
    return lines, squeeze("".join(lines[i][j] for i, j in at)), at


def find(src, name, text):
    """(line, end, the source's own text) for a quote in sources/<name>, or None. Pieces must appear in order; a quote
    of fewer than MIN_QUOTE letters and digits is too short to place."""
    found = letters(src / name)
    pieces = [p for p in map(squeeze, re.split(rf'\.\.\.|{rep.ELLIPSIS}|"\s*and\s*"', text)) if p]
    if not found or sum(map(len, pieces)) < MIN_QUOTE:
        return None
    lines, whole, at = found
    pos, spans = 0, []
    for piece in pieces:
        hit = whole.find(piece, pos)
        if hit < 0:
            return None
        pos = hit + len(piece)
        spans.append((at[hit], at[pos - 1]))
    copies = []
    for (i, j), (k, m) in spans:
        copies.append(lines[i][j:m + 1] if i == k else "\n".join((lines[i][j:], *lines[i + 1:k], lines[k][:m + 1])))
    return spans[0][0][0] + 1, spans[-1][1][0] + 1, rep.ELLIPSIS.join(copies)


def nearest(src, name, text):
    """The source line holding the longest run of the quote's letters and digits, when that run could be a quote itself."""
    found = letters(src / name)
    if not found:
        return None
    lines, whole, at = found
    quote = squeeze(text)
    run = difflib.SequenceMatcher(None, quote, whole, autojunk=False).find_longest_match(0, len(quote), 0, len(whole))
    return at[run.b][0] + 1 if run.size >= MIN_QUOTE else None


def findings(topic):
    """Every finding line of notes/*.md as {key: finding}, located where its source and quote allow."""
    src = topic / "sources"
    files = source_files(src)
    out = {}
    for note in sorted((topic / "notes").glob("*.md")):
        for raw in note.read_text(encoding="utf-8-sig", errors="replace").split("\n"):
            head = re.match(r"^- F(\d+)\.", raw)
            if not head:
                continue
            key = f"{note.stem} F{head.group(1)}"
            m = FINDING.match(raw.rstrip("\r"))
            if not m:
                out[key] = {"miss": "no quote", "url": "-"}
                continue
            claim, quote, url, tail = m.group(2), m.group(3), m.group(5).rstrip(".,;)"), m.group(6)
            labels = LABEL.findall(tail)
            item = {"claim": claim, "quote": quote, "url": url, "label": labels[-1] if labels else "summary"}
            names = files.get(url_key(url))
            if not names:
                item["miss"] = "no source for the URL"
            else:
                hit = next(((f, at) for f in names if (at := find(src, f, quote))), None)
                if hit:
                    item["file"], (item["line"], item["end"], item["text"]) = hit[0], hit[1]
                else:
                    near = nearest(src, names[0], quote)
                    item["miss"] = f"not found in {names[0]}" + (f", nearest line {near}" if near else "")
            out[key] = item
    return out


def where(item):
    span = str(item["line"]) if item["end"] == item["line"] else f'{item["line"]}-{item["end"]}'
    return f'{item["file"]}:{span}'


def quote_of(item):
    q = {"file": item["file"], "line": item["line"], "text": item["text"]}
    if item["end"] != item["line"]:
        q["end"] = item["end"]
    return q


def write(topic, stem, picks, found):
    """Add the picks to claims.json and write the view; returns 0, or 1 after printing what blocked it."""
    problems = []
    for pick in picks["claims"]:
        for key in pick["findings"]:
            item = found.get(key)
            reason = "no such finding" if item is None else item.get("miss")
            if reason and (item is None or not pick.get("quotes")):
                problems.append((pick["id"], key, reason))
    if problems:
        for p in problems:
            print("\t".join(("PICK", *p)))
        print(f"FAIL\t{len(problems)} picks cannot be used; nothing written")
        return 1
    path = topic / "claims.json"
    claims = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else []
    known = {c["id"] for c in claims}
    view, new, count = [], 0, 0
    for pick in picks["claims"]:
        items = [found[key] for key in pick["findings"]]
        quotes = pick.get("quotes") or [quote_of(i) for i in items]
        standing = {k: pick[k] for k in ("standing", "venue") if k in pick}
        if pick["id"] not in known:
            first = items[0]
            claims.append({"id": pick["id"], "claim": first["claim"], "quote": quotes[0]["text"], "url": first["url"],
                           "label": first["label"], "importance": pick["importance"], "votes": []})
            known.add(pick["id"])
            new += 1
        next(c for c in claims if c["id"] == pick["id"]).update(standing)
        view.append({"id": pick["id"], "claim": pick["claim"], "status": "partial", "quotes": quotes})
        count += len(quotes)
    data = {k: picks[k] for k in ("title", "question", "stopped", "disagreements", "unreached") if k in picks}
    data["claims"] = view
    out = topic / f"extracts-{stem}.json"
    path.write_text(json.dumps(claims, ensure_ascii=False, indent=1), encoding="utf-8")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK\t{len(view)} claims, {count} quotes, {new} new in claims.json\t{out}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("topic_dir")
    p.add_argument("stem", nargs="?")
    p.add_argument("--picks")
    args = p.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    topic = pathlib.Path(args.topic_dir)
    if bool(args.stem) != bool(args.picks):
        print("FAIL\ta stem and --picks go together")
        return 1
    if args.stem and not re.fullmatch(r"[A-Za-z0-9][\w.-]*", args.stem):
        print("FAIL\tbad stem")
        return 1
    found = findings(topic)
    if not found:
        print("FAIL\tno findings in notes/*.md")
        return 1
    if not args.picks:
        for key, item in found.items():
            if "miss" in item:
                print("\t".join(("MISS", key, item["miss"], item["url"])))
            else:
                print("\t".join(("FOUND", key, where(item), item["label"], rep.clean(item["claim"], 80))))
        return 0
    try:
        picks = json.loads(pathlib.Path(args.picks).read_text(encoding="utf-8-sig"))
        rep.need(picks, {"title": str, "question": str, "stopped": str, "claims": list}, "picks")
        for pick in picks["claims"]:
            rep.need(pick, {"id": str, "findings": list, "importance": str, "claim": str}, "pick")
            if pick["importance"] not in rep.IMPORTANCE or not pick["findings"]:
                raise ValueError(f'pick {pick["id"]}: needs findings and an importance of {", ".join(rep.IMPORTANCE)}')
            if pick.get("standing", rep.STANDING[0]) not in rep.STANDING:
                raise ValueError(f'pick {pick["id"]}: standing must be one of {", ".join(rep.STANDING)}')
    except (OSError, ValueError) as e:
        print(f"FAIL\t{rep.clean(e)}")
        return 1
    return write(topic, args.stem, picks, found)


if __name__ == "__main__":
    sys.exit(main())
