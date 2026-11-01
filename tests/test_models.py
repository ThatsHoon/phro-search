import contextlib, io, json, os, re, shutil, tempfile, unittest, urllib.error, urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests._load import load

m = load("scripts/models.py")
H, SHA, EV = "https://huggingface.co", "a" * 40, "abc123"
DOWN, UP, VS, DASH, CHECK, SUP1 = "\U00002b07", "\U00002b06", "\U0000fe0f", "\U00002014", "\U00002705", "\U000000b9"
DE, FR, KR, US = "\U0001f1e9\U0001f1ea", "\U0001f1eb\U0001f1f7", "\U0001f1f0\U0001f1f7", "\U0001f1fa\U0001f1f8"


def js(x):
    return json.dumps(x).encode()


# Responses in the shapes the live routes return (synthetic: the real boards list other people's models).

def a(repo, href=None, text=None):
    """A model cell as the Gradio boards render it."""
    return f'<a target="_blank" href="{href or H + "/" + repo}" style="text-decoration: underline;">{text or repo}</a>'


ASR_EN = ["Rank", "Rank \U00000394", "model", f"Average WER {DOWN}{VS}", f"RTFx {UP}{VS}{VS}", "AMI"]
ASR_ML = ["Rank", "Model", "Average WER", "Coverage", f"{DE} German", f"{FR} French"]
TTS_Q = ["Rank", "Model", "Average WER", "Average RTFx", "UTMOS (en)", "Average SIM", "Size (B)", "License",
         "# languages", "Voice cloning", "Batch inference", "Transformers"]
TTS_S = ["Rank", "Model", "TTFA p95 (ms)", "TTFA p50 (ms)", "RTFx", "Streaming API", "Size (B)"]


def asr_config(english=None, multilingual=None, en_heads=ASR_EN):
    def df(elem, heads, rows):
        return {"id": 7, "type": "dataframe", "props": {"elem_id": elem, "value": {"headers": heads, "data": rows}}}
    english = english or [[1, "+1", a("acme/asr-a"), 5.1, 900.0, 4.0],
                          [2, "0", a("elevenlabs/scribe_v2", "https://elevenlabs.io/stt"), 4.2, None, 3.0]]
    multilingual = multilingual or [[1, a("acme/asr-a"), 4.0, "2/2", 3.5, 4.5]]
    return js({"version": "6.26.0", "components": [{"id": 1, "type": "markdown", "props": {"value": "# board"}},
                                                    df("leaderboard-table", en_heads, english),
                                                    df("multilingual-table", ASR_ML, multilingual)]})


def tts_info(quality=("version", "search", "langs", "datasets", "clone")):
    types = {"version": {"enum": ["latest", "2026-09"], "type": "string"}, "search": {"type": "string"},
             "langs": {"items": {"enum": [f"{KR} Korean", f"{US} English"]}, "type": "array"},
             "datasets": {"items": {"enum": ["Seed-TTS", "CV3-Eval", "MiniMax"]}, "type": "array"},
             "clone": {"type": "boolean"}, "mode": {"enum": ["A100", "CPU", "H200"], "type": "string"}}
    ep = lambda names: {"parameters": [{"label": n, "parameter_name": n, "type": types.get(n, {})} for n in names]}
    return js({"named_endpoints": {"/_refresh_leaderboard": ep(quality), "/_refresh_streaming": ep(("mode", "version", "search")),
                                   "/save_feedback": ep(("text",))}, "unnamed_endpoints": {}})


def sse(heads, rows, kind="complete"):
    data = json.dumps([{"value": {"headers": heads, "data": rows, "metadata": None}}, None]) if kind == "complete" else "null"
    return f"event: heartbeat\ndata: null\n\nevent: {kind}\ndata: {data}\n\n".encode()


def tts_routes(heads=TTS_Q, rows=None, fn="leaderboard", kind="complete", info=None):
    rows = rows if rows is not None else [[1, a("acme/tts-a"), 2.8, 13.9, DASH, 75.0, 1.92, "apache 2.0", 10, CHECK,
                                           CHECK, DASH]]
    return [(("gradio_api/info",), info or tts_info()), ((f"call/_refresh_{fn}/{EV}",), sse(heads, rows, kind)),
            ((f"call/_refresh_{fn}",), js({"event_id": EV}))]


def llm_entry(name, avg=20.0, params=1.0, lic="apache-2.0", ifeval=50.0, flagged=False, date="2024-06-01", precision="bfloat16"):
    evals = {k: {"name": n, "value": 0.5, "normalized_score": ifeval if k == "ifeval" else 10.0}
             for k, n in (("ifeval", "IFEval"), ("bbh", "BBH"), ("math", "MATH Level 5"), ("gpqa", "GPQA"), ("musr", "MUSR"),
                          ("mmlu_pro", "MMLU-PRO"))}
    return {"id": f"{name}_{precision}_{SHA}_True",
            "model": {"name": name, "sha": SHA, "precision": precision, "type": "chatmodels", "weight_type": "Original",
                      "architecture": "LlamaForCausalLM", "average_score": avg, "has_chat_template": True},
            "evaluations": evals, "features": {"is_not_available_on_hub": True, "is_merged": False, "is_moe": False,
                                               "is_flagged": flagged, "is_official_provider": False},
            "metadata": {"upload_date": date, "submission_date": "2024-08-01", "generation": 0, "base_model": name,
                         "hub_license": lic, "hub_hearts": 1, "params_billions": params, "co2_cost": 0.5}}


SLM_LINES = [
    "{ name:'Tiny-1', org:'Acme', addedDate:'2026-10-01', params:150000000, paramsDisplay:'150M', arc:50, hellaswag:40, "
    "piqa:70, arcChall:30, arithmark3:45, arithmark2:30, links:{card:'https://huggingface.co/acme/Tiny-1'} },",
    "//{ name:'Gone-1', org:'Acme', addedDate:'2026-09-01', params:50000000, paramsDisplay:'50M', arc:30, hellaswag:30, "
    "piqa:55, arcChall:26, arithmark3:26, arithmark2:26, links:{card:'https://huggingface.co/acme/Gone-1'} },",
    "{ type:'orgMovementCutoff', label:'Later entries' },",
    "{ name:'Tiny-2', org:'Beta', addedDate:'2026-10-02', params:90000000, paramsDisplay:'90M', arc:40, hellaswag:35, "
    "piqa:65, arcChall:null, arithmark3:null, arithmark2:null, links:{card:'https://huggingface.co/beta/Tiny-2'} },",
    "{ name:'Rambler-10M', org:'Solo', addedDate:'2026-10-03', params:10000000, paramsDisplay:'10M', arc:30, hellaswag:30, "
    "piqa:55, arcChall:26, arithmark3:26, arithmark2:26, links:{} },"]


