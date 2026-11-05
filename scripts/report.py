r"""Check that every quote in a topic's evidence view sits at its stated source line, then build its page.

Usage:
  report.py <topic_dir>                  check extracts.json (dig), then write <topic_dir>/report.html
  report.py <topic_dir> <stem>           check extracts-<stem>.json (a report), then write evidence-<stem>.html
  report.py <topic_dir> [<stem>] --check check only; write nothing

When the topic has a claims.json (report mode), a claim in a view may carry its "id";
the page then shows that claim's verdict, standing and votes. Every claims.json claim is checked:
a standing is one of open-post, reviewed or unknown, and
each verdict must follow from its votes (2 refutations: refuted; one vote that holds with
high or medium confidence: survived; any other single vote or none: unverified; else
survived), at most 3 votes, and a vote's "checked" date written YYYY-MM-DD. The claims a
view cites are checked too: every id is in claims.json, each central one has a quote in the
view that is not marked retracted, and the view cites at most 10 central claims and 40 in
all, the limits of a deep run. In any view, a sourced claim needs a quote from a source that is not
retracted whose support (from the support pass) is full, and a claim whose quotes all come
from retracted sources cannot be sourced or partial. A quote's qualifier, the sentence that limits it, is checked like a quote.
The page shows each source's dates from sources/index.tsv when there is one, with the snapshot date of an
archived copy.

Lines count like grep -n. A quote matches when it appears within lines line-2 to
end+2 of sources/<file>, both sides normalized the same way: on each line a leading
caption timestamp ([mm:ss], [h:mm:ss]) and list marker are dropped, then every
whitespace character (no-break spaces too) and soft hyphen is removed. Pieces split by the ellipsis character (U+2026)
must appear in that order. Any mismatch blocks the page and leaves an existing
report.html as it is.

Output, tab-separated:
  MISMATCH\t<claim|disagreement> <i> quote <j>\t<file>:<line>\t<reason>\t<quote head>
  CLAIM\t<where>\t<reason>                     a claims.json problem
  CLAIM\tclaim <i>\t<reason>                   a claim in the view breaks a rule
  FAIL\t<k> of <m> quotes do not match; <page> not written
  FAIL\t<p> claim problems; <page> not written
  FAIL\t<reason>       the view or claims.json missing, not valid JSON or the wrong shape; a bad stem
  OK\t<m> quotes in <c> claims match[; votes: <s> survived, <r> refuted, <u> unverified]\t<page path or "check only">
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

VERSION = "0.6.1"

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
CLAIM = {"claim": str, "status": str, "note?": str, "quotes": list, "id?": str}
DISAGREEMENT = {"topic": str, "quotes": list}
QUOTE = {"file": str, "line": int, "end?": int, "text": str, "translation?": str, "ja?": str, "mark?": str, "who?": str,
         "support?": str, "qualifier?": dict}
QUALIFIER = {"file": str, "line": int, "end?": int, "text": str}  # the source's own sentence that limits the claim
SUPPORT = ("full", "partial", "none", "contradicts")
# claims.json (report mode) is a list of CLAIMED, each with its verifiers' votes.
CLAIMED = {"id": str, "claim": str, "quote": str, "url": str, "label": str, "importance": str, "votes?": list, "verdict?": str,
           "standing?": str, "venue?": str}
VOTE = {"refuted": bool, "confidence": str, "evidence": str, "counter_source?": str, "checked?": str, "withheld?": str}
STANDING = ("open-post", "reviewed", "unknown")
INDEX_HEAD = ("name", "url", "final", "fetched", "published", "modified", "extraction", "version", "marks", "files")
IMPORTANCE = ("central", "supporting", "tangential")
VERDICTS = ("survived", "refuted", "unverified")
MAX_CENTRAL, MAX_CITED, MAX_VOTES = 10, 40, 3
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
.sourced,.survived{color:var(--accent)}.partial,.unverified{color:var(--partial)}.none,.refuted{color:var(--none)}
.votes{font-size:.9rem}.votes p{margin:.3rem 0}.votes ul{margin:0;padding-left:1.2rem}
figure{margin:1rem 0;padding:1rem;background:var(--card);border:1px solid var(--line);border-radius:8px}
blockquote{margin:0;padding-left:.8rem;border-left:3px solid var(--accent);white-space:pre-wrap}
.who{font-weight:600;margin:0 0 .5rem}
.tr{margin:.6rem 0 0}
.tag{font-size:.75rem;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 .35em}
.when{color:var(--muted)}
.limit{margin:.6rem 0 0;font-size:.9rem}
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
    """An evidence view (extracts.json or extracts-<stem>.json) and its quotes as (where, quote) pairs;
    raises ValueError naming the first problem."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        raise ValueError(f"cannot read {path}") from None
    except ValueError as e:
        raise ValueError(f"{path.name} is not valid JSON: {e}") from None
    need(data, TOP, path.name)
    if any(type(u) is not str for u in data.get("unreached", [])):
        raise ValueError(f"{path.name}: unreached must hold strings only")
    quotes = []
    for key, name, spec in (("claims", "claim", CLAIM), ("disagreements", "disagreement", DISAGREEMENT)):
        for i, item in enumerate(data.get(key, []), 1):
            need(item, spec, f"{name} {i}")
            if name == "claim" and item["status"] not in STATUS:
                raise ValueError(f'claim {i}: unknown status "{clean(item["status"], 40)}"')
            for j, q in enumerate(item["quotes"], 1):
                where = f"{name} {i} quote {j}"
                need(q, QUOTE, where)
                if "support" in q and q["support"] not in SUPPORT:
                    raise ValueError(f"{where}: support must be {', '.join(SUPPORT[:-1])} or {SUPPORT[-1]}")
                quotes.append((where, q))
                if "qualifier" in q:
                    need(q["qualifier"], QUALIFIER, f"{where} qualifier")
                    quotes.append((f"{where} qualifier", q["qualifier"]))
    return data, quotes


