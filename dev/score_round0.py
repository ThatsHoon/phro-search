"""Round-0 recall (R1, R4, R8 in docs/structure-review.md): gold recall of a topic's map and index, and the share of
searcher URLs that fetch.py archived as the original itself.

Usage:
  python -I dev/score_round0.py <gold file> <topic folder> [<topic folder> ...] [--found TEXT]

The gold file lists the canonical works the owner marked, one work per line: a DOI (bare, doi: or a doi.org URL),
an OpenAlex W id, or a title. Tab-separated alternatives on one line name the same work, and any of them counts
("W2041012399<TAB>Kuhlthau ISP model"). Blank lines and lines starting with # are skipped.

A gold work is a hit when a row of map.md's Sources table or of sources/index.tsv holds it: a DOI anywhere in
the row (an arXiv DOI, 10.48550/arXiv.<id>, also as an arXiv URL or an arxiv-<id> file name), a W id as a word,
or a title whose words of three letters or more (minus a few stop words) all appear in the row. A DOI is the
surest key: map rows name works briefly ("Bates 1989, berrypicking"), so check MISS lines by hand.

Searcher URLs are the Original URL cells of the map's Sources rows (--found keeps only rows whose Found in
cell contains TEXT, case-insensitive). One counts as archived as the original when sources/index.tsv has a row
with that URL as asked or as read, without the archived-copy mark (a dead page read from Wayback), and the map's
label (its first word, so "summary (survey)" is summary) is not summary. A wall or a failed fetch leaves no index
row. A topic without index.tsv (older topics) counts a row whose Files cell names a file.

Output, tab-separated, per topic:
  GOLD <topic> <HIT|MISS> <work> <map: <found in> | index: <name> | ->
  RECALL <topic> <k>/<n> <pct>
  RECALL-BY <topic> <found in> <k>/<n>          (per Found in value; index only for hits only the index has)
  NOT <topic> <summary|archived-copy|not fetched> <url>
  ARCHIVED <topic> <k>/<n> <pct>
  ARCHIVED-BY <topic> <found in> <k>/<n>
and over several topics (the repeats of one arm), MEAN <n> topics recall <pct> archived <pct>. It only reads.
"""
import argparse, csv, re, sys, urllib.parse
from pathlib import Path

STOP = {"the", "and", "for", "with", "from", "into", "via", "its", "are", "our", "using", "toward", "towards", "about",
        "over", "under", "between", "this", "that", "their", "not"}
DOI = re.compile(r"10\.\d{4,9}/\S+", re.I)
WID = re.compile(r"^(?:https?://openalex\.org/)?(w\d+)$", re.I)
URL = re.compile(r"https?://[^\s|)>\]]+", re.I)


def words(text):
    return re.findall(r"[^\W_]+", text.lower())


def key(item):
    """(kind, value) of one gold alternative: doi, wid or title."""
    item = item.strip()
    if m := WID.match(item):
        return "wid", m.group(1).lower()
    if m := DOI.search(urllib.parse.unquote(item)):
        return "doi", m.group(0).lower().rstrip(".,;")
    return "title", [w for w in words(item) if len(w) >= 3 and w not in STOP]


def read_gold(path):
    """[(shown text, [keys])] for each work of the gold file."""
    out = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        alts = [x.strip() for x in line.split("\t") if x.strip()]
        keys = [key(x) for x in alts]
        shown = " | ".join(v if k == "doi" else (v.upper() if k == "wid" else a) for a, (k, v) in zip(alts, keys))
        out.append((shown, keys))
    return out


def hit(keys, text):
    """Does a row's text (lowercase, URL-decoded) hold one of a work's keys?"""
    toks = set(words(text))
    for kind, v in keys:
        if kind == "doi":
            if v in text:
                return True
            if m := re.fullmatch(r"10\.48550/arxiv\.(.+)", v):
                if any(f"{p}{m.group(1)}" in text for p in ("arxiv.org/abs/", "arxiv.org/pdf/", "arxiv.org/html/", "arxiv-")):
                    return True
        elif kind == "wid":
            if re.search(rf"(?<![a-z0-9]){v}(?![0-9])", text):
                return True
        elif v and set(v) <= toks:
            return True
    return False


def norm_url(u):
    u = urllib.parse.unquote(u.strip()).lower().split("#", 1)[0]
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^(www\.|dx\.)", "", u)
    return u.rstrip("/")