def slm_page(lines=SLM_LINES, index="return 0;", baselines=True):
    base = "const RANDOM_BASELINES = { hellaswag: 25, arc: 25, arcChall: 25, piqa: 50, arithmark2: 25, arithmark3: 25 };\n"
    return ("<html><body><script>\n" + (base if baselines else "") + "const MODELS = [\n  " + "\n  ".join(lines) + "\n];\n"
            "function normalizeFromChance(v, chance) { return (v - chance) / (100 - chance) * 100; }\n"
            "function getIntelligenceIndex(m) { " + index + " }\n</script></body></html>").encode()


def hub_entry(rank, model_id, value, verified=False, params=None, lower=False):
    return {"rank": rank, "filename": "eval.yaml", "value": value, "verified": verified,
            "source": {"url": f"{H}/{model_id}", "name": "model card", "isExternal": False}, "modelId": model_id,
            "author": model_id.split("/")[0], "notes": None, "num_parameters": params, "lower_is_better": lower,
            "pullRequest": None}


def model(repo, params=None, dtype="BF16", license="apache-2.0", languages=(), created="2026-05-01", files=(), tags=(),
          gated=False, card=None, total=None):
    """/api/models/<repo>?blobs=true."""
    sib = [{"rfilename": ".gitattributes", "size": 100}, {"rfilename": "README.md", "size": len(CARD.encode())},
           {"rfilename": "config.json", "size": 500}] + [{"rfilename": n, "size": s} for n, s in files]
    body = {"_id": "x", "id": repo, "sha": SHA, "pipeline_tag": "text-to-speech", "library_name": "transformers",
            "createdAt": f"{created}T00:00:00.000Z", "lastModified": "2026-10-01T00:00:00.000Z", "gated": gated,
            "tags": [*tags, *([f"license:{license}"] if license else [])], "siblings": sib, "downloads": 10, "likes": 1,
            "cardData": card if card is not None else {"license": license, "language": list(languages)},
            "config": {"architectures": ["TinyForCausalLM"], "model_type": "tiny"}}
    if params:
        body["safetensors"] = {"parameters": {dtype: params}, "total": total or params}
    return js(body)


def api(repo):
    return (f"/api/models/{repo}?blobs=true",)