def load_claims(path):
    """claims.json as {id: claim}, or None when the topic has none; raises ValueError naming the first problem."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        raise ValueError(f"cannot read {path}") from None
    except ValueError as e:
        raise ValueError(f"claims.json is not valid JSON: {e}") from None
    if type(data) is not list:
        raise ValueError("claims.json must be a list")
    claims = {}
    for i, c in enumerate(data, 1):
        need(c, CLAIMED, f"claims.json item {i}")
        where = f'claims.json {clean(c["id"], 40)}'
        if c["id"] in claims:
            raise ValueError(f"{where}: the id appears twice")
        if c["importance"] not in IMPORTANCE or c.get("verdict", VERDICTS[0]) not in VERDICTS:
            raise ValueError(f"{where}: importance must be one of {', '.join(IMPORTANCE)}; verdict one of {', '.join(VERDICTS)}")
        if c.get("standing", STANDING[0]) not in STANDING:
            raise ValueError(f"{where}: standing must be one of {', '.join(STANDING)}")
        for j, v in enumerate(c.setdefault("votes", []), 1):  # a claim never sent to verifiers has none
            need(v, VOTE, f"{where} vote {j}")
            if "checked" in v and not re.fullmatch(r"\d{4}-\d\d-\d\d", v["checked"]):
                raise ValueError(f"{where} vote {j}: checked must be a date written YYYY-MM-DD")
        claims[c["id"]] = c
    return claims


def verdict(votes):
    """The vote rule: 2 refutations kill a claim; one vote keeps it only if it holds and is not low in confidence;
    any other single vote or none leaves it unverified, never refuted."""
    if sum(v["refuted"] for v in votes) >= 2:
        return "refuted"
    if len(votes) == 1 and not votes[0]["refuted"] and str(votes[0].get("confidence")).lower() != "low":
        return "survived"
    return "unverified" if len(votes) < 2 else "survived"


def index_rows(src):
    """The rows of sources/index.tsv as dicts; rows of the wrong width are skipped; [] without the file."""
    try:
        lines = (src / "index.tsv").read_text(encoding="utf-8-sig", errors="replace").splitlines()[1:]
    except OSError:
        return []
    return [dict(zip(INDEX_HEAD, cells)) for cells in (line.split("\t") for line in lines) if len(cells) == len(INDEX_HEAD)]


def retracted_files(src):
    """The files in sources/ whose index row carries fetch.py's retracted mark; a later row for a name wins."""
    newest = {row["name"]: row for row in index_rows(src)}.values()
    return {f for row in newest if "retracted" in row["marks"].split(",") for f in row["files"].split(",")}


