"""Replay the support pass on fixed inputs: the quotes and archived sources of a delivered view stay as they are, so
a change to the support reader's brief (skills/search/references/briefs.md) is the only thing a second run measures.

Usage:
  python -I dev/replay_support.py build <topic_dir> <view file> <brief out> [--limit N]
  python -I dev/replay_support.py score <topic_dir> <view file> <reply file> [--sent N]

build fills the support reader brief, as briefs.md words it today, with the view's quotes sorted by file (the first
N with --limit) and writes it to <brief out>. Send it to one phro-search:local-reader and save the reply as it came.
score reads that reply against the ratings the view holds and prints, tab-separated:
  CHANGED <claim> <file>:<line> <rating in the view> <rating in the reply>
  MISSING <claim> <file>:<line>                 a quote of the brief the reply has no line for
  REPLAY <n> quotes sent <r> rated <a> of <c> agree with the view <g> with a gist
--sent is the --limit the brief was built with. c counts the rated quotes that the view also rates. A claim is named by its id, else by its number in the view.
"""
import argparse, json, re, sys
from pathlib import Path

BRIEFS_MD = Path(__file__).resolve().parents[1] / "skills" / "search" / "references" / "briefs.md"
SLOT = '<claim id or number>. <claim text> | <file>:<line> "<quote>"'
RATINGS = ("full", "partial", "none", "contradicts")


def quotes(view, limit=None):
    """(claim name, claim text, quote) of every located quote in the view, sorted by file and line."""
    data = json.loads(Path(view).read_text(encoding="utf-8-sig"))
    rows = [(str(c.get("id") or n), c["claim"], q) for n, c in enumerate(data["claims"], 1) for q in c.get("quotes") or []]
    return sorted(rows, key=lambda r: (r[2]["file"], r[2]["line"], r[0]))[:limit]


def build(a):
    m = re.search(r"```\n(You are a support reader\..*?)\n```", BRIEFS_MD.read_text(encoding="utf-8"), re.S)
    if not m or SLOT not in m.group(1):
        raise ValueError("briefs.md: the support reader brief or its quote slot was not found")
    rows = quotes(a.view, a.limit)
    listed = "\n".join(f'{name}. {text} | {q["file"]}:{q["line"]} "{q["text"]}"' for name, text, q in rows)
    brief = m.group(1).replace("<topic>", Path(a.topic).expanduser().as_posix()).replace(SLOT, listed)
    Path(a.out).write_text(brief, encoding="utf-8", newline="\n")
    print(f"BUILT\t{len(rows)} quotes\t{len({q['file'] for _, _, q in rows})} files\t{a.out}")
    return 0


def score(a):
    reply = {}
    for line in Path(a.reply).read_text(encoding="utf-8-sig", errors="replace").splitlines():
        cells = [c.strip() for c in line.split("\t")]
        if len(cells) >= 3 and cells[2].lower() in RATINGS:
            reply[(cells[0].rstrip("."), cells[1])] = (cells[2].lower(), len(cells) > 5 and cells[5] not in ("", "-"))
    rows = quotes(a.view)
    sent = len(rows) if a.sent is None else a.sent
    rated = agree = both = gists = 0
    for name, _, q in rows[:sent]:
        got = reply.get((name, f'{q["file"]}:{q["line"]}'))
        if got is None:
            print(f'MISSING\t{name}\t{q["file"]}:{q["line"]}')
            continue
        rated += 1
        gists += got[1]
        if q.get("support"):
            both += 1
            agree += got[0] == q["support"]
            if got[0] != q["support"]:
                print(f'CHANGED\t{name}\t{q["file"]}:{q["line"]}\t{q["support"]}\t{got[0]}')
    print(f"REPLAY\t{sent} quotes sent\t{rated} rated\t{agree} of {both} agree with the view\t{gists} with a gist")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="replay_support.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the support reader brief for a view's quotes")
    b.add_argument("topic")
    b.add_argument("view")
    b.add_argument("out")
    b.add_argument("--limit", type=int, help="only the first N quotes")
    s = sub.add_parser("score", help="compare a saved reply with the view's ratings")
    s.add_argument("topic")
    s.add_argument("view")
    s.add_argument("reply")
    s.add_argument("--sent", type=int, help="the --limit the brief was built with")
    a = p.parse_args(argv)
    try:
        return {"build": build, "score": score}[a.cmd](a)
    except (OSError, ValueError, KeyError) as e:
        print(f"FAIL\t{getattr(e, 'strerror', None) or e}")
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
