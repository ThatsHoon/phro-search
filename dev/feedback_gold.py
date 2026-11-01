"""The items users said a delivered result missed, as gold-item candidates for the eval sets (R16, R1).

Usage:
  python -I dev/feedback_gold.py <root> [--since YYYY-MM-DD]

It reads <root>/*/log.md (the topic root, such as ~/research) for normalized feedback lines,
  feedback: fit=<yes|partly|no>; missing=<item | item, or none>
and prints, tab-separated, one line per missing item:
  GOLD <topic> <date> <mode> <fit> <item>
where date is the log section's date and mode the last brief: line before it. A feedback line in an older,
unnormalized shape gets a "# <topic>/log.md:<line>: feedback line not normalized" note; a last "#" line
counts the feedback lines by fit. Each GOLD item is a candidate for the eval set of its mode: add it by hand
as a gold item, and change a reference or a default only when an eval run passes its threshold. It only reads.
"""
import argparse, re, sys
from pathlib import Path

NORMAL = re.compile(r"^feedback: fit=(yes|partly|no); missing=(.*)$")
SECTION = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b")
MODE = re.compile(r"^brief: mode=([\w-]+)")


def scan(log, topic, since):
    """(gold rows, fits, notes) of one topic's log.md."""
    rows, fits, notes, day, mode = [], [], [], "", "-"
    for n, line in enumerate(log.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if m := SECTION.match(line):
            day = m.group(1)
        elif m := MODE.match(line):
            mode = m.group(1)
        elif line.startswith("feedback:"):
            m = NORMAL.match(line.strip())
            if not m:
                notes.append(f"# {topic}/log.md:{n}: feedback line not normalized")
                continue
            if since and day < since:
                continue
            fits.append(m.group(1))
            items = [x.strip() for x in m.group(2).split("|")]
            rows += [(topic, day or "-", mode, m.group(1), x) for x in items if x and x.lower() != "none"]
    return rows, fits, notes


def main(argv=None):
    p = argparse.ArgumentParser(prog="feedback_gold.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("root", help="topic root, such as ~/research")
    p.add_argument("--since", metavar="YYYY-MM-DD", help="only feedback logged on or after this day")
    a = p.parse_args(argv)
    root = Path(a.root).expanduser()
    if not root.is_dir():
        print(f"FAIL\t{root}\tnot a folder")
        return 1
    rows, fits, notes = [], [], []
    for log in sorted(root.glob("*/log.md")):
        r, f, n = scan(log, log.parent.name, a.since)
        rows, fits, notes = rows + r, fits + f, notes + n
    for row in rows:
        print("GOLD\t" + "\t".join(" ".join(x.split()) for x in row))
    for note in notes:
        print(note)
    print(f"# {len(fits)} feedback lines: {fits.count('yes')} yes, {fits.count('partly')} partly, {fits.count('no')} no; "
          f"{len(rows)} gold items")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
