"""dev/pdf_modes.py, and pdftotext's two modes on a two-column page (run only where pdftotext is installed)."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests._load import load

modes = load("dev/pdf_modes.py")
fetch = load("scripts/fetch.py")
ELL = "\U00002026"
LEFT = [f"Left column sentence {i} runs on with plain words" for i in range(1, 21)]
LEFT[3], LEFT[4] = "Left column sentence 4 ends with a split evalu-", "ation of the method on the test set"
RIGHT = [f"Right column sentence {i} talks about other work" for i in range(1, 21)]


def two_column_pdf(left, right):
    """A one-page PDF with two columns of Helvetica text, written by hand so no PDF library is needed."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    parts = [f"BT /F1 10 Tf 13 TL {x} 740 Td " + " ".join(f"({esc(t)}) Tj T*" for t in lines) + " ET"
             for x, lines in ((56, left), (320, right))]
    content = "\n".join(parts).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
            b" /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


class MetricTest(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(modes.hyphen_breaks("a split evalu-\nation here\nwell-known\nX-\nRay"), 1)
        self.assertEqual(modes.aligned_rows("a    b    c\nplain line\ncol one     col two"), 1)
        self.assertEqual(modes.norm("[12:34] - first\n2) second line"), "firstsecondline")


@unittest.skipUnless(shutil.which("pdftotext"), "pdftotext is not installed")
class TwoColumnTest(unittest.TestCase):
    """Why fetch.py quotes the reading-order text: -layout puts both columns on every line."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.pdf = self.tmp / "two.pdf"
        self.pdf.write_bytes(two_column_pdf(LEFT, RIGHT))

    def test_layout_mixes_columns_and_reading_order_does_not(self):
        work = self.tmp / "work"
        work.mkdir()
        reading, layout = fetch.pdf_text(work, self.pdf.read_bytes())
        first = next(line for line in layout.splitlines() if line.strip())
        self.assertIn("Left column sentence 1", first)
        self.assertIn("Right column sentence 1", first)
        self.assertLess(reading.index("Left column sentence 20"), reading.index("Right column sentence 1"))
        quote = modes.norm(f"{LEFT[0]} {LEFT[1]}")
        self.assertIn(quote, modes.norm(reading))
        self.assertNotIn(quote, modes.norm(layout))
        self.assertEqual((modes.hyphen_breaks(layout), modes.hyphen_breaks(reading)), (1, 0))

    def test_measure_counts_quotes_that_needed_the_ellipsis(self):
        topic = self.tmp / "topic"
        (topic / "sources").mkdir(parents=True)
        shutil.copy(self.pdf, topic / "sources" / "paper.pdf")
        quotes = [{"file": "paper.txt", "line": 1, "text": f"{LEFT[0]} {ELL} {LEFT[1]}"},
                  {"file": "paper.txt", "line": 1, "text": LEFT[2]},
                  {"file": "other.md", "line": 1, "text": f"a {ELL} b"}]
        data = {"title": "t", "question": "q", "stopped": "s", "claims": [{"claim": "c", "status": "sourced", "quotes": quotes}]}
        (topic / "extracts.json").write_text(json.dumps(data), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            modes.main([str(topic)])
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0].split("\t")[:2], ["PDF", "topic/paper.pdf"])
        self.assertEqual(lines[0].split("\t")[2:5], ["hyphen-breaks", "1", "0"])
        self.assertEqual(lines[-1], "TOTAL\t2 quotes on PDF text; 1 use the ellipsis; 1 of those read as one run in reading order")


if __name__ == "__main__":
    unittest.main()