def map_rows(path):
    """Rows of the Sources table of map.md as dicts with label, work, files, url, found and text."""
    rows, head, inside = [], None, False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            inside = "source" in line.lower()
            head = None
            continue
        if not inside or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if head is None:
            head = [c.lower() for c in cells]
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        get = lambda *names: next((cells[i] for i, h in enumerate(head) if i < len(cells) and any(n in h for n in names)), "")
        url = URL.search(get("url"))
        rows.append({"label": (re.findall(r"[\w-]+", get("label").lower()) or [""])[0], "work": get("work"), "files": get("files"), "url": url.group(0) if url else "",
                     "found": " ".join(get("found").split()) or "-", "text": urllib.parse.unquote(line).lower()})
    return rows


def index_rows(path):
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    for r in rows:
        r["text"] = urllib.parse.unquote(" ".join(r.get(k) or "" for k in ("name", "url", "final", "files"))).lower()
    return rows


def pct(k, n):
    return f"{k}/{n} {100 * k / n:.1f}%" if n else f"{k}/{n}"


def score(gold, topic, found):
    """Print one topic's lines; (recall, archived share) as fractions, or None when the map is missing."""
    name = topic.name
    if not (topic / "map.md").is_file():
        print(f"FAIL\t{topic}\tno map.md")
        return None
    rows = map_rows(topic / "map.md")
    idx_path = topic / "sources" / "index.tsv"
    idx = index_rows(idx_path) if idx_path.is_file() else None
    if idx is None:
        print(f"# {name}: no sources/index.tsv; a row counts as archived when its Files cell names a file")
    hits, by = 0, {}
    for shown, keys in gold:
        groups = sorted({r["found"] for r in rows if hit(keys, r["text"])})
        inx = [r["name"] for r in idx or [] if hit(keys, r["text"])]
        where = "map: " + "; ".join(groups) if groups else ("index: " + inx[0] if inx else "-")
        hits += bool(groups or inx)
        for g in groups or (["index only"] if inx else []):
            by[g] = by.get(g, 0) + 1
        print("\t".join(["GOLD", name, "HIT" if groups or inx else "MISS", shown, where]))
    print(f"RECALL\t{name}\t{pct(hits, len(gold))}")
    for g in sorted(by):
        print(f"RECALL-BY\t{name}\t{g}\t{by[g]}/{len(gold)}")
    seen = {}
    for r in idx or []:
        for col in ("url", "final"):
            if r.get(col):
                seen.setdefault(norm_url(r[col]), []).append(r)
    urls = [r for r in rows if r["url"] and (not found or found.lower() in r["found"].lower())]
    good, groups = 0, {}
    for r in urls:
        if r["label"] == "summary":
            why = "summary"
        elif idx is None:
            why = None if re.search(r"\w\.\w", r["files"]) else "not fetched"
        else:
            match = seen.get(norm_url(r["url"]), [])
            if any("archived-copy" not in (m.get("marks") or "") for m in match):
                why = None
            else:
                why = "archived-copy" if match else "not fetched"
        g = groups.setdefault(r["found"], [0, 0])
        g[1] += 1
        if why:
            print(f"NOT\t{name}\t{why}\t{r['url']}")
        else:
            good += 1
            g[0] += 1
    print(f"ARCHIVED\t{name}\t{pct(good, len(urls))}")
    for g in sorted(groups):
        print(f"ARCHIVED-BY\t{name}\t{g}\t{groups[g][0]}/{groups[g][1]}")
    return hits / len(gold) if gold else 0.0, good / len(urls) if urls else 0.0


def main(argv=None):
    p = argparse.ArgumentParser(prog="score_round0.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("gold", help="gold file, one work per line")
    p.add_argument("topics", nargs="+", help="topic folders (the repeats of one arm)")
    p.add_argument("--found", metavar="TEXT", help="count only searcher URLs whose Found in cell contains TEXT")
    a = p.parse_args(argv)
    try:
        gold = read_gold(Path(a.gold).expanduser())
    except OSError as e:
        print(f"FAIL\t{a.gold}\t{e.strerror or e}")
        return 1
    if not gold:
        print(f"FAIL\t{a.gold}\tno gold works")
        return 1
    scores = [score(gold, Path(t).expanduser(), a.found) for t in a.topics]
    if None in scores:
        return 1
    if len(scores) > 1:
        r = sum(s[0] for s in scores) / len(scores)
        f = sum(s[1] for s in scores) / len(scores)
        print(f"MEAN\t{len(scores)} topics\trecall {100 * r:.1f}%\tarchived {100 * f:.1f}%")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
