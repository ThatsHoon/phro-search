"""Compare pdftotext's reading order with its -layout mode on the PDFs of existing topics.

Usage:
  python -I dev/pdf_modes.py <topic_dir> [<topic_dir> ...]

For every sources/*.pdf it prints, tab-separated:
  PDF <topic>/<file> hyphen-breaks <layout> <reading> aligned-rows <layout> <reading>
then, over the quotes in each topic's extracts*.json that point at a PDF's text copy (<name>.txt or
<name>.layout.txt beside <name>.pdf):
  QUOTES <n> quotes on PDF text; <e> use the ellipsis; <k> of those read as one run in reading order;
         <x> without the ellipsis are not found in reading order
and a TOTAL line. Run it before switching to reading order and before deciding whether quotes still
need the ellipsis rule for columns (formats.md). It needs pdftotext and writes nothing.

hyphen-breaks: a word split at a line end ("evalu-" then "ation"); in -layout the right column may follow it.
               Reading order joins every such word, which also drops the hyphen of a compound split there
               (well-known becomes wellknown), so the layout count is also the count of joins to check.
aligned-rows: lines with two or more gaps of 3 or more spaces, which is how table rows (and, in -layout,
              two columns side by side) look.
"""
import json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HYPHEN = re.compile(r"[A-Za-z]{2,}-(?=[ \t]*\n|[ \t]{2,}\S)")  # at a line end, or before a column gap
ALIGNED = re.compile(r"\S {3,}\S.* {3,}\S")
ELLIPSIS = "\U00002026"
# report.py's _LEAD: a caption timestamp, then a list marker (a bullet glyph, or -, *, +, 1. or 1) before whitespace).
LEAD = re.compile(r"^\s*(?:\[(?:\d+:)?\d+:\d\d\])?\s*(?:[\U000000b7\U00002022\U00002023\U00002043\U000025a0\U000025a1"
                  r"\U000025aa\U000025c6\U000025cb\U000025cf\U000025e6\U000030fb]|(?:[-*+]|\d+[.)])(?!\S))?")


def hyphen_breaks(text):
    return len(HYPHEN.findall(text))


def aligned_rows(text):
    return sum(bool(ALIGNED.search(line)) for line in text.split("\n"))


def norm(text):
    """As report.py compares: a leading timestamp or list marker dropped per line, then all whitespace removed."""
    return "".join("".join(LEAD.sub("", line) for line in text.split("\n")).split())


def pdftotext(pdf, layout):
    exe = shutil.which("pdftotext")
    if not exe:
        sys.exit("pdftotext is not on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.txt"
        subprocess.run([exe, *(["-layout"] if layout else []), "-enc", "UTF-8", str(pdf), str(out)],
                       capture_output=True, timeout=900, check=False)
        return out.read_text(encoding="utf-8", errors="replace") if out.is_file() else ""


def measure(topic):
    """Per-PDF lines and the quote counts of one topic folder."""
    lines, reading = [], {}
    for pdf in sorted((topic / "sources").glob("*.pdf")):
        lay, rd = pdftotext(pdf, True), pdftotext(pdf, False)
        reading[pdf.stem] = norm(rd)
        lines.append(f"PDF\t{topic.name}/{pdf.name}\thyphen-breaks\t{hyphen_breaks(lay)}\t{hyphen_breaks(rd)}"
                     f"\taligned-rows\t{aligned_rows(lay)}\t{aligned_rows(rd)}")
    n = e = k = x = 0
    for extracts in sorted(topic.glob("extracts*.json")):
        try:
            data = json.loads(extracts.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        for item in data.get("claims", []) + data.get("disagreements", []):
            for q in item.get("quotes", []):
                name = Path(str(q.get("file", ""))).name
                stem = re.sub(r"(?:\.layout)?\.txt$", "", name)
                if stem == name or stem not in reading:  # not a PDF's text copy
                    continue
                n += 1
                text = str(q.get("text", ""))
                if ELLIPSIS in text:
                    e += 1
                    k += norm(re.sub("-\\s*" + ELLIPSIS, "", text).replace(ELLIPSIS, " ")) in reading[stem]
                else:
                    x += norm(text) not in reading[stem]
    return lines, (n, e, k, x)


def main(argv):
    if not argv:
        sys.exit(__doc__)
    def tally(c):
        return (f"{c[0]} quotes on PDF text; {c[1]} use the ellipsis; {c[2]} of those read as one run in reading order; "
                f"{c[3]} without the ellipsis are not found in reading order")
    total = [0, 0, 0, 0]
    for arg in argv:
        lines, counts = measure(Path(arg).expanduser())
        if lines:
            print("\n".join(lines))
        print(f"QUOTES\t{Path(arg).name}\t{tally(counts)}")
        total = [a + b for a, b in zip(total, counts)]
    print(f"TOTAL\t{tally(total)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