class Opener:
    """Fake opener: the first route whose substrings all appear in the URL answers with body bytes, an HTTP status,
    a (status, headers) tuple, an exception or a list of those served in turn; records each request."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def open(self, req, timeout=None):
        url = req.full_url
        self.calls.append(SimpleNamespace(method=req.get_method(), url=url, headers=dict(req.header_items()),
                                          data=json.loads(req.data) if req.data else None))
        r = next((r for keys, r in self.routes if all(k in url for k in keys)), 404)
        if isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, tuple):
            raise urllib.error.HTTPError(url, r[0], "error", r[1], None)
        if isinstance(r, int):
            raise urllib.error.HTTPError(url, r, "error", {}, None)
        return io.BytesIO(r)

    def urls(self):
        return [c.url for c in self.calls]


class Base(unittest.TestCase):
    def setUp(self):
        self.topic = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.topic, True)
        self.sleep = mock.patch("time.sleep").start()
        mock.patch.object(m, "egress_terms", lambda cwd=None: []).start()
        mock.patch.object(m, "SLM_INDEX", m.index_code(slm_page().decode())).start()
        mock.patch.dict(os.environ, {"HF_TOKEN": ""}).start()
        self.addCleanup(mock.patch.stopall)

    def run_main(self, routes, *argv):
        self.opener = Opener(routes)
        out = io.StringIO()
        with mock.patch.object(m, "OPENER", self.opener), contextlib.redirect_stdout(out):
            code = m.main([argv[0], str(self.topic), *argv[1:]])
        for url in self.opener.urls():  # fetch() asks only for registry routes, and never for a write endpoint
            self.assertTrue(any(r.fullmatch(url) for r in m.ROUTES), url)
            self.assertNotIn("save_feedback", url)
        return code, out.getvalue()

    def tsv(self, stem):
        path = self.topic / "sources" / f"{stem}-{m.today()}.tsv"
        lines = path.read_text(encoding="utf-8").split("\n")
        return lines[0], lines[1].split("\t"), [dict(zip(lines[1].split("\t"), l.split("\t"))) for l in lines[2:] if l]

    def shortlist_json(self):
        return json.loads((self.topic / "models" / "shortlist.json").read_text(encoding="utf-8"))


class SnapshotTest(Base):
    def test_asr_tables_parse_to_their_headers(self):
        rev = (("api/spaces/hf-audio/open_asr_leaderboard",), js({"sha": "b" * 40}))
        code, out = self.run_main([(("open-asr-leaderboard.hf.space/config",), asr_config()), rev], "snapshot", "--board", "asr")
        self.assertEqual(code, 0, out)
        meta, heads, rows = self.tsv("board-asr-english")
        self.assertEqual(heads, ["Rank", "Rank \U00000394", "model", "Average WER", "RTFx", "AMI", "link"])
        self.assertIn("board=asr table=english route=gradio-config", meta)
        self.assertIn("revision=" + "b" * 40, meta)
        self.assertEqual([(r["model"], r["link"]) for r in rows], [("acme/asr-a", f"{H}/acme/asr-a"),
                                                                     ("elevenlabs/scribe_v2", "https://elevenlabs.io/stt")])
        self.assertEqual(rows[1]["RTFx"], "")
        self.assertRegex(out, r"SNAPSHOT\t\S+board-asr-english-\S+\.tsv\t2 rows\t1 linked off the Hub\trevision bbbbbbb")
        code, out = self.run_main([(("config",), asr_config())], "snapshot", "--board", "asr", "--table", "multilingual")
        self.assertEqual(self.tsv("board-asr-multilingual")[1], ["Rank", "Model", "Average WER", "Coverage", "German",
                                                                  "French", "link"])

    def test_values_verbatim_markup_stripped_footnotes_kept(self):
        rows = [[1, a("acme/tts-s", text=f"acme/tts-s (audio.cpp)<sup>{SUP1}</sup> &amp; co"), 120.5, 45.0, 6.1, CHECK, DASH]]
        code, out = self.run_main(tts_routes(TTS_S, rows, "streaming"), "snapshot", "--board", "tts", "--table", "streaming")
        self.assertEqual(code, 0, out)
        row = self.tsv("board-tts-streaming-a100")[2][0]
        self.assertEqual((row["Model"], row["TTFA p50 (ms)"], row["Streaming API"], row["Size (B)"]),
                         (f"acme/tts-s (audio.cpp){SUP1} & co", "45.0", CHECK, DASH))
        self.assertEqual(self.opener.calls[1].data, {"data": ["A100", "latest", ""]})

    def test_renamed_header_is_schema_drift(self):
        heads = ["Rank", "Rank \U00000394", "model", "Mean WER", "RTFx", "AMI"]
        code, out = self.run_main([(("config",), asr_config(en_heads=heads))], "snapshot", "--board", "asr")
        self.assertEqual(code, 2)
        self.assertIn("FAIL\tschema-drift: asr\tmissing Average WER", out)
        self.assertFalse((self.topic / "sources").exists())

    def test_one_snapshot_a_day_then_new_and_gone(self):
        self.run_main([(("config",), asr_config())], "snapshot", "--board", "asr")
        code, out = self.run_main([(("config",), asr_config())], "snapshot", "--board", "asr")
        self.assertTrue(out.startswith("KEPT\t") and self.opener.calls == [], out)
        later = [[1, "0", a("acme/asr-a"), 5.0, 910.0, 4.0], [2, "+3", a("acme/asr-new"), 4.0, 100.0, 3.0]]
        code, out = self.run_main([(("config",), asr_config(english=later))], "snapshot", "--board", "asr", "--refresh")
        self.assertTrue((self.topic / "sources" / f"board-asr-english-{m.today()}-2.tsv").is_file())
        self.assertIn("NEW\tacme/asr-new\nGONE\televenlabs/scribe_v2\n", out)
        self.assertIn("1 new, 1 gone", out)

    def test_tts_quality_posts_the_space_choices(self):
        code, out = self.run_main(tts_routes(), "snapshot", "--board", "tts", "--lang", "korean", "--clone")
        self.assertEqual(code, 0, out)
        post = [c for c in self.opener.calls if c.method == "POST"]
        self.assertEqual([c.data for c in post], [{"data": ["latest", "", [f"{KR} Korean"], ["Seed-TTS", "CV3-Eval", "MiniMax"],
                                                            True]}])
        meta, heads, rows = self.tsv("board-tts-quality-korean-clone")
        self.assertIn("lang=korean clone=true", meta)
        self.assertEqual(heads, TTS_Q + ["link"])
        self.assertEqual(rows[0]["UTMOS (en)"], DASH)

    def test_tts_bad_language_changed_endpoint_and_error_event(self):
        code, out = self.run_main(tts_routes(), "snapshot", "--board", "tts", "--lang", "Klingon")
        self.assertEqual((code, out.strip()), (2, "FAIL\tusage\t--lang for tts: Korean, English"))
        code, out = self.run_main(tts_routes(info=tts_info(("version", "search", "langs", "datasets"))), "snapshot", "--board", "tts")
        self.assertEqual(code, 2)
        self.assertIn("schema-drift", out)
        self.assertFalse(any(c.method == "POST" for c in self.opener.calls))
        code, out = self.run_main(tts_routes(kind="error"), "snapshot", "--board", "tts")
        self.assertEqual((code, out.strip()), (1, "FAIL\ttts\tthe board answered with an error"))

    def test_llm_board_in_one_request(self):
        entries = [llm_entry("acme/llm-a"), llm_entry("acme/llm-b", flagged=True)]
        code, out = self.run_main([(("api/leaderboard/formatted",), js(entries))], "snapshot", "--board", "llm")
        self.assertEqual(code, 0, out)
        meta, heads, rows = self.tsv("board-llm")
        for h in ("name", "average_score", "IFEval", "MATH Level 5", "MMLU-PRO", "params_billions", "hub_license",
                  "upload_date", "is_flagged", "precision"):
            self.assertIn(h, heads)
        self.assertEqual([r["is_flagged"] for r in rows], ["false", "true"])
        self.assertEqual(sum("formatted" in u for u in self.opener.urls()), 1)
        self.assertIn("# frozen since 2025-03-20", out)
        code, out = self.run_main([(("formatted",), js({"error": "x"}))], "snapshot", "--board", "llm", "--refresh")
        self.assertEqual(code, 2)

    def test_slm_page_skips_comments_and_computes_the_index(self):
        code, out = self.run_main([(("index.html",), slm_page())], "snapshot", "--board", "slm")
        self.assertEqual(code, 0, out)
        meta, heads, rows = self.tsv("board-slm")
        self.assertEqual([r["name"] for r in rows], ["Tiny-1", "Tiny-2", "Rambler-10M"])
        # Tiny-1: HellaSwag 20, ARC (50+30)/2 -> 20, PIQA 40, ArithMark-3 26.67 at 0.65: 97.33 / 3.65
        self.assertEqual([r["Intelligence Index"] for r in rows], ["26.67", "21.11", "5.9"])
        self.assertEqual((rows[0]["card"], rows[2]["card"], rows[1]["arcChall"]), (f"{H}/acme/Tiny-1", "", ""))
        code, out = self.run_main([(("index.html",), slm_page(index="return 1;"))], "snapshot", "--board", "slm", "--refresh")
        self.assertEqual(code, 2)
        self.assertIn("Intelligence Index code changed", out)
        code, out = self.run_main([(("index.html",), slm_page(baselines=False))], "snapshot", "--board", "slm", "--refresh")
        self.assertEqual(code, 2)

    def test_hub_benchmark_board(self):
        entries = [hub_entry(1, "acme/m1", 30.0, verified=True, params=10**9, lower=True), hub_entry(2, "acme/m2", 35.0)]
        code, out = self.run_main([(("api/datasets/acme/bench/leaderboard",), js(entries))], "snapshot", "--board", "hub:acme/bench")
        self.assertEqual(code, 0, out)
        meta, heads, rows = self.tsv("board-hub-acme-bench")
        self.assertEqual(heads, ["rank", "modelId", "value", "verified", "source", "lower_is_better", "num_parameters", "notes",
                                 "link"])
        self.assertEqual((rows[0]["verified"], rows[0]["source"], rows[1]["num_parameters"]), ("true", f"{H}/acme/m1", ""))
        code, out = self.run_main([], "snapshot", "--board", "hub:acme")
        self.assertEqual((code, self.opener.calls), (2, []))


class FetchTest(Base):
    URL = H + "/api/models/acme/x?blobs=true"

    def test_registry_routes_only(self):
        opener = Opener([])
        with mock.patch.object(m, "OPENER", opener):
            for url, data in (("https://example.com/x", None), (H + "/acme/x/resolve/main/model.safetensors", None),
                              ("https://hf-audio-open-tts-leaderboard.hf.space/gradio_api/call/save_feedback", {"data": []}),
                              ("https://hf-audio-open-asr-leaderboard.hf.space/config", {"data": []})):
                with self.subTest(url=url), self.assertRaises(m.Fail) as e:
                    m.fetch(url, data)
                self.assertEqual(str(e.exception), "not a registry route")
        self.assertEqual(opener.calls, [])

    def test_retries_then_gives_up(self):
        for served, waits in (([429, b"{}"], [2]), ([(429, {"Retry-After": "5"}), b"{}"], [5]), ([503, b"{}"], [2]),
                              ([TimeoutError(), TimeoutError(), b"{}"], [2, 4])):
            self.sleep.reset_mock()
            with self.subTest(served=served[0]), mock.patch.object(m, "OPENER", Opener([(("api/models",), served)])):
                self.assertEqual(m.fetch(self.URL), b"{}")
                self.assertEqual([c.args[0] for c in self.sleep.call_args_list if c.args[0] > 1.5], waits)
        for served, why in (([429] * 4, "http 429"), ([404, b"{}"], "http 404")):
            with mock.patch.object(m, "OPENER", Opener([(("api/models",), served)])), self.assertRaises(m.Fail) as e:
                m.fetch(self.URL)
            self.assertEqual(str(e.exception), why)
        with mock.patch.object(m, "OPENER", Opener([(("api/models",), b"x" * 11)])), mock.patch.object(m, "CAP", 10), \
                self.assertRaises(m.Fail) as e:
            m.fetch(self.URL)
        self.assertEqual(str(e.exception), "too large")

    def test_walls_are_not_retried_and_one_run_deadline(self):
        for served, why in (([(503, {"cf-mitigated": "challenge"}), b"{}"], "http 503: bot check"),
                            ([(403, {"X-RateLimit-Remaining": "0"}), b"{}"], "http 403"),
                            ([(502, {"Retry-After": "61"}), b"{}"], None)):
            opener = Opener([(("api/models",), served)])
            with self.subTest(why=why), mock.patch.object(m, "OPENER", opener):
                if why is None:  # a Retry-After over 60 s is not honored: the backoff applies
                    self.sleep.reset_mock()
                    self.assertEqual(m.fetch(self.URL), b"{}")
                    self.assertIn(2, [c.args[0] for c in self.sleep.call_args_list])
                    continue
                with self.assertRaises(m.Fail) as e:
                    m.fetch(self.URL)
                self.assertEqual((str(e.exception), len(opener.calls)), (why, 1))
        with mock.patch.object(m, "DEADLINE", 5):
            code, out = self.run_main([(("api/models/acme/x",), [(429, {"Retry-After": "30"}), b"{}"])], "follow", "acme/x")
        self.assertEqual((code, out.splitlines()[0], len(self.opener.calls)), (1, "FAIL\tacme/x\thttp 429; run deadline reached", 1))
        with mock.patch.object(m, "DEADLINE", 0):
            code, out = self.run_main([], "follow", "acme/x")
        self.assertEqual((code, out.splitlines()[0], self.opener.calls), (1, "FAIL\tacme/x\trun deadline reached", []))
        self.assertIsNone(m._end)

    def test_redirects_stay_on_the_host(self):
        req = urllib.request.Request(self.URL)
        with self.assertRaises(urllib.error.URLError):
            m._Redirect().redirect_request(req, None, 302, "Found", {}, "https://evil.example/x")
        self.assertIsNotNone(m._Redirect().redirect_request(req, None, 302, "Found", {}, H + "/api/models/acme/y?blobs=true"))

    def test_token_from_env_to_huggingface_only_never_printed(self):
        secret = "hf_test_not_a_real_token"
        routes = [(("config",), asr_config()), (("api/spaces",), js({"sha": SHA})), (api("acme/asr-a"), model("acme/asr-a", 10**9))]
        with mock.patch.dict(os.environ, {"HF_TOKEN": secret}):
            out = self.run_main(routes, "snapshot", "--board", "asr")[1]
            out += self.run_main(routes, "shortlist", "--board", "asr")[1]
        hf = [c for c in self.opener.calls + [] if c.url.startswith(H + "/")]
        self.assertTrue(hf)
        for c in self.opener.calls:
            self.assertEqual(c.headers.get("Authorization"), f"Bearer {secret}" if c.url.startswith(H + "/") else None, c.url)
        self.assertNotIn(secret, out)
        self.assertEqual([p for p in self.topic.rglob("*") if p.is_file() and secret in p.read_text(encoding="utf-8")], [])


class FactsTest(Base):
    def test_cells_names_and_links(self):
        self.assertEqual(m.label(f"Average WER {DOWN}{VS}"), "Average WER")
        self.assertEqual(m.label(f"{DE} German"), "German")
        self.assertEqual(m.text(f'<a href="x">acme/m</a><sup>{SUP1}</sup> &amp; co'), f"acme/m{SUP1} & co")
        self.assertEqual((m.text(None), m.text(True), m.text(5.1)), ("", "true", "5.1"))
        for name, link, want in (("acme/m (audio.cpp)" + SUP1, "https://github.com/acme/m", "acme/m"),
                                 ("acme/m\U000000b2", "", "acme/m"), ("Tiny", f"{H}/acme/Tiny", "acme/Tiny"),
                                 ("Service X", "https://x.example", None), ("x", f"{H}/spaces/acme/demo", None)):
            self.assertEqual(m.candidate(name, link), want, name)

    def test_sizes_by_dtype_and_at_4_bit(self):
        self.assertEqual([m.width(d) for d in ("BF16", "F32", "F8_E4M3", "I64", "BOOL", "U8")], [2, 4, 1, 8, 1, 1])
        c = {"params": 10**9}
        m.sizes(c)
        self.assertEqual((c["gb_16"], c["gb_4bit"]), (2.0, 0.55))
        c = {"params": None}
        m.sizes(c)
        self.assertEqual((c["gb_16"], c["gb_4bit"]), (None, None))

    def test_license_classes(self):
        for lic, want in (("apache-2.0", "permissive"), ("apache 2.0", "permissive"), ("MIT", "permissive"),
                          ("cc-by-4.0", "permissive"), ("bsd-3-clause", "permissive"), ("cc-by-nc-4.0", "non-commercial"),
                          ("cc-by-nc", "non-commercial"), ("fair-noncommercial-research", "non-commercial"),
                          ("cc-by-sa-4.0", "open"), ("llama3.2", "open"), ("openrail", "open"), ("gpl-3.0", "open"),
                          ("other", "unknown"), ("custom", "unknown"), ("", "unknown"), (None, "unknown"),
                          ("https://example.com/LICENSE", "unknown")):
            self.assertEqual(m.license_class(lic), want, lic)

    def test_facts_of_a_repo(self):
        body = model("acme/x", 300_000_000, "F32", card={"license": "other", "license_name": "acme-research-only",
                                                          "language": "en"},
                     files=[("model.safetensors", 1_200_000_000), ("onnx/model.onnx", 1_200_000_000),
                            ("coreml/x.mlpackage/Data/weights.bin", 10)], tags=["arxiv:2601.00001", "base_model:acme/base", "mlx"])
        gguf = js({"id": "acme/x-GGUF", "sha": SHA, "tags": ["gguf"], "siblings": [{"rfilename": "x-Q4_K_M.gguf", "size": 7}],
                   "gguf": {"total": 10**9, "architecture": "llama", "context_length": 4096}})
        with mock.patch.object(m, "OPENER", Opener([(api("acme/x"), body), (api("acme/x-GGUF"), gguf), (api("acme/gone"), 401)])):
            f, g, gone = m.facts("acme/x"), m.facts("acme/x-GGUF"), m.facts("acme/gone")
        self.assertEqual((f["params"], f["params_by_dtype"], f["weight_gb"], f["weight_source"], f["largest_file_gb"]),
                         (300_000_000, {"F32": 300_000_000}, 1.2, "safetensors dtypes", 1.2))
        self.assertEqual((f["license"], f["license_name"], f["license_class"]), ("other", "acme-research-only", "non-commercial"))
        self.assertEqual((f["languages"], f["arxiv"], f["base_model"], f["card"], f["config_file"]),
                         (["en"], ["2601.00001"], ["acme/base"], True, True))
        self.assertEqual(f["formats"], ["safetensors", "onnx", "mlx", "coreml", "pytorch"])
        self.assertEqual((g["params"], g["weight_gb"], g["gguf"], g["formats"], g["card"]),
                         (10**9, None, {"architecture": "llama", "context_length": 4096}, ["gguf"], False))
        self.assertIsNone(gone)

    def test_fit_against_a_budget(self):
        def fit(gb_16, gb_4bit, stored=None, budget=1.0):
            return m.fit({"gb_16": gb_16, "gb_4bit": gb_4bit, "weight_gb": stored}, budget)
        self.assertEqual(fit(16, 4.4, budget=None), (None, None))
        self.assertEqual(fit(0.6, 0.165, stored=1.2), (None, None))  # an F32 upload is not held against it
        self.assertEqual(fit(3.0, 0.825), (None, "fits at 4-bit"))
        self.assertEqual(fit(3.8, 1.05), (None, "over budget by 5%"))
        self.assertEqual(fit(16, 4.4), ("over budget: 4.40 GB at 4-bit", None))
        self.assertEqual(fit(None, None, stored=2.5), ("over budget: 2.50 GB at stored size", None))
        self.assertEqual(fit(None, None), (None, "size unknown"))

    def test_front_on_a_toy_table(self):
        ms = [{"scores": {"s": 90}, "params": 10**9}, {"scores": {"s": 80}, "params": 5 * 10**8},
              {"scores": {"s": 70}, "params": 6 * 10**8}, {"scores": {"s": 95}, "params": None},
              {"scores": {"s": 80}, "params": 5 * 10**8}]
        m.pareto(ms, "s", m.HIGH, None)
        self.assertEqual([c["front"] for c in ms], [True, True, False, True, True])
        ms = [{"scores": {"wer": 5, "rtfx": 100}, "params": 10**9}, {"scores": {"wer": 5, "rtfx": 50}, "params": 10**9},
              {"scores": {"wer": 5, "rtfx": None}, "params": 10**9}, {"scores": {"wer": 4, "rtfx": 10}, "params": 2 * 10**9}]
        m.pareto(ms, "wer", m.LOW, "rtfx")
        self.assertEqual([c["front"] for c in ms], [True, False, False, True])


class ShortlistTest(Base):
    def test_no_snapshot_yet(self):
        code, out = self.run_main([], "shortlist", "--board", "asr")
        self.assertEqual(code, 2)
        self.assertIn("run snapshot first", out)

    def test_asr_language_column_budget_and_front(self):
        ml = [[1, a("acme/asr-big"), 3.5, "2/2", 3.0, 4.0], [2, a("elevenlabs/scribe_v2", "https://elevenlabs.io/stt"), 3.0,
                                                               "2/2", 2.0, 3.0],
              [3, a("acme/asr-small"), 4.5, "2/2", 4.0, 5.0], [4, a("acme/asr-mid"), 5.5, "2/2", 5.0, 6.0],
              [5, a("acme/asr-tiny"), 6.5, "2/2", 6.0, 7.0], [6, a("acme/asr-huge"), 2.6, "2/2", 2.5, 2.7],
              [7, a("acme/asr-fr"), 5.0, "1/2", DASH, 5.0]]
        self.run_main([(("config",), asr_config(multilingual=ml))], "snapshot", "--board", "asr", "--table", "multilingual")
        routes = [(api("acme/asr-big"), model("acme/asr-big", 1_900_000_000, languages=["en"])),
                  (api("acme/asr-small"), model("acme/asr-small", 300_000_000, "F32")),
                  (api("acme/asr-mid"), model("acme/asr-mid", 500_000_000)),
                  (api("acme/asr-tiny"), model("acme/asr-tiny", 100_000_000)),
                  (api("acme/asr-huge"), model("acme/asr-huge", 8 * 10**9)),
                  (("quantized%3Aacme%2Fasr-small",), js([{"id": "q/asr-small-GGUF", "tags": ["gguf", "base_model:x"]}]))]
        code, out = self.run_main(routes, "shortlist", "--board", "asr", "--lang", "german", "--max-gb", "1")
        self.assertEqual(code, 0, out)
        self.assertIn("# asr multilingual: German, lower is better; ", out)
        self.assertIn("; 6 models, 4 kept, 3 on the front, 1 off the Hub", out)
        lines = [l.split("\t") for l in out.splitlines() if l.startswith(("FRONT", "MODEL"))]
        self.assertEqual([(l[0], l[1]) for l in lines], [("FRONT", "acme/asr-big"), ("FRONT", "acme/asr-small"),
                                                         ("FRONT", "acme/asr-tiny"), ("MODEL", "acme/asr-mid")])
        self.assertEqual(lines[0][2:7], ["German=3", "measured", "params 1.9B", "3.80 GB at 16-bit", "1.04 GB at 4-bit"])
        self.assertRegex(lines[0][-1], r"over budget by \d+%")
        self.assertEqual((lines[1][5], lines[1][-1]), ("0.60 GB at 16-bit", "quantized: gguf"))
        self.assertIn("OFFHUB\televenlabs/scribe_v2\tGerman=2\thttps://elevenlabs.io/stt", out)
        self.assertIn("# dropped: 1 no German score, 1 over budget", out)
        self.assertFalse(any("asr-fr" in u for u in self.opener.urls()))
        sl = self.shortlist_json()
        self.assertEqual({c["languages_label"] for c in sl["models"]}, {"board"})  # the board measured German
        self.assertEqual((sl["metric"], sl["direction"], sl["filters"]["max_gb"]), ("German", "lower", 1.0))
        code, out = self.run_main(routes, "shortlist", "--board", "asr", "--lang", "Korean")
        self.assertIn("# asr multilingual measures no Korean: the cards' own language lists filter instead", out)
        self.assertIn("# asr multilingual: Average WER, lower is better", out)
        self.assertIn("card does not list Korean", out)  # asr-big's card lists en only

    def test_board_columns_filter_before_any_lookup(self):
        rows = [[1, a("acme/tts-a"), 2.8, 13.9, DASH, 75.0, 1.92, "apache 2.0", 10, CHECK, CHECK, DASH],
                [2, a("acme/tts-nc"), 3.0, 24.3, DASH, 79.0, 0.81, "cc-by-nc", 600, CHECK, CHECK, DASH],
                [3, a("acme/tts-rl", text="acme/tts-rl (RL)"), 4.3, 2.5, DASH, 70.0, 0.11, "cc-by-4.0", 9, CHECK, DASH, DASH],
                [4, a("acme/tts-var"), 4.5, 9.0, DASH, 52.0, 0.1, "cc-by-4.0", 7, CHECK, DASH, DASH]]
        self.run_main(tts_routes(rows=rows), "snapshot", "--board", "tts", "--lang", "Korean", "--clone")
        routes = [(api("acme/tts-a"), model("acme/tts-a", 1_920_000_000)),
                  (api("acme/tts-rl"), model("acme/tts-rl", files=[("llm.pt", 2_000_000_000), ("flow.pt", 400_000_000)])),
                  (api("acme/tts-var"), model("acme/tts-var", files=[("en/model.safetensors", 400_000_000),
                                                                     ("en_24l/model.safetensors", 1_300_000_000)]))]
        code, out = self.run_main(routes, "shortlist", "--board", "tts", "--lang", "Korean", "--clone", "--license",
                                  "permissive", "--max-gb", "2")
        self.assertEqual(code, 0, out)
        self.assertFalse(any("tts-nc" in u for u in self.opener.urls()))
        self.assertIn("# dropped: 1 license non-commercial", out)
        lines = {l.split("\t")[1]: l.split("\t") for l in out.splitlines() if l.startswith(("FRONT", "MODEL"))}
        self.assertEqual(lines["acme/tts-a"][:3], ["FRONT", "acme/tts-a", "Average WER=2.8 Average RTFx=13.9"])
        self.assertIn("fits at 4-bit", lines["acme/tts-a"][-1])
        rl = lines["acme/tts-rl"]
        self.assertEqual(rl[4:7], ["params ?", "2.00 GB stored", "? at 4-bit"])
        self.assertEqual(rl[-1], "params 0.11B miss part of the weights (2.00 GB in one file); board row: acme/tts-rl (RL)")
        self.assertEqual(lines["acme/tts-var"][4:6], ["params 0.1B", "0.20 GB at 16-bit"])  # a bigger variant in a folder
        code, out = self.run_main(routes, "shortlist", "--board", "tts", "--lang", "Korean", "--clone", "--metric", "average sim")
        self.assertIn("# tts quality: Average SIM, higher is better", out)

    def test_llm_rows_flags_dates_and_card_languages(self):
        entries = [llm_entry("acme/llm-ko", ifeval=70.0), llm_entry("acme/llm-ko", ifeval=60.0, precision="float16"),
                   llm_entry("acme/llm-en", ifeval=65.0), llm_entry("acme/llm-none", ifeval=64.0),
                   llm_entry("acme/llm-multi", ifeval=63.0), llm_entry("acme/llm-flag", ifeval=99.0, flagged=True),
                   llm_entry("acme/llm-old", ifeval=80.0, date="2023-12-01")]
        self.run_main([(("formatted",), js(entries))], "snapshot", "--board", "llm")
        routes = [(api("acme/llm-ko"), model("acme/llm-ko", 10**9, languages=["ko", "en"])),
                  (api("acme/llm-en"), model("acme/llm-en", 10**9, languages=["en"])),
                  (api("acme/llm-none"), model("acme/llm-none", 10**9)),
                  (api("acme/llm-multi"), model("acme/llm-multi", 10**9, languages=["multilingual"]))]
        code, out = self.run_main(routes, "shortlist", "--board", "llm", "--metric", "ifeval", "--since", "2024-03-01",
                                  "--lang", "Korean")
        self.assertEqual(code, 0, out)
        rows = {l.split("\t")[1]: l.split("\t") for l in out.splitlines() if l.startswith(("FRONT", "MODEL"))}
        self.assertEqual(sorted(rows), ["acme/llm-ko", "acme/llm-multi", "acme/llm-none"])
        self.assertEqual(rows["acme/llm-ko"][2], "IFEval=70")
        self.assertIn("languages not stated", rows["acme/llm-none"][-1])
        self.assertIn("card says multilingual", rows["acme/llm-multi"][-1])
        self.assertIn("created 2024-06-01", rows["acme/llm-ko"])  # the board's upload date
        self.assertIn("# dropped: 1 flagged by the board, 1 created before 2024-03-01, 1 card does not list Korean", out)
        self.assertFalse(any("llm-old" in u or "llm-flag" in u for u in self.opener.urls()))
        looked = [c for c in self.shortlist_json()["models"] if c["repo"] not in ("acme/llm-old",)]
        self.assertEqual({c["languages_label"] for c in looked}, {"self-reported"})  # the cards say so, not the board
        self.assertIn("# the board is frozen since 2025-03-20", out)

    def test_slm_dates_come_from_the_hub_and_unlinked_rows_are_off_it(self):
        self.run_main([(("index.html",), slm_page())], "snapshot", "--board", "slm")
        routes = [(api("acme/Tiny-1"), model("acme/Tiny-1", 150_000_000, created="2024-01-01")),
                  (api("beta/Tiny-2"), model("beta/Tiny-2", 90_000_000, created="2026-09-01"))]
        code, out = self.run_main(routes, "shortlist", "--board", "slm", "--since", "2026-01-01")
        self.assertEqual(code, 0, out)
        self.assertIn("# dropped: 1 created before 2026-01-01", out)  # added to the board 2026-10-01, made 2024-01-01
        self.assertIn("FRONT\tbeta/Tiny-2\tIntelligence Index=21.11\tmeasured\tparams 0.09B", out)
        self.assertIn("OFFHUB\tRambler-10M\tIntelligence Index=5.9\tno link", out)
        self.assertNotIn("board row", out)
        code, out = self.run_main(routes, "shortlist", "--board", "slm", "--off-hub")
        self.assertIn("\tRambler-10M\t", out.split("# dropped")[0])
        self.assertNotIn("OFFHUB", out)

    def test_hub_board_labels_direction_and_lookup_cap(self):
        entries = [hub_entry(1, "acme/m1", 30.0, verified=True, params=10**9, lower=True),
                   hub_entry(2, "acme/m2", 35.0, lower=True)]
        self.run_main([(("leaderboard",), js(entries))], "snapshot", "--board", "hub:acme/bench")
        routes = [(api("acme/m1"), model("acme/m1", 10**9)), (api("acme/m2"), model("acme/m2", 5 * 10**8))]
        code, out = self.run_main(routes, "shortlist", "--board", "hub:acme/bench")
        self.assertIn("value, lower is better", out)
        self.assertIn("FRONT\tacme/m1\tvalue=30\tverified\t", out)
        self.assertIn("FRONT\tacme/m2\tvalue=35\tself-reported\t", out)
        with mock.patch.object(m, "RESOLVE", 1):
            code, out = self.run_main(routes, "shortlist", "--board", "hub:acme/bench")
        self.assertIn("# 1 lower-ranked models were not looked up; --max-gb filter on the board's columns", out)
        self.assertFalse(any("acme/m2" in u for u in self.opener.urls()))


CARD = """---
license: apache-2.0
language:
- en
- ko
---
# Tiny TTS

