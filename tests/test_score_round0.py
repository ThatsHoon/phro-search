"""dev/score_round0.py: gold recall of a round-0 map and the share of searcher URLs archived as originals (R1, R4, R8)."""
import contextlib, io, shutil, tempfile, unittest
from pathlib import Path

from tests._load import load

score = load("dev/score_round0.py")

MAP = """# map: info-seeking

## Brief
brief: mode=dig; object=information seeking models

## Sources
| Label | Work | Files | Original URL | Found in |
|---|---|---|---|---|
| paper | Bates 1989, berrypicking | bates-1989-berrypicking.pdf, .txt | https://doi.org/10.1108/EB024320 | round 0, term search |
| paper | Kuhlthau 1991, ISP model | kuhlthau-1991-isp.pdf | https://www.example.org/kuhlthau.pdf | round 0, surveys |
| summary | Wikipedia, information seeking | wiki-information-seeking.md | https://en.wikipedia.org/wiki/Information_seeking | round 0, term search |
| paper | Leviathan 2023, speculative decoding | arxiv-2211.17192-speculative.md | https://arxiv.org/abs/2211.17192 | round 0, citation list |
| first-hand | Old blog post | old-post.md | http://dead.example.com/post/ | round 0, surveys |
| paper | Pirolli 1999, information foraging (unverified) | - | https://psycnet.apa.org/record/1999-11924-001 | round 0, surveys |

## Next leads
- Marchionini 1995
"""

INDEX = ("name\turl\tfinal\tfetched\tpublished\tmodified\textraction\tversion\tmarks\tfiles\n"
         "bates-1989-berrypicking\thttps://doi.org/10.1108/eb024320\thttps://repo.example.edu/bates.pdf\t2026-11-01T10:00:00Z\t-\t-\tpdftotext\taccepted\taccepted-copy\tbates-1989-berrypicking.pdf,bates-1989-berrypicking.txt\n"
         "kuhlthau-1991-isp\thttps://example.org/kuhlthau.pdf\thttps://example.org/kuhlthau.pdf\t2026-11-01T10:01:00Z\t-\t-\tpdftotext\t-\t-\tkuhlthau-1991-isp.pdf,kuhlthau-1991-isp.txt\n"
         "wiki-information-seeking\thttps://en.wikipedia.org/wiki/Information_seeking\thttps://en.wikipedia.org/wiki/Information_seeking\t2026-11-01T10:02:00Z\t-\t-\thtml\t-\t-\twiki-information-seeking.md\n"
         "arxiv-2211.17192-speculative\thttps://arxiv.org/abs/2211.17192\thttps://arxiv.org/html/2211.17192v2\t2026-11-01T10:03:00Z\t-\t-\tarxiv-html\tarXiv v2\tarxiv-html\tarxiv-2211.17192-speculative.md\n"
         "old-post\thttp://dead.example.com/post/\thttps://web.archive.org/web/2020id_/http://dead.example.com/post/\t2026-11-01T10:04:00Z\tarchived 2020-03-04\t-\thtml\t-\tarchived-copy\told-post.md\n"
         "dervin-1983\thttps://example.net/dervin.pdf\thttps://example.net/dervin.pdf\t2026-11-01T10:05:00Z\t-\t-\tpdftotext\t-\t-\tdervin-1983.pdf\n")

GOLD = """# canonical works of information seeking
10.1108/eb024320
doi:10.48550/arXiv.2211.17192
W2041012399\tKuhlthau ISP model
Information foraging
Dervin 1983
Marchionini Information seeking in electronic environments
"""