def claim_problems(claims, data, flagged=frozenset()):
    """Where the claims break the rules, as (where, reason) pairs: in the view, a sourced or partial claim whose quotes
    all come from retracted sources (marked so in the quote, or in sources/index.tsv: flagged); with claims.json, every
    claim's votes and verdict, and for the claims the view cites a known id, a quote from a source that is not
    retracted for each central one, at most MAX_CENTRAL central ones and at most MAX_CITED in all."""
    def retracted(q):
        return q["file"] in flagged or bool(re.search(r"\bretracted\b", q.get("mark") or "", re.I))
    out = []
    for i, c in enumerate(data["claims"], 1):
        full = [q for q in c["quotes"] if q.get("support") == "full"]
        if STATUS[c["status"]] in ("sourced", "partial") and c["quotes"] and all(map(retracted, c["quotes"])):
            out.append((f"claim {i}", "every quote comes from a retracted source; a retracted work backs no claim"))
        elif STATUS[c["status"]] == "sourced" and not full:
            out.append((f"claim {i}", "sourced, but no quote gives full support; run the support pass"))
        elif STATUS[c["status"]] == "sourced" and all(map(retracted, full)):
            out.append((f"claim {i}", "sourced, but only quotes from retracted sources give full support"))
    if claims is None:
        return out
    cited = {}
    for i, c in enumerate(data["claims"], 1):
        if "id" not in c:
            continue
        if c["id"] in claims:
            cited.setdefault(c["id"], []).extend(c["quotes"])
        else:
            out.append((f"claim {i}", f'id "{clean(c["id"], 40)}" is not in claims.json'))
    central = [i for i in cited if claims[i]["importance"] == "central"]
    if len(central) > MAX_CENTRAL:
        out.append(("claims.json", f"{len(central)} central claims in this view (limit {MAX_CENTRAL})"))
    if len(cited) > MAX_CITED:
        out.append(("claims.json", f"{len(cited)} claims in this view (limit {MAX_CITED})"))
    for c in claims.values():
        where = f'claims.json {clean(c["id"], 40)}'
        if c["id"] in central and not cited[c["id"]]:
            out.append((where, "central, but this view gives it no quote"))
        elif c["id"] in central and all(map(retracted, cited[c["id"]])):
            out.append((where, "central, but every quote in this view comes from a retracted source"))
        if len(c["votes"]) > MAX_VOTES:
            out.append((where, f"{len(c['votes'])} votes (limit {MAX_VOTES})"))
        if (c["votes"] or "verdict" in c) and c.get("verdict") != verdict(c["votes"]):
            out.append((where, f'verdict {c.get("verdict", "missing")}, but the votes give {verdict(c["votes"])}'))
    return out


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
    """Text as compared: per line a leading timestamp and list marker dropped, then every whitespace character and
    soft hyphen removed."""
    return "".join("".join(_LEAD.sub("", line) for line in text.split("\n")).replace("\U000000ad", "").split())


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


def source_dates(src):
    """{file in sources/: "published ...; modified ...; fetched ...; archived copy of ...; version ...; retracted"} from
    sources/index.tsv. A PDF's dates are the file's own, so they read "created"; an archived copy's published cell ends
    with "archived <snapshot date>"; a later row for a name wins; {} without the index."""
    out = {}
    for row in index_rows(src):
        made = "created" if row["extraction"] in ("pdftotext", "ocr") else "published"
        stated, _, archived = row["published"].partition("archived ")
        stated = stated.strip(" ,") or "-"
        parts = [f"{made} {stated}"] * (stated != "-")
        parts += [f"modified {row['modified']}"] * (row["modified"] not in ("-", stated))
        parts += [f"fetched {row['fetched'][:10]}"] + [f"archived copy of {archived.strip()}"] * bool(archived.strip())
        parts += [f"version {row['version']}"] * (row["version"] != "-")
        parts += ["retracted"] * ("retracted" in row["marks"].split(","))
        out.update({f: "; ".join(parts) for f in row["files"].split(",")})
    return out


def quote_html(src, q, when=""):
    """One quote: who, the text, its translation, the source link, mark and dates, and the numbered lines around it."""
    first, last = q["line"], q.get("end", q["line"])
    lo = max(first - 5, 1)
    rows = []
    for n, line in enumerate(read_lines(src / q["file"])[lo - 1:last + 5], lo):
        row = f'<span class="n">{n}</span>{esc(line)}'
        rows.append(f"<mark>{row}</mark>" if first <= n <= last else row)
    context = "\n".join(rows)
    loc = f"sources/{q['file']}:{first}" + (f"-{last}" if last != first else "")
    mark = f' <span class="tag">{esc(q["mark"])}</span>' if q.get("mark") else ""
    mark += f' <span class="tag">support: {esc(q["support"])}</span>' if q.get("support") else ""
    tr = q.get("translation", q.get("ja"))
    out = ["<figure>"]
    if q.get("who"):
        out.append(f'<p class="who">{esc(q["who"])}</p>')
    out.append(f"<blockquote>{esc(q['text'])}</blockquote>")
    if tr:
        out.append(f'<p class="tr"><span class="tag">translation</span> {esc(tr)}</p>')
    lim = q.get("qualifier")
    if lim:
        out.append(f'<p class="limit"><span class="tag">limit</span> {esc(lim["text"])} (sources/{esc(lim["file"])}:{lim["line"]})</p>')
    when = f' <span class="when">{esc(when)}</span>' if when else ""
    out.append(f'<figcaption><a href="sources/{esc(urllib.parse.quote(q["file"]))}">{esc(loc)}</a>{mark}{when}</figcaption>')
    out.append(f"<details><summary>context</summary><pre>{context}</pre></details></figure>")
    return "\n".join(out)