Tiny TTS speaks in a voice taken from a 3 second reference audio clip.
It supports streaming output at 24 kHz.
"""


class FollowTest(Base):
    def routes(self):
        return [(api("acme/tts-a"), model("acme/tts-a", 10**9, languages=["en", "ko"], tags=["arxiv:2601.00001"],
                                          files=[("streaming_sample.wav", 100)])),
                (("quantized%3Aacme%2Ftts-a",), js([{"id": "someone/tts-a-emotion-GGUF", "tags": ["gguf"]}])),
                (("raw/" + SHA + "/README.md",), CARD.encode()),
                (("raw/" + SHA + "/config.json",), js({"model_type": "tiny", "sampling_rate": 24000,
                                                       "llm_config": {"num_hidden_layers": 12, "rope": {"theta": 1}}})),
                (("api/papers/2601.00001",), js({"id": "2601.00001", "title": "Tiny TTS", "publishedAt": "2026-01-02T00:00:00Z",
                                                 "githubRepo": "https://github.com/acme/tiny-tts",
                                                 "summary": "Word timestamps are out of scope.",
                                                 "ai_summary": "Machine-written: supports emotion control."}))]

    def test_card_saved_at_its_sha_and_never_overwritten(self):
        code, out = self.run_main(self.routes(), "follow", "acme/tts-a", "--task", "tts")
        self.assertEqual(code, 0, out)
        card = self.topic / "sources" / "hf-acme--tts-a-aaaaaaa.md"
        self.assertEqual(card.read_text(encoding="utf-8"), CARD)
        facts = json.loads((self.topic / "models" / "hub" / "acme--tts-a.json").read_text(encoding="utf-8"))
        self.assertEqual({k: facts["config"][k] for k in ("model_type", "sampling_rate", "llm_config.num_hidden_layers")},
                         {"model_type": "tiny", "sampling_rate": 24000, "llm_config.num_hidden_layers": 12})
        self.assertNotIn("llm_config.rope", facts["config"])
        self.assertEqual(facts["papers"], [{"id": "2601.00001", "title": "Tiny TTS", "abstract": "Word timestamps are out of scope.",
                                            "published": "2026-01-02", "github": "https://github.com/acme/tiny-tts"}])
        self.assertIn(f"FACTS\tacme/tts-a\t{card.as_posix()}\t", out)
        card.write_text("edited\n" * 400, encoding="utf-8")
        self.run_main(self.routes(), "follow", "acme/tts-a", "--task", "tts")
        self.assertEqual(card.read_text(encoding="utf-8"), "edited\n" * 400)
        self.assertFalse(any("README.md" in u for u in self.opener.urls()))

    def test_features_needs_and_hops(self):
        code, out = self.run_main(self.routes(), "follow", "acme/tts-a", "--task", "tts", "--need",
                                  "Streaming, korean, word timestamps, lip sync")
        self.assertEqual(code, 0, out)
        feats = [l.split("\t")[2:] for l in out.splitlines() if l.startswith("FEATURE")]
        src = "sources/hf-acme--tts-a-aaaaaaa.md"
        self.assertIn(["voice cloning", f"{src}:9: Tiny TTS speaks in a voice taken from a 3 second reference audio clip."], feats)
        self.assertIn(["streaming", f"{src}:10: It supports streaming output at 24 kHz."], feats)
        self.assertEqual(sum(f[0].casefold() == "streaming" for f in feats), 1)  # the need is the task's own feature
        self.assertIn(["emotion or style control", "not stated"], feats)  # not from a derivative's or a file's name
        self.assertIn(["korean", f"{src}:5: - ko"], feats)
        self.assertIn(["korean", "models/hub/acme--tts-a.json:%d: %s" % self.line_of('"ko"')], feats)
        n, line = self.line_of('"abstract"')  # the paper's abstract is the first hop, read from the facts file
        self.assertIn(["word timestamps", f"models/hub/acme--tts-a.json:{n}: {line}"], feats)
        self.assertIn(["emotion or style control", "not stated"], feats)  # ai_summary is not kept
        self.assertIn(["lip sync", "not stated"], feats)
        hops = [l.split("\t")[2:] for l in out.splitlines() if l.startswith("HOP")]
        self.assertEqual(hops, [["lip sync", "paper https://arxiv.org/abs/2601.00001"],
                                ["lip sync", "repo https://github.com/acme/tiny-tts"]])

    def test_gated_card_keeps_the_facts_and_hops_to_the_page(self):
        routes = [(("acme/gated/raw/",), 401), (api("acme/gated"), model("acme/gated", 10**8, gated="auto")), *self.routes()]
        code, out = self.run_main(routes, "follow", "acme/gated", "acme/tts-a", "--task", "tts")
        self.assertEqual(code, 0, out)
        self.assertIn("FACTS\tacme/gated\tcard gated\t", out)
        self.assertIn("HOP\tacme/gated\tcard\tpage https://huggingface.co/acme/gated", out)
        self.assertIn("FEATURE\tacme/gated\tvoice cloning\tnot read: the card is gated", out)
        self.assertTrue((self.topic / "models" / "hub" / "acme--gated.json").is_file())
        self.assertFalse(list((self.topic / "sources").glob("hf-acme--gated-*")))
        self.assertIn("FACTS\tacme/tts-a\t", out)

    def test_atomic_writes_and_cut_files(self):
        target = self.topic / "a" / "f.txt"
        m.write_atomic(target, "one\n")
        with mock.patch.object(m.os, "replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            m.write_atomic(target, "two\n")
        self.assertEqual((target.read_bytes(), sorted(p.name for p in target.parent.iterdir())), (b"one\n", ["f.txt"]))
        routes = [(("api/leaderboard/formatted",), js([llm_entry("acme/llm-a"), llm_entry("acme/llm-b")]))]
        with mock.patch.object(m.os, "replace", side_effect=OSError("disk full")):
            code, out = self.run_main(routes, "snapshot", "--board", "llm")
        self.assertEqual((code, list((self.topic / "sources").iterdir())), (1, []), out)  # nothing half written is left
        code, out = self.run_main(routes, "snapshot", "--board", "llm")
        self.assertEqual(code, 0, out)
        path = self.topic / "sources" / f"board-llm-{m.today()}.tsv"
        whole = path.read_bytes()
        path.write_bytes(whole[:-30])  # a snapshot cut short by an older version
        code, out = self.run_main([], "shortlist", "--board", "llm")
        self.assertEqual((code, self.opener.calls), (2, []), out)  # never read as a table
        self.assertIn("run snapshot", out)
        code, out = self.run_main([(("api/leaderboard/formatted",), [503, js([llm_entry("acme/llm-a")])])], "snapshot", "--board", "llm")
        self.assertEqual(code, 0, out)
        self.assertNotIn("KEPT", out)  # a cut snapshot is no baseline: another is taken, and no NEW or GONE against it
        self.assertNotIn("# since", out)
        self.assertTrue((self.topic / "sources" / f"board-llm-{m.today()}-2.tsv").is_file())
        hub = m.hub_path(self.topic, "acme/x")
        hub.parent.mkdir(parents=True)
        hub.write_text('{"repo": "acme/x", "fetch', encoding="utf-8")  # a cut facts file is fetched again
        with mock.patch.object(m, "OPENER", Opener([(api("acme/x"), [503, model("acme/x", 10**8)])])):
            self.assertEqual(m.cached_facts(self.topic, "acme/x")["repo"], "acme/x")
        saved = json.loads(hub.read_text(encoding="utf-8"))
        self.assertEqual((saved["repo"], saved["fetched"]), ("acme/x", m.today()))
        self.assertFalse([k for k in saved if k.startswith("_")])

    def test_an_odd_reply_is_a_fail_line_not_a_traceback(self):
        routes = [(api("acme/odd"), [503, js([1])]), *self.routes()]  # a transient 503, then a list for a model
        code, out = self.run_main(routes, "follow", "acme/odd", "acme/tts-a", "--task", "tts")
        lines = out.splitlines()
        self.assertEqual(code, 1, out)
        self.assertTrue(lines[0].startswith("FAIL\tacme/odd\tunexpected reply from the Hub: AttributeError"), lines[0])
        self.assertIn("FACTS\tacme/tts-a\t", out)  # the next model is still followed
        code, out = self.run_main([(("api/leaderboard/formatted",), [503, js([{"model": [1], "evaluations": {}}])])], "snapshot", "--board", "llm")
        self.assertEqual(code, 1, out)
        self.assertEqual(len(out.splitlines()), 1, out)
        self.assertTrue(out.startswith("FAIL\tllm\tunexpected reply from the board: "), out)

    def test_a_cut_card_is_fetched_again_and_another_is_kept(self):
        code, out = self.run_main(self.routes(), "follow", "acme/tts-a", "--task", "tts")
        card = self.topic / "sources" / "hf-acme--tts-a-aaaaaaa.md"
        whole = card.read_bytes()
        for cut in (b"", whole[:len(whole) // 2]):  # an empty card and one cut short
            card.write_bytes(cut)
            routes = [(("raw/" + SHA + "/README.md",), [503, CARD.encode()]), *self.routes()]
            code, out = self.run_main(routes, "follow", "acme/tts-a", "--task", "tts")
            self.assertEqual((code, card.read_bytes()), (0, whole), out)
        card.write_bytes(b"another card")  # shorter than the Hub says but not a cut copy: never overwritten
        self.run_main(self.routes(), "follow", "acme/tts-a", "--task", "tts")
        self.assertEqual(card.read_bytes(), b"another card")
        self.assertEqual(list(card.parent.glob("*.tmp")), [])

    def test_an_unreadable_shortlist_falls_back_to_the_llm_features(self):
        sl = self.topic / "models" / "shortlist.json"
        sl.parent.mkdir(parents=True)
        sl.write_text('{"board": "tt', encoding="utf-8")
        code, out = self.run_main(self.routes(), "follow", "acme/tts-a")
        self.assertEqual(code, 0, out)
        self.assertIn("# models/shortlist.json is unreadable: the llm features are used; pass --task", out)
        self.assertIn("FEATURE\tacme/tts-a\ttool calling\t", out)

    def line_of(self, needle):
        lines = (self.topic / "models" / "hub" / "acme--tts-a.json").read_text(encoding="utf-8").split("\n")
        return next((n, l.strip()) for n, l in enumerate(lines, 1) if needle in l)

    def test_limits_unserved_repos_and_egress(self):
        code, out = self.run_main([], "follow", *[f"acme/m{i}" for i in range(6)])
        self.assertEqual((code, self.opener.calls), (2, []))
        code, out = self.run_main([], "follow", "not-a-repo")
        self.assertEqual(code, 2)
        code, out = self.run_main(self.routes(), "follow", "acme/gone", "acme/tts-a", "--task", "tts")
        self.assertEqual(code, 1)
        self.assertIn("FAIL\tacme/gone\tnot served by the Hub", out)
        self.assertIn("FACTS\tacme/tts-a\t", out)
        with mock.patch.object(m, "egress_terms", lambda cwd=None: [("acme", "forbidden.txt")]):
            code, out = self.run_main(self.routes(), "follow", "acme/tts-a")
        self.assertEqual((code, out.strip(), self.opener.calls), (2, "FAIL\tegress\tacme/tts-a contains a term from forbidden.txt",
                                                                 []))


if __name__ == "__main__":
    unittest.main()