class Round0Test(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.topic = self.dir / "info-seeking"
        (self.topic / "sources").mkdir(parents=True)
        (self.topic / "map.md").write_text(MAP, encoding="utf-8")
        (self.topic / "sources" / "index.tsv").write_text(INDEX, encoding="utf-8")
        self.gold = self.dir / "gold.txt"
        self.gold.write_text(GOLD, encoding="utf-8")

    def run_score(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = score.main([str(self.gold), *args])
        return code, out.getvalue().splitlines()

    def test_recall_and_archive_share(self):
        code, out = self.run_score(str(self.topic))
        self.assertEqual(code, 0)
        self.assertIn("GOLD\tinfo-seeking\tHIT\t10.1108/eb024320\tmap: round 0, term search", out)
        self.assertIn("GOLD\tinfo-seeking\tHIT\t10.48550/arxiv.2211.17192\tmap: round 0, citation list", out)
        # a W id is matched only as text; the title on the same line finds the row
        self.assertIn("GOLD\tinfo-seeking\tHIT\tW2041012399 | Kuhlthau ISP model\tmap: round 0, surveys", out)
        self.assertIn("GOLD\tinfo-seeking\tHIT\tInformation foraging\tmap: round 0, surveys", out)
        self.assertIn("GOLD\tinfo-seeking\tHIT\tDervin 1983\tindex: dervin-1983", out)
        self.assertIn("GOLD\tinfo-seeking\tMISS\tMarchionini Information seeking in electronic environments\t-", out)
        self.assertIn("RECALL\tinfo-seeking\t5/6 83.3%", out)
        self.assertIn("RECALL-BY\tinfo-seeking\tround 0, citation list\t1/6", out)
        self.assertIn("RECALL-BY\tinfo-seeking\tround 0, surveys\t2/6", out)
        self.assertIn("RECALL-BY\tinfo-seeking\tround 0, term search\t1/6", out)
        self.assertIn("NOT\tinfo-seeking\tsummary\thttps://en.wikipedia.org/wiki/Information_seeking", out)
        self.assertIn("NOT\tinfo-seeking\tarchived-copy\thttp://dead.example.com/post/", out)
        self.assertIn("NOT\tinfo-seeking\tnot fetched\thttps://psycnet.apa.org/record/1999-11924-001", out)
        self.assertIn("ARCHIVED\tinfo-seeking\t3/6 50.0%", out)
        self.assertIn("ARCHIVED-BY\tinfo-seeking\tround 0, surveys\t1/3", out)
        self.assertIn("ARCHIVED-BY\tinfo-seeking\tround 0, citation list\t1/1", out)
        self.assertIn("ARCHIVED-BY\tinfo-seeking\tround 0, term search\t1/2", out)

    def test_found_filter_keeps_searcher_rows(self):
        _, out = self.run_score(str(self.topic), "--found", "surveys")
        self.assertIn("ARCHIVED\tinfo-seeking\t1/3 33.3%", out)
        self.assertIn("RECALL\tinfo-seeking\t5/6 83.3%", out)  # recall reads the whole map and index

    def test_mean_over_repeats(self):
        other = self.dir / "info-seeking-2"
        shutil.copytree(self.topic, other)
        (other / "sources" / "index.tsv").write_text(INDEX.split("\n", 1)[0] + "\n", encoding="utf-8")
        _, out = self.run_score(str(self.topic), str(other))
        self.assertIn("RECALL\tinfo-seeking-2\t4/6 66.7%", out)
        self.assertIn("ARCHIVED\tinfo-seeking-2\t0/6 0.0%", out)
        self.assertEqual(out[-1], "MEAN\t2 topics\trecall 75.0%\tarchived 25.0%")

    def test_older_topic_without_index(self):
        (self.topic / "sources" / "index.tsv").unlink()
        _, out = self.run_score(str(self.topic))
        self.assertIn("# info-seeking: no sources/index.tsv; a row counts as archived when its Files cell names a file", out)
        self.assertIn("ARCHIVED\tinfo-seeking\t4/6 66.7%", out)  # summary and the row without files are not

    def test_missing_map(self):
        code, out = self.run_score(str(self.dir / "nope"))
        self.assertEqual(code, 1)
        self.assertTrue(out[0].startswith("FAIL\t"))


if __name__ == "__main__":
    unittest.main()