def link(url, text):
    """A link for http and https URLs only; anything else stays plain text."""
    return f'<a href="{esc(url)}">{esc(text)}</a>' if re.match(r"https?://", url) else esc(url)


def votes_html(c):
    """A claims.json claim: its verdict, importance, label and original URL, then each verifier's vote."""
    v = c.get("verdict")
    head = f'<span class="status {v}">{v}</span>' if v else '<span class="status">not checked</span>'
    rows = []
    for vote in c["votes"]:
        src = vote.get("counter_source")
        checked = f', checked {esc(vote["checked"])}' if vote.get("checked") else ""
        closed = f'; withheld: {esc(vote["withheld"])}' if vote.get("withheld") else ""
        rows.append(f'<li>{"refuted" if vote["refuted"] else "held"} ({esc(vote["confidence"])}{checked}): {esc(vote["evidence"])}{closed}'
                    + (f" ({link(src, 'counter source')})" if src else "") + "</li>")
    known = "".join(f"{esc(c[k])}, " for k in ("standing", "venue") if c.get(k))
    return (f'<div class="votes"><p>Votes: {head} {esc(c["importance"])}, {esc(c["label"])}, {known}{link(c["url"], "original")}</p>'
            + (f'<ul>{"".join(rows)}</ul>' if rows else "") + "</div>")


def page(src, data, claims=None):
    """The evidence page: the question, each claim with its votes and quotes, then disagreements and what was not reached."""
    dates = source_dates(src)
    body = [f"<h1>{esc(data['title'])}</h1>",
            f'<p class="lead">Question: {esc(data["question"])}</p>',
            f'<p class="lead">Stopped: {esc(data["stopped"])}</p>']
    for c in data["claims"]:
        status = STATUS[c["status"]]
        body.append(f'<section><h2>{esc(c["claim"])} <span class="status {status}">{status}</span></h2>')
        if c.get("note"):
            body.append(f'<p class="note">{esc(c["note"])}</p>')
        if claims and c.get("id") in claims:
            body.append(votes_html(claims[c["id"]]))
        body += [quote_html(src, q, dates.get(q["file"], "")) for q in c["quotes"]]
        body.append("</section>")
    if data.get("disagreements"):
        body.append("<section><h2>Disagreements</h2>")
        for d in data["disagreements"]:
            body.append(f"<h3>{esc(d['topic'])}</h3>")
            body += [quote_html(src, q, dates.get(q["file"], "")) for q in d["quotes"]]
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
    ap.add_argument("topic_dir", help="topic folder holding the evidence view and sources/")
    ap.add_argument("stem", nargs="?", help="a report's stem, such as 2026-11-01: check extracts-<stem>.json and "
                                             "write evidence-<stem>.html")
    ap.add_argument("--check", action="store_true", help="only check the quotes; do not write the page")
    args = ap.parse_args(argv)
    topic = pathlib.Path(args.topic_dir).expanduser()  # a quoted ~ reaches the script unexpanded
    if args.stem is not None and not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.-]*", args.stem):
        print(f"FAIL\tbad stem: {clean(args.stem, 40)}")
        return 1
    view, out = ((f"extracts-{args.stem}.json", f"evidence-{args.stem}.html") if args.stem
                 else ("extracts.json", "report.html"))
    out = topic / out
    try:
        data, quotes = load(topic / view)
        claims = load_claims(topic / "claims.json")
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
    problems = claim_problems(claims, data, retracted_files(src))
    for where, reason in problems:
        print(f"CLAIM\t{where}\t{reason}")
    if bad:
        print(f"FAIL\t{bad} of {len(quotes)} quotes do not match; {out.name} not written")
    if problems:
        print(f"FAIL\t{len(problems)} claim problems; {out.name} not written")
    if bad or problems:
        return 1
    if not args.check:
        out.write_text(page(src, data, claims), encoding="utf-8")
    tally = ""
    cited = {c["id"] for c in data["claims"] if claims and c.get("id") in claims}
    if cited:
        n = [sum(claims[i].get("verdict") == v for i in cited) for v in VERDICTS]
        tally = "; votes: {} survived, {} refuted, {} unverified".format(*n)
    print(f"OK\t{len(quotes)} quotes in {len(data['claims'])} claims match{tally}\t{'check only' if args.check else out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
