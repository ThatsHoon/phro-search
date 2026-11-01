"""Snapshot public model leaderboards, shortlist models for a use, and collect each model's facts and feature evidence.

usage: models.py snapshot  <topic_dir> --board B [--table T] [--lang L] [--clone] [--hardware H] [--refresh]
       models.py shortlist <topic_dir> --board B [--table T] [--lang L] [--metric COL] [--max-gb G]
                           [--license permissive|open|any] [--since YYYY-MM-DD] [--off-hub] [--top N]
       models.py follow    <topic_dir> <org/name>... [--need F1,F2] [--task asr|tts|llm]
boards: asr (Open ASR; tables english, multilingual, longform, private), tts (Open TTS; quality for one --lang, with
        --clone for voice cloning, and streaming for one --hardware), llm (Open LLM, frozen since 2025-03-20),
        slm (Open SLM), hub:<org/dataset> (the leaderboard of a Hub benchmark dataset, mostly self-reported)
Only the read-only routes in ROUTES are requested. HF_TOKEN is read from the environment, sent to huggingface.co only
and never printed. Requests are 1 s apart per host. A 429 or a 5xx is retried after 2, 4 and 8 s (after Retry-After
when it asks 60 s or less); a timeout (20 s without an answer) is retried once; any other status is not, nor a 403 or
503 from a bot check. All requests of one run share a deadline: 270 s for shortlist, under the 5-minute timeout the
models reference gives it, and 100 s for snapshot and follow, under the Bash tool's default 2 minutes. No request
starts and no retry waits past it.
Files are written whole or not at all (a temp file, then a rename). A same-day snapshot, a facts file or a card that an
earlier run left cut short is taken or fetched again instead of being used; a card that differs otherwise is kept.
output, tab-separated:
  SNAPSHOT <file>  <n> rows  <k> linked off the Hub  revision <sha>    then NEW <model> and GONE <model>, up to 20 each
  KEPT     <file>  (a snapshot of that board was already taken today)
  FRONT    <repo>  <metric>=<value>  measured|verified|self-reported  params  16-bit (or stored) size  4-bit size
           license  created  formats  notes
  MODEL    the same for a model off the front
  OFFHUB   <name>  <metric>=<value>  <link>   (no Hub repo: a hosted service, or a model the board does not link)
  FACTS    <repo>  <card file>  <facts file>
  FEATURE  <repo>  <feature>  <file>:<line>: <text>   or   not stated
  HOP      <repo>  <need>  paper|repo <url>   (where to look next for a need the card and config do not state)
  # <note>
  OK       <file>
  FAIL     <what>  <reason>
exit 0; 1 when the board or a model could not be read (also a reply of an unexpected shape); 2 for bad arguments, an egress hit or a changed board
(schema-drift: nothing is guessed).
"""
import argparse, hashlib, html, json, math, os, re, socket, ssl, sys, tempfile, time, unicodedata
import urllib.error, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.4.0"

HUB = "https://huggingface.co"
UA = f"Mozilla/5.0 (compatible; phro-search/{VERSION}; +https://github.com/ThatsHoon/phro-search)"
CAP = 10 * 1024 * 1024  # bytes per response
LOW, HIGH = "lower", "higher"
RESOLVE, TOP, FOLLOW, OVER = 40, 15, 5, 1.1  # rows looked up on the Hub, rows printed, models followed, budget slack
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
TAG, HREF = re.compile(r"<[^>]*>"), re.compile(r"""href=["']([^"']+)["']""")
DECOR = ("So", "Sk", "Mn", "Me", "Cf")  # arrows, flags, emoji and their joiners in headers
BACKOFF = (2, 4, 8)  # seconds before each retry of a 429 or a 5xx; a timeout is retried once
TIMEOUT = 20  # seconds one request may stall before it counts as a timeout
RETRY_AFTER_CAP = 60  # longest Retry-After honored, in seconds; a longer one gets the backoff
DEADLINE = {"shortlist": 270, "snapshot": 100, "follow": 100}  # seconds for all requests of one run, per command
BOT_CHECK = (b"just a moment", b"checking your browser", b"captcha", b"verify you are human", b"are you a robot",
             b"attention required", b"challenge-platform", b"/cdn-cgi/challenge", b"ddos-guard")

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\U0000061c\U0000200b-\U0000200f\U0000202a-\U0000202e\U00002060-\U00002064\U00002066-\U00002069\U0000feff]")
_QUOTES = str.maketrans("\U00002018\U00002019\U0000201a\U0000201b\U00002032\U0000201c\U0000201d\U0000201e\U0000201f\U00002033\U0000ff02\U0000ff07", "'''''\"\"\"\"\"\"'")


def clean(s, cap=300):
    """One printable line: control, bidi and zero-width characters dropped, quote lookalikes made ASCII, whitespace collapsed."""
    return " ".join(_CTRL.sub("", str(s)).translate(_QUOTES).split())[:cap]


def egress_terms(cwd=None):
    """(term, source) pairs from ~/.claude/phro-search/forbidden.txt (under the home folder, HOME and USERPROFILE, the
    places the hook's shell looks) and the nearest .phro/project.json at or above cwd."""
    found = []
    homes = [Path.home()] + [Path(os.environ[v]) for v in ("HOME", "USERPROFILE") if os.environ.get(v)]
    for path in dict.fromkeys(h.resolve() / ".claude" / "phro-search" / "forbidden.txt" for h in homes):
        if path.is_file():
            found += [(t.strip(), str(path)) for t in path.read_text(encoding="utf-8-sig").splitlines()
                      if t.strip() and not t.lstrip().startswith("#")]
    here = Path(cwd or os.getcwd()).resolve()
    for d in (here, *here.parents):
        p = d / ".phro" / "project.json"
        if p.is_file():
            try:
                terms = json.loads(p.read_text(encoding="utf-8-sig")).get("egress", {}).get("forbidden_terms", [])
            except (ValueError, AttributeError) as e:
                raise ValueError(f"{p}: {e}") from None
            if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
                raise ValueError(f"{p}: egress.forbidden_terms must be a list of strings")
            found += [(t.strip(), str(p)) for t in terms if t.strip()]
            break
    return [(t, s) for t, s in found if len(t) >= 2]


def _edge(c):
    return c.isascii() and c.isalnum()


def egress_hit(text, terms):
    """First (term, source) whose term appears in text, or None: NFKC and case-insensitive, also after
    percent-decoding; a term that starts or ends with an ASCII letter or digit must not touch another one there."""
    hay = {unicodedata.normalize("NFKC", h).casefold() for h in (text, urllib.parse.unquote_plus(text))}
    for term, source in terms:
        t = unicodedata.normalize("NFKC", term).casefold()
        pat = ("(?<![a-z0-9])" if _edge(t[0]) else "") + re.escape(t) + ("(?![a-z0-9])" if _edge(t[-1]) else "")
        if any(re.search(pat, h) for h in hay):
            return term, source
    return None


def table(at, model, metrics, speed=None, size=None, license=None, date=None, link=None, opt=None):
    return {"at": at, "model": model, "metrics": metrics, "speed": speed, "size": size, "license": license, "date": date,
            "link": link, "opt": opt or {}}


# One entry per board: its route, and per table where it sits, its model column and its metric columns with their
# direction. A table must carry every header named here (without decoration); other columns are kept as found.
# size is (column, parameters per unit); date is the day the repo was made, as the board states it; opt holds metric
# columns a table has only for some choices.
BOARDS = {
    "asr": {"route": "gradio-config", "space": "hf-audio/open_asr_leaderboard", "direction": LOW,
            "url": "https://hf-audio-open-asr-leaderboard.hf.space/config",
            "tables": {"english": table("leaderboard-table", "model", {"Average WER": LOW, "RTFx": HIGH}, speed="RTFx"),
                       "multilingual": table("multilingual-table", "Model", {"Average WER": LOW}),
                       "longform": table("longform-table", "Model", {"Average WER": LOW, "RTFx": HIGH}, speed="RTFx"),
                       "private": table("private-data-table", "Model",
                                        {"Average WER": LOW, "Avg Scripted": LOW, "Avg Conversational": LOW})}},
    "tts": {"route": "gradio-call", "space": "hf-audio/open_tts_leaderboard",
            "url": "https://hf-audio-open-tts-leaderboard.hf.space/gradio_api",
            "params": {"_refresh_leaderboard": ("version", "search", "langs", "datasets", "clone"),
                       "_refresh_streaming": ("mode", "version", "search")},
            "tables": {"quality": table("_refresh_leaderboard", "Model",
                                        {"Average WER": LOW, "Average RTFx": HIGH, "UTMOS (en)": HIGH},
                                        speed="Average RTFx", size=("Size (B)", 1e9), license="License",
                                        opt={"Average SIM": HIGH}),
                       "streaming": table("_refresh_streaming", "Model",
                                          {"TTFA p50 (ms)": LOW, "TTFA p95 (ms)": LOW, "RTFx": HIGH},
                                          speed="RTFx", size=("Size (B)", 1e9))}},
    "llm": {"route": "space-api", "space": "open-llm-leaderboard/open_llm_leaderboard", "frozen": "2025-03-20",
            "url": "https://open-llm-leaderboard-open-llm-leaderboard.hf.space/api/leaderboard/formatted",
            "tables": {"main": table(None, "name", {m: HIGH for m in ("average_score", "IFEval", "BBH", "MATH Level 5",
                                                                      "GPQA", "MUSR", "MMLU-PRO")},
                                     size=("params_billions", 1e9), license="hub_license", date="upload_date")}},
    "slm": {"route": "static-html", "space": "AxiomicLabs/Open_SLM_Leaderboard",
            "url": "https://axiomiclabs-open-slm-leaderboard.static.hf.space/index.html",
            "tables": {"main": table(None, "name", {m: HIGH for m in ("Intelligence Index", "hellaswag", "arc", "arcChall",
                                                                      "piqa", "arithmark3")},
                                     size=("params", 1), link="card")}},  # addedDate: when the board added it
}
SLM_INDEX = "97ac2e3647429545"  # hash of the page's index code that intelligence_index() follows; a change is drift
ROUTES = [re.compile(p) for p in (
    r"https://hf-audio-open-asr-leaderboard\.hf\.space/config",
    r"https://hf-audio-open-tts-leaderboard\.hf\.space/gradio_api/(info|call/_refresh_(leaderboard|streaming)(/[0-9a-f]+)?)",
    r"https://open-llm-leaderboard-open-llm-leaderboard\.hf\.space/api/leaderboard/formatted",
    r"https://axiomiclabs-open-slm-leaderboard\.static\.hf\.space/index\.html",
    r"https://huggingface\.co/api/(spaces|datasets)/[\w.-]+/[\w.-]+",
    r"https://huggingface\.co/api/datasets/[\w.-]+/[\w.-]+/leaderboard",
    r"https://huggingface\.co/api/models/[\w.-]+/[\w.-]+\?blobs=true",
    r"https://huggingface\.co/api/models\?filter=base_model%3Aquantized%3A[\w.-]+%2F[\w.-]+&limit=100",
    r"https://huggingface\.co/api/papers/\d{4}\.\d{4,5}",
    r"https://huggingface\.co/[\w.-]+/[\w.-]+/raw/[0-9a-f]{40}/(README\.md|config\.json)")]
GRADIO_CALL = re.compile(r"https://hf-audio-open-tts-leaderboard\.hf\.space/gradio_api/call/_refresh_(leaderboard|streaming)")
WEIGHT_FILES = (".safetensors", ".gguf", ".bin", ".pth", ".pt", ".ckpt", ".nemo", ".onnx")
QUANT_TAGS = ("gguf", "mlx", "onnx", "coreml", "openvino", "awq", "gptq", "exl2", "bitsandbytes")
CONFIG_KEYS = {"model_type", "architectures", "max_position_embeddings", "n_positions", "n_ctx", "max_seq_len", "seq_length",
               "max_sequence_length", "sliding_window", "num_hidden_layers", "n_layer", "num_layers", "hidden_size",
               "d_model", "n_embd", "vocab_size", "torch_dtype", "sampling_rate", "sample_rate", "max_source_positions",
               "max_target_positions", "num_mel_bins"}
LANGS = {"arabic": "ar", "cantonese": "yue", "chinese": "zh", "czech": "cs", "dutch": "nl", "english": "en",
         "finnish": "fi", "french": "fr", "german": "de", "greek": "el", "hindi": "hi", "italian": "it", "japanese": "ja",
         "korean": "ko", "polish": "pl", "portuguese": "pt", "romanian": "ro", "russian": "ru", "spanish": "es",
         "turkish": "tr", "vietnamese": "vi"}
STREAM, LANG_LINE = r"\bstream(ing|s)?\b", r"\b\d+\+?\s+(\w+\s+)?languages\b|multilingual|languages? support|^\s*language:"
FEATURES = {  # grep patterns per task, matched case-insensitively against the card and the facts file
    "asr": (("streaming", STREAM), ("timestamps", r"time[\s_-]?stamp"), ("long-form", r"long[\s_-]?form|long audio|chunk"),
            ("language identification", r"language (identification|detection)|\blid\b|detects? the language"),
            ("diarization", r"diari[sz]"),
            ("context biasing", r"context[\s_-]?bias|hotword|(word|keyword)[\s_-]?boost|initial[\s_]prompt|context prompt")),
    "tts": (("voice cloning", r"voice[\s_-]?clon|clon(e|ing) (a |any |the )?voices?|zero[\s_-]?shot|reference (audio|speech|voice)"
             r"|speaker prompt"), ("streaming", STREAM),
            ("emotion or style control", r"emotion|(speaking|voice) style|style control|voice design|prosody|instruction"),
            ("languages", LANG_LINE), ("sample rate", r"\b\d{1,2}(\.\d+)? ?khz\b|\b\d{4,5} ?hz\b|sampl(e|ing)[\s_-]?rate")),
    "llm": (("context length", r"context (length|window)|max_position_embeddings|context_length|\b\d+k (tokens|context)"),
            ("tool calling", r"tool[\s_-]?(use|call)|function[\s_-]?call"),
            ("structured output", r"json (mode|schema)|structured output|constrained decoding|\bgrammar\b"),
            ("reasoning mode", r"thinking|reasoning (mode|model|effort|budget)|<think>|chain[\s_-]?of[\s_-]?thought"),
            ("image or audio input", r"\bimage|vision|audio input|multimodal"),
            ("quantized formats", r"gguf|\bawq\b|gptq|\bint[48]\b|\b[48][\s_-]?bit|\bmlx\b|onnx")),
}


class Fail(Exception):
    """A short reason; code is the HTTP status when there was one."""

    def __init__(self, reason, code=None):
        super().__init__(reason)
        self.code = code


class Drift(Exception):
    """The board no longer has the shape the registry expects."""


class Usage(Exception):
    """A bad argument, with what would be accepted."""


class _Redirect(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only within the host asked, so the token never leaves huggingface.co."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            raise urllib.error.URLError("redirect to another host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_Redirect)
_last = {}  # host -> monotonic time of its last request
_end = None  # monotonic time when this run's requests stop; set by main


def left():
    """Seconds until the run deadline; infinite outside a run."""
    return float("inf") if _end is None else _end - time.monotonic()


def bot_check(e):
    """True for a 403 or 503 from a bot check (a wall that no retry passes)."""
    if e.code not in (403, 503):
        return False
    if str((e.headers or {}).get("cf-mitigated", "")).strip().casefold() == "challenge":
        return True
    try:
        body = (e.read(8192) or b"").lower()
    except Exception:  # the error body may be gone or cut; then it is no proof of a wall
        body = b""
    return any(p in body for p in BOT_CHECK)


def retry_wait(e, backoff):
    """Seconds before retrying HTTPError e: its Retry-After when it asks RETRY_AFTER_CAP or less, else backoff."""
    ra = str((e.headers or {}).get("Retry-After") or "").strip()
    return int(ra) if ra.isascii() and ra.isdigit() and int(ra) <= RETRY_AFTER_CAP else backoff


def fetch(url, data=None):
    """Body of a registry route (a POST with JSON data for a Gradio call), at most CAP bytes, under the retry policy in
    the module docstring; anything else raises Fail."""
    if not any(r.fullmatch(url) for r in ROUTES) or (data is not None and not GRADIO_CALL.fullmatch(url)):
        raise Fail("not a registry route")
    host = urllib.parse.urlsplit(url).hostname
    headers = {"User-Agent": UA}
    token = os.environ.get("HF_TOKEN", "").strip()
    if token and host == "huggingface.co":
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        body, headers["Content-Type"] = json.dumps(data).encode(), "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    timeouts = 0
    for backoff in (*BACKOFF, None):
        wait = _last.get(host, float("-inf")) + 1 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        if left() <= 0:
            raise Fail("run deadline reached")
        _last[host] = time.monotonic()
        try:
            with OPENER.open(req, timeout=min(TIMEOUT, max(1, left()))) as r:
                out = r.read(CAP + 1)
        except urllib.error.HTTPError as e:
            if bot_check(e):
                raise Fail(f"http {e.code}: bot check", e.code) from None
            if not (e.code == 429 or 500 <= e.code < 600) or backoff is None:
                raise Fail(f"http {e.code}", e.code) from None
            why, wait = f"http {e.code}", retry_wait(e, backoff)
        except Exception as e:  # any other network error becomes a short reason, never a traceback
            e = e.reason if isinstance(e, urllib.error.URLError) else e
            kinds = ((socket.gaierror, "dns"), (ssl.SSLError, "tls"), (TimeoutError, "timeout"))
            why = next((w for t, w in kinds if isinstance(e, t)), None)
            timeouts += why == "timeout"
            if why != "timeout" or backoff is None or timeouts > 1:
                raise Fail(why or clean(e if isinstance(e, str) else type(e).__name__, 80)) from None
            wait = backoff
        else:
            if len(out) > CAP:
                raise Fail("too large")
            return out
        if wait > left():
            raise Fail(f"{why}; run deadline reached")
        time.sleep(wait)


def get(url, data=None):
    try:
        return json.loads(fetch(url, data))
    except ValueError:
        raise Fail("unreadable response") from None


def odd(e, where):
    """The FAIL reason for a reply of an unexpected shape, which raised e."""
    msg = clean(e, 120)
    return f"unexpected reply from the {where}: {type(e).__name__}" + (f": {msg}" if msg else "")


def label(h):
    """A header without its decoration (arrows, flags, emoji), in the board's own words."""
    return " ".join("".join(c for c in str(h) if unicodedata.category(c) not in DECOR).split())


def text(v):
    """A cell as the board shows it: markup stripped (footnote marks kept), entities decoded, on one line."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return clean(html.unescape(TAG.sub("", str(v))), 300)


def num(v):
    try:
        x = float(str(v).replace(",", ""))
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def repo_of(link):
    """The Hub repo a board links to, or None for a link elsewhere (a hosted service)."""
    p = urllib.parse.urlsplit(link or "")
    parts = [x for x in p.path.split("/") if x]
    if p.hostname != "huggingface.co" or len(parts) < 2 or parts[0] in ("spaces", "datasets", "api", "docs", "blog"):
        return None
    return f"{parts[0]}/{parts[1]}" if REPO.fullmatch(f"{parts[0]}/{parts[1]}") else None


def candidate(name, link):
    """The Hub repo to look up for a board row: the repo its link points to, else its name without the variant suffix
    and footnote marks a board adds; None when neither names a repo."""
    bare = re.sub(r"\s*\(.*$", "", name or "")
    bare = re.sub(r"[\s*\U000000b2\U000000b3\U000000b9\U00002070-\U0000209f\U00002020\U00002021]+$", "", bare)
    return repo_of(link) or (bare if REPO.fullmatch(bare) else None)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def board(name, tname=None):
    """(registry entry, table, table name) for a board name and an optional table."""
    if name.startswith("hub:"):
        did = name[4:]
        if not REPO.fullmatch(did):
            raise Usage("a Hub board is hub:<org>/<dataset>")
        b = {"route": "hub-leaderboard", "dataset": did, "url": f"{HUB}/api/datasets/{did}/leaderboard",
             "tables": {"main": table(None, "modelId", {"value": HIGH}, size=("num_parameters", 1))}}
    elif name in BOARDS:
        b = BOARDS[name]
    else:
        raise Usage(f"--board is one of {', '.join(BOARDS)} or hub:<org>/<dataset>")
    tname = tname or next(iter(b["tables"]))
    if tname not in b["tables"]:
        raise Usage(f"--table for {name}: {', '.join(b['tables'])}")
    return b, b["tables"][tname], tname


def stem_of(args, b, tname):
    """board-<board>[-<table>][-<lang>[-clone] or -<hardware>]: the snapshot name before its date."""
    parts = [args.board.replace("/", "-").replace(":", "-")]
    if len(b["tables"]) > 1:
        parts.append(tname)
    if tname == "quality":
        parts += [args.lang or "english"] + (["clone"] if args.clone else [])
    elif tname == "streaming":
        parts.append(args.hardware or "a100")
    return "board-" + "-".join(slug(p) for p in parts)


def write_atomic(path, data):
    """Write text (UTF-8, LF line ends) or bytes to path through a temp file in its folder and os.replace, so a crash
    never leaves a cut file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def whole_snapshot(path):
    """True when a snapshot file is complete: its meta line, its header, rows with as many cells, a final newline."""
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = raw.split("\n")
    if not raw.endswith("\n") or len(lines) < 3 or not lines[0].startswith("# board="):
        return False
    cells = lines[1].count("\t")
    return all(line.count("\t") == cells for line in lines[2:-1])


def snapshots(src, stem):
    """The snapshot files of a stem, oldest first."""
    pat = re.compile(re.escape(stem) + r"-(\d{4}-\d{2}-\d{2})(?:-(\d+))?\.tsv")
    found = [(m.group(1), int(m.group(2) or 1), p) for p in src.glob(stem + "-*.tsv") if (m := pat.fullmatch(p.name))]
    return [p for *_, p in sorted(found)]


def read_snapshot(path):
    lines = path.read_text(encoding="utf-8").split("\n")
    meta = dict(kv.split("=", 1) for kv in lines[0][2:].split(" ") if "=" in kv)
    heads = lines[1].split("\t")
    return meta, heads, [dict(zip(heads, line.split("\t"))) for line in lines[2:] if line]


# Board readers: each returns (headers, rows), the rows as lists of the board's raw values.

def read_gradio_config(b, t, args):
    cfg = get(b["url"])
    df = next((c for c in cfg.get("components", []) if c.get("type") == "dataframe"
               and (c.get("props") or {}).get("elem_id") == t["at"]), None)
    if df is None:
        raise Drift(f"no table {t['at']}")
    v = df["props"].get("value") or {}
    return v.get("headers") or [], v.get("data") or []


def read_gradio_call(b, t, args):
    """One read-only Gradio endpoint, its parameters checked against the registry and its choices taken from the Space."""
    ep = (get(b["url"] + "/info").get("named_endpoints") or {}).get("/" + t["at"]) or {}
    params = {p.get("parameter_name"): p.get("type") or {} for p in ep.get("parameters", [])}
    if tuple(params) != b["params"][t["at"]] or "latest" not in params["version"].get("enum", []):
        raise Drift(f"/{t['at']} takes {', '.join(map(str, params)) or 'nothing'}")
    if t["at"] == "_refresh_leaderboard":
        langs = params["langs"].get("items", {}).get("enum") or []
        lang = next((c for c in langs if label(c).casefold() == (args.lang or "English").casefold()), None)
        if lang is None:
            raise Usage(f"--lang for tts: {', '.join(label(c) for c in langs)}")
        data = ["latest", "", [lang], params["datasets"].get("items", {}).get("enum") or [], bool(args.clone)]
    else:
        modes = params["mode"].get("enum") or []
        hw = next((h for h in modes if h.casefold() == (args.hardware or "A100").casefold()), None)
        if hw is None:
            raise Usage(f"--hardware for tts: {', '.join(modes)}")
        data = [hw, "latest", ""]
    event = str(get(f"{b['url']}/call/{t['at']}", {"data": data}).get("event_id", ""))
    if not re.fullmatch(r"[0-9a-f]+", event):
        raise Fail("no event id")
    stream = fetch(f"{b['url']}/call/{t['at']}/{event}").decode("utf-8", "replace")
    kinds, payload = re.findall(r"^event: *(\w+)", stream, re.M), re.findall(r"^data: *(.*)$", stream, re.M)
    if not kinds or kinds[-1] != "complete" or not payload:
        raise Fail("the board answered with an error")
    out = json.loads(payload[-1])
    v = out[0].get("value") if isinstance(out, list) and out and isinstance(out[0], dict) else None
    if not isinstance(v, dict):
        raise Drift("no table in the answer")
    return v.get("headers") or [], v.get("data") or []


def read_llm(b, t, args):
    """One row per evaluated model revision: the leaf values of model, features and metadata under their own keys, and
    per evaluation its normalized score (what the board shows) under its own name."""
    d = get(b["url"])
    if not isinstance(d, list) or not all(isinstance(e, dict) and isinstance(e.get("evaluations"), dict) for e in d):
        raise Drift("not a list of models with evaluations")
    recs = []
    for e in d:
        r = {k: v for part in ("model", "features", "metadata") for k, v in (e.get(part) or {}).items()
             if not isinstance(v, (dict, list))}
        r.update({str(ev.get("name")): ev.get("normalized_score") for ev in e["evaluations"].values()
                  if isinstance(ev, dict)})
        recs.append(r)
    heads = list(dict.fromkeys(k for r in recs for k in r))
    return heads, [[r.get(h) for h in heads] for r in recs]


SLM_FIELD = re.compile(r"(\w+):\s*('(?:[^'\\]|\\.)*'|-?\d+(?:\.\d+)?|null|true|false)")


def js_block(page, start):
    """The text from start to the brace that closes the first one after it."""
    depth, i = 0, page.find("{", start)
    for j in range(i, len(page)):
        depth += {"{": 1, "}": -1}.get(page[j], 0)
        if depth == 0:
            return page[start:j + 1]
    return ""


def index_code(page):
    parts = [js_block(page, page.find(f"function {n}(")) for n in ("normalizeFromChance", "getIntelligenceIndex")
             if f"function {n}(" in page]
    return hashlib.sha256("".join("".join(p.split()) for p in parts).encode()).hexdigest()[:16] if len(parts) == 2 else ""


def intelligence_index(m, base):
    """The SLM board's Intelligence Index: HellaSwag, ARC (Easy and Challenge averaged) and PIQA at weight 1 and
    ArithMark-3 at 0.65, each mapped from chance (0) to perfect (100); None with fewer than 2 of them."""
    def norm(v, chance):
        return (v - chance) / (100 - chance) * 100
    parts = [norm(m["hellaswag"], base["hellaswag"])] if m.get("hellaswag") is not None else []
    arcs = [m[k] for k in ("arc", "arcChall") if m.get(k) is not None]
    if arcs:
        parts.append(norm(sum(arcs) / len(arcs), base["arc"]))
    if m.get("piqa") is not None:
        parts.append(norm(m["piqa"], base["piqa"]))
    a3 = m.get("arithmark3")
    if len(parts) + (a3 is not None) < 2:
        return None
    w = 0.65 if a3 is not None else 0
    return (sum(parts) + (norm(a3, base["arithmark3"]) * w if a3 is not None else 0)) / (len(parts) + w)


def read_slm(b, t, args):
    """The MODELS lines of the page, key by key; commented lines are skipped and the index is computed as the page does."""
    page = fetch(b["url"]).decode("utf-8", "replace")
    block = re.search(r"const MODELS = \[(.*?)\n\s*\];", page, re.S)
    base = re.search(r"const RANDOM_BASELINES = \{(.*?)\}", page, re.S)
    base = {k: float(v) for k, v in re.findall(r"(\w+):\s*(-?\d+(?:\.\d+)?)", base.group(1))} if base else {}
    if not block or not {"hellaswag", "arc", "piqa", "arithmark3"} <= set(base) or index_code(page) != SLM_INDEX:
        raise Drift("the MODELS list or the Intelligence Index code changed")
    recs = []
    for line in block.group(1).split("\n"):
        line = line.strip()
        if line.startswith("{") and re.match(r"\{\s*name:", line):  # a commented model starts with //
            recs.append({k: v[1:-1].replace("\\'", "'") if v.startswith("'") else None if v == "null" else v
                         for k, v in SLM_FIELD.findall(line)})
    heads = list(dict.fromkeys(k for r in recs for k in r)) + ["Intelligence Index"]
    rows = []
    for r in recs:
        idx = intelligence_index({k: num(v) for k, v in r.items()}, base)
        rows.append([r.get(h) for h in heads[:-1]] + [None if idx is None else round(idx, 2)])
    return heads, rows


def read_hub(b, t, args):
    d = get(b["url"])
    cols = ("rank", "modelId", "value", "verified", "source", "lower_is_better", "num_parameters", "notes")
    if not isinstance(d, list) or not all(isinstance(e, dict) and {"rank", "modelId", "value"} <= set(e) for e in d):
        raise Drift("an entry lacks rank, modelId or value")
    return list(cols), [[e.get(c) if c != "source" else (e.get("source") or {}).get("url") for c in cols] for e in d]


READ = {"gradio-config": read_gradio_config, "gradio-call": read_gradio_call, "space-api": read_llm,
        "static-html": read_slm, "hub-leaderboard": read_hub}


def revision(b):
    kind, rid = ("datasets", b["dataset"]) if "dataset" in b else ("spaces", b["space"])
    try:
        return str(get(f"{HUB}/api/{kind}/{rid}").get("sha") or "unknown")
    except Fail:
        return "unknown"


def snapshot(args, topic):
    b, t, tname = board(args.board, args.table)
    src = topic / "sources"
    stem, day = stem_of(args, b, tname), today()
    old = snapshots(src, stem)
    same = [p for p in old if p.name.startswith(f"{stem}-{day}")]
    kept = [p for p in same if whole_snapshot(p)]
    if kept and not args.refresh:
        print(f"KEPT\t{kept[-1].as_posix()}\tone snapshot per board and day; --refresh takes another")
        return 0
    old = [p for p in old if whole_snapshot(p)]  # a cut file is no baseline
    heads, rows = READ[b["route"]](b, t, args)
    labels = [label(h) for h in heads]
    need = [t["model"], *t["metrics"], *[x for x in (t["speed"], t["size"] and t["size"][0], t["license"], t["date"],
                                                      t["link"]) if x]]
    missing = [h for h in dict.fromkeys(need) if h not in labels]
    if missing or len(set(labels)) < len(labels):
        raise Drift(("missing " + ", ".join(missing) if missing else "duplicate headers") + "; found " + ", ".join(labels))
    mi = labels.index(t["model"])
    if b["route"] in ("gradio-config", "gradio-call"):
        links = [html.unescape(m.group(1)) if (m := HREF.search(str(r[mi]))) else "" for r in rows]
    elif t["link"]:
        links = [str(r[labels.index(t["link"])] or "") for r in rows]
    else:
        links = [f"{HUB}/{r[mi]}" for r in rows]
    meta = {"board": args.board, "table": tname, "route": b["route"], "url": b["url"] + (f"/call/{t['at']}" if
            b["route"] == "gradio-call" else ""), "revision": revision(b),
            "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if tname == "quality":
        meta.update(lang=slug(args.lang or "english"), clone=str(bool(args.clone)).lower())
    elif tname == "streaming":
        meta["hardware"] = slug(args.hardware or "a100")
    n = len(same) + 1
    while (path := src / (f"{stem}-{day}-{n}.tsv" if n > 1 else f"{stem}-{day}.tsv")).exists():
        n += 1  # a cut snapshot stays where it is; sources are never overwritten
    body = ["# " + " ".join(f"{k}={v}" for k, v in meta.items()), "\t".join(labels + ["link"])]
    body += ["\t".join([text(c) for c in r] + [clean(link, 300)]) for r, link in zip(rows, links)]
    write_atomic(path, "\n".join(body) + "\n")
    keys = lambda p: {r[t["model"]] for r in read_snapshot(p)[2]}
    now = keys(path)
    print(f"SNAPSHOT\t{path.as_posix()}\t{len(rows)} rows\t{sum(not repo_of(x) for x in links)} linked off the Hub"
          f"\trevision {meta['revision'][:7]}")
    if old:
        before = keys(old[-1])
        for kind, names in (("NEW", now - before), ("GONE", before - now)):
            for n in sorted(names)[:20]:
                print(f"{kind}\t{clean(n, 120)}")
        print(f"# since {old[-1].name}: {len(now - before)} new, {len(before - now)} gone")
    if b.get("frozen"):
        print(f"# frozen since {b['frozen']}: later models are absent; hub:<org/dataset> boards cover them")
    print(f"OK\t{path.as_posix()}")
    return 0


# Hub facts

def width(dtype):
    """Bytes per parameter of a safetensors dtype name (BF16 2, F8_E4M3 1, BOOL 1)."""
    bits = re.search(r"\d+", dtype)
    return int(bits.group()) / 8 if bits else 1


def license_class(lic):
    """permissive, open (a model-specific or copyleft license: terms to read), non-commercial, or unknown."""
    s = re.sub(r"[\s_]+", "-", str(lic or "").strip().lower())
    if not s or s in ("other", "unknown", "custom", "none") or "://" in s:
        return "unknown"
    if re.search(r"(^|-)nc(-|$)|non-?commercial|research", s):
        return "non-commercial"
    if re.match(r"(apache|mit$|bsd|cc0|isc$|zlib|unlicense|bsl-1)", s) or re.fullmatch(r"cc-by-\d(\.\d)?", s):
        return "permissive"
    return "open"


def formats(files, tags, library):
    names = [f.get("rfilename", "") for f in files]
    has = lambda *ext: any(n.endswith(ext) for n in names)
    found = (("safetensors", has(".safetensors")), ("gguf", has(".gguf")), ("onnx", has(".onnx")),
             ("mlx", "mlx" in tags or library == "mlx"),
             ("coreml", has(".mlmodel") or any(".mlpackage/" in n or ".mlmodelc/" in n for n in names)),
             ("openvino", "openvino" in tags or has("openvino_model.xml")), ("pytorch", has(".bin", ".pth", ".pt")))
    return [name for name, ok in found if ok]


def facts(repo):
    """The Hub facts of a repo, or None when the Hub does not serve it (401 or 404: not there, or private)."""
    try:
        m = get(f"{HUB}/api/models/{repo}?blobs=true")
    except Fail as e:
        if e.code in (401, 404):
            return None
        raise
    tags, card = m.get("tags") or [], m.get("cardData") or {}
    st, gg, files = m.get("safetensors") or {}, m.get("gguf") or {}, m.get("siblings") or []
    per = {k: v for k, v in (st.get("parameters") or {}).items() if isinstance(v, int)}
    params = st.get("total") or gg.get("total") or None
    weights = [(f["rfilename"], f.get("size") or 0) for f in files if f.get("rfilename", "").endswith(WEIGHT_FILES)]
    largest = max((s for _, s in weights), default=0)
    top = max((s for n, s in weights if "/" not in n), default=0)  # a repo's variants and parts sit in folders
    stored, source = sum(n * width(d) for d, n in per.items()), "safetensors dtypes"
    if not stored and not gg:
        stored, source = largest, "largest weight file"
    lic = card.get("license") or next((x[8:] for x in tags if x.startswith("license:")), None)
    lic = lic[0] if isinstance(lic, list) and lic else lic
    langs = card.get("language") or []
    base = card.get("base_model") or [x[11:] for x in tags if x.startswith("base_model:") and x.count(":") == 1]
    return {"repo": repo, "url": f"{HUB}/{repo}", "sha": m.get("sha"), "pipeline_tag": m.get("pipeline_tag"),
            "library": m.get("library_name"), "created": (m.get("createdAt") or "")[:10] or None,
            "modified": (m.get("lastModified") or "")[:10] or None, "gated": m.get("gated") or False,
            "license": lic, "license_name": card.get("license_name"), "license_link": card.get("license_link"),
            "license_class": license_class(card.get("license_name") if lic == "other" and card.get("license_name") else lic),
            "languages": [langs] if isinstance(langs, str) else list(langs), "base_model": base,
            "arxiv": [x[6:] for x in tags if x.startswith("arxiv:")], "params": params, "params_by_dtype": per,
            "weight_gb": round(stored / 1e9, 3) if stored else None, "weight_source": source if stored else None,
            "largest_file_gb": round(top / 1e9, 3) if top else None,
            "formats": formats(files, tags, m.get("library_name")),
            "gguf": {k: gg[k] for k in ("architecture", "context_length") if gg.get(k)} or None,
            "config": {k: v for k, v in (m.get("config") or {}).items() if k in ("architectures", "model_type")},
            "downloads": m.get("downloads"), "likes": m.get("likes"),
            "card": any(f.get("rfilename") == "README.md" for f in files),
            "config_file": any(f.get("rfilename") == "config.json" for f in files),
            "files": [f.get("rfilename") for f in files][:300], "fetched": today(),
            "_card_size": next((f.get("size") for f in files if f.get("rfilename") == "README.md"), None)}


def hub_path(topic, repo):
    return topic / "models" / "hub" / (repo.replace("/", "--") + ".json")


def save_facts(topic, f):
    """Write a repo's facts, one key per line; keys starting with _ are for this run only."""
    path = hub_path(topic, f["repo"])
    write_atomic(path, json.dumps({k: v for k, v in f.items() if not k.startswith("_")}, indent=1,
                                  ensure_ascii=False) + "\n")
    return path


def cached_facts(topic, repo):
    """Today's facts file of a repo when it is whole, else the facts fetched again and saved."""
    path = hub_path(topic, repo)
    if path.is_file():
        try:
            f = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError):  # cut short or unreadable: fetched again
            f = None
        if isinstance(f, dict) and f.get("fetched") == today():
            return f
    f = facts(repo)
    if f:
        save_facts(topic, f)
    return f


def derivatives(repo):
    """Quantized models whose base is repo: how many (100 at most), in which formats, the first 10."""
    try:
        d = get(f"{HUB}/api/models?filter={urllib.parse.quote('base_model:quantized:' + repo, safe='')}&limit=100")
    except Fail:
        return None
    seen = {q for x in d for q in QUANT_TAGS if q in (x.get("tags") or [])}
    return {"count": len(d), "formats": sorted(seen), "first": [x.get("id") for x in d[:10]]}


# Shortlist

def sizes(c):
    """16-bit and 4-bit weight sizes in GB from the parameter count: 2 bytes a parameter, and 0.5 bytes plus 10 percent
    for scales and the layers left unquantized. The stored size depends on the dtype an uploader chose."""
    p = c["params"]
    c["gb_16"], c["gb_4bit"] = (round(p * 2 / 1e9, 3), round(p * 0.5 * OVER / 1e9, 3)) if p else (None, None)


def fit(c, budget):
    """(reason to drop, note) for a model's weights against a memory budget in GB."""
    w, q = c["gb_16"] or c["weight_gb"], c["gb_4bit"]
    if budget is None or (w is not None and w <= budget):
        return None, None
    if w is None and q is None:
        return None, "size unknown"
    if q is not None and q <= budget:
        return None, "fits at 4-bit"
    over = min(x for x in (w, q) if x is not None)
    if over <= budget * OVER:
        return None, f"over budget by {round((over / budget - 1) * 100)}%"
    return f"over budget: {over:.2f} GB at {'4-bit' if q is not None else 'stored size'}", None


def license_drop(c, args):
    cls = c["license_class"]
    bad = (args.license == "permissive" and cls != "permissive") or (args.license == "open" and cls == "non-commercial")
    return f"license {cls}" if bad else None


def since_drop(c, args):
    return f"created before {args.since}" if args.since and c["created"] and c["created"] < args.since else None


def langs_ok(c, lang):
    """(reason to drop, note) for the card's languages, which their authors state."""
    have = [str(x).lower() for x in c["languages"]]
    code = LANGS.get(lang.lower(), lang.lower())
    if not have:
        return None, "languages not stated"
    if code in have or lang.lower() in have:
        return None, None
    return (None, "card says multilingual") if "multilingual" in have else (f"card does not list {lang}", None)


def pareto(models, metric, direction, speed):
    """Mark the models that no other one beats on the metric, the parameter count and (on speech boards) the speed at
    once; an unknown size or speed counts as the worst."""
    def vec(c):
        v, s = c["scores"][metric], c["scores"].get(speed) if speed else 0
        return (v if direction == HIGH else -v, -(c["params"] or math.inf), -math.inf if s is None else s)
    vs = [vec(c) for c in models]
    for c, a in zip(models, vs):
        c["front"] = not any(o != a and all(x >= y for x, y in zip(o, a)) for o in vs)


def gb(x):
    return "?" if x is None else f"{x:.2f} GB"


def row_line(c, metric, speed):
    p = "?" if c["params"] is None else f"{c['params'] / 1e9:.3g}B"
    score = f"{metric}={c['scores'][metric]:g}" + (f" {speed}={c['scores'][speed]:g}" if speed and
                                                    c["scores"].get(speed) is not None else "")
    size = f"{gb(c['gb_16'])} at 16-bit" if c["gb_16"] else f"{gb(c['weight_gb'])} stored"
    return "\t".join(["FRONT" if c.get("front") else "MODEL", c["repo"] or c["name"], score, c["label"], f"params {p}", size,
                      f"{gb(c['gb_4bit'])} at 4-bit", f"{c['license_class']} ({clean(c['license'] or '?', 40)})",
                      f"created {c['created'] or '?'}", ",".join(c["formats"]) or "-", "; ".join(c["notes"]) or "-"])


def shortlist(args, topic):
    tname = args.table or ("multilingual" if args.board == "asr" and args.lang else None)
    b, t, tname = board(args.board, tname)
    files = [p for p in snapshots(topic / "sources", stem_of(args, b, tname)) if whole_snapshot(p)]  # never a cut one
    if not files:
        raise Usage(f"no snapshot of {args.board} {tname} in {topic.as_posix()}/sources yet: run snapshot first")
    meta, heads, rows = read_snapshot(files[-1])
    lang_col = next((h for h in heads if h.casefold() == args.lang.casefold()), None) \
        if args.board == "asr" and args.lang else None
    want = args.metric or lang_col or next(iter(t["metrics"]))
    metric = next((h for h in heads if h.casefold() == want.casefold()), None)
    direction = {**t["metrics"], **t["opt"]}.get(metric) or (b.get("direction") if metric and metric != t["model"]
                                                              else None)
    if b["route"] == "hub-leaderboard":
        direction = LOW if any(r.get("lower_is_better") == "true" for r in rows) else HIGH
    if direction is None:
        raise Usage(f"--metric for {args.board} {tname}: {', '.join([*t['metrics'], *t['opt']])}")
    speed = t["speed"] if t["speed"] != metric else None
    board_langs = bool(lang_col) or (args.board == "tts" and tname == "quality" and bool(args.lang))
    cands, dropped = {}, Counter()
    for r in rows:
        if r.get("is_flagged") == "true":
            dropped["flagged by the board"] += 1
            continue
        v = num(r.get(metric))
        if v is None:
            dropped[f"no {metric} score"] += 1
            continue
        repo = candidate(r[t["model"]], r.get("link"))
        key = repo or r[t["model"]]
        if key in cands and (v >= cands[key]["scores"][metric]) == (direction == LOW):
            continue  # one row per model: its best
        size = num(r.get(t["size"][0])) if t["size"] else None
        cands[key] = {"repo": repo, "name": r[t["model"]], "off_hub": repo is None, "link": r.get("link") or None,
                      "scores": {metric: v, **({speed: num(r.get(speed))} if speed else {})},
                      "label": "measured" if b["route"] != "hub-leaderboard" else
                      "verified" if r.get("verified") == "true" else "self-reported", "source": r.get("source") or None,
                      "params": size * t["size"][1] if size is not None else None, "weight_gb": None,
                      "license": (r.get(t["license"]) or None) if t["license"] else None, "license_class": "unknown",
                      "languages": [], "languages_label": "board" if board_langs else None,
                      "created": (r.get(t["date"]) or None) if t["date"] else None, "formats": [], "gated": False,
                      "notes": [], "front": False}
    order = sorted(cands.values(), key=lambda c: c["scores"][metric], reverse=direction == HIGH)
    looked = 0
    for c in order:
        c["license_class"] = license_class(c["license"])
        sizes(c)
        # what the board's own columns already rule out costs no Hub request
        c["dropped"] = (c["license_class"] in ("open", "non-commercial") and license_drop(c, args)) \
            or since_drop(c, args) or fit(c, args.max_gb)[0]
        if c["dropped"] or c["off_hub"]:
            continue
        if looked >= RESOLVE:
            c["dropped"] = "not looked up"
            continue
        looked += 1
        try:
            f = cached_facts(topic, c["repo"])
        except Fail as e:
            c["notes"].append(f"Hub facts failed: {e}")
            continue
        if f is None:
            c["off_hub"] = True
            continue
        c.update(created=c["created"] or f["created"], formats=f["formats"], languages=f["languages"],
                 params=f["params"] or c["params"], weight_gb=f["weight_gb"], gated=f["gated"])
        if f["license"]:
            c["license"] = f["license_name"] if f["license"] == "other" and f["license_name"] else f["license"]
            c["license_class"] = f["license_class"]
        big = f.get("largest_file_gb")
        if c["params"] and big and big * 1e9 > c["params"] * 4 * OVER:  # more bytes in one file than 4 a parameter
            c["notes"].append(f"params {c['params'] / 1e9:.3g}B miss part of the weights ({big:.2f} GB in one file)")
            c["params"], c["weight_gb"] = None, max(c["weight_gb"] or 0, big)
        if c["name"] not in (c["repo"], c["repo"].split("/")[1]):  # a variant or runtime the board ran
            c["notes"].append(f"board row: {clean(c['name'], 80)}")
        sizes(c)
        why, note = fit(c, args.max_gb)
        lwhy = None
        if args.lang and not board_langs:
            c["languages_label"] = "self-reported"
            lwhy, lnote = langs_ok(c, args.lang)
            c["notes"] += [lnote] if lnote else []
        c["dropped"] = license_drop(c, args) or since_drop(c, args) or lwhy or why
        c["notes"] += [n for n in (note, f["gated"] and "gated: accept its terms on the Hub",
                                   c["license_class"] == "unknown" and "license unknown: read it") if n]
    kept = [c for c in order if not c["dropped"] and (not c["off_hub"] or args.off_hub)]
    pareto(kept, metric, direction, speed)
    for c in kept:
        if c["front"] and not c["off_hub"]:
            c["quantized"] = derivatives(c["repo"])
            if c["quantized"] and c["quantized"]["formats"]:
                c["notes"].append("quantized: " + ",".join(c["quantized"]["formats"]))
    for c in order:
        if c["dropped"] and c["dropped"] != "not looked up":
            dropped[c["dropped"].split(":")[0]] += 1
    out = topic / "models" / "shortlist.json"
    filters = {k: getattr(args, k) for k in ("lang", "max_gb", "license", "since", "off_hub")}
    write_atomic(out, json.dumps({"board": args.board, "table": tname, "snapshot": files[-1].name, "metric": metric,
                                  "direction": direction, "filters": filters, "models": order}, indent=1,
                                 ensure_ascii=False) + "\n")
    off = [c for c in order if c["off_hub"] and not c["dropped"]]
    print(f"# {args.board} {tname}: {metric}, {direction} is better; {files[-1].name}; {len(order)} models, "
          f"{len(kept)} kept, {sum(c['front'] for c in kept)} on the front, {len(off)} off the Hub")
    if args.lang and not board_langs:
        print(f"# {args.board} {tname} measures no {args.lang}: the cards' own language lists filter instead (self-reported)")
    for c in sorted(kept, key=lambda c: not c["front"])[:min(args.top, TOP)]:
        print(row_line(c, metric, speed))
    if not args.off_hub:
        for c in off[:5]:
            print(f"OFFHUB\t{clean(c['name'], 80)}\t{metric}={c['scores'][metric]:g}\t{c['link'] or 'no link'}")
    if dropped:
        print("# dropped: " + ", ".join(f"{n} {why}" for why, n in dropped.most_common()))
    unseen = sum(c["dropped"] == "not looked up" for c in order)
    if unseen:
        early = [f for f, k in (("--max-gb", "size"), ("--license", "license"), ("--since", "date")) if t[k]]
        print(f"# {unseen} lower-ranked models were not looked up" +
              (f"; {', '.join(early)} filter on the board's columns before the lookup" if early else ""))
    if kept:
        print("# sizes are weights only: KV cache, activations and audio buffers come on top")
    if b.get("frozen"):
        print(f"# the board is frozen since {b['frozen']}")
    print(f"OK\t{out.as_posix()}")
    return 0


# Follow

def pick(cfg, prefix=""):
    out = {}
    for k, v in cfg.items():
        if isinstance(v, dict) and not prefix:
            out.update(pick(v, f"{k}."))
        elif k in CONFIG_KEYS and not isinstance(v, dict):
            out[prefix + k] = v
    return out


NAME_KEYS = ("files", "base_model", "quantized")  # facts that list names (files, other repos), never a statement


def grep(paths, pat, topic):
    """file:line: text for each line that matches, the text a window of the line around the match."""
    hits = []
    for p in paths:
        key = None
        for n, line in enumerate(p.read_bytes().decode("utf-8", "replace").split("\n"), 1):  # numbered as grep -n does
            if p.suffix == ".json" and line.startswith(' "'):
                key = line[2:].split('"', 1)[0]  # the facts file's top-level key
            if key in NAME_KEYS:
                continue
            if hit := pat.search(line):
                hits.append(f"{p.relative_to(topic).as_posix()}:{n}: {clean(line[max(0, hit.start() - 60):], 160)}")
    return hits


def follow(args, topic):
    if len(args.repos) > FOLLOW:
        raise Usage(f"follow takes at most {FOLLOW} models")
    bad = [r for r in args.repos if not REPO.fullmatch(r)]
    if bad:
        raise Usage(f"not a Hub repo id: {', '.join(bad)}")
    task = args.task
    if not task:
        sl, name = topic / "models" / "shortlist.json", ""
        if sl.is_file():
            try:
                name = json.loads(sl.read_bytes().decode("utf-8")).get("board", "")
            except (OSError, ValueError, AttributeError):
                print("# models/shortlist.json is unreadable: the llm features are used; pass --task")
        task = name if name in ("asr", "tts") else "llm"
    feats, needs = dict(FEATURES[task]), []
    for n in (x.strip() for x in (args.need or "").split(",")):
        key = next((k for k in feats if k.casefold() == n.casefold()), n)  # a need may be one of the task's features
        if n and key not in feats:
            code = LANGS.get(n.casefold())  # a language is also stated as its code in the card's language list
            feats[key] = r"[\s_-]*".join(map(re.escape, n.split())) + (rf'|^\s*-\s*{code}\s*$|"{code}"' if code else "")
        needs += [key] if n else []
    feats = [(n, re.compile(p, re.I)) for n, p in feats.items()]
    code = 0
    for repo in args.repos:
        try:
            f = facts(repo)
            if f is None:
                print(f"FAIL\t{repo}\tnot served by the Hub (a hosted service, or private)")
                code = 1
                continue
            files, gated = [], False
            if f["card"]:
                card = topic / "sources" / f"hf-{repo.replace('/', '--')}-{f['sha'][:7]}.md"
                old = card.read_bytes() if card.is_file() else None
                if not old or len(old) < (f.get("_card_size") or 0):  # missing, empty, or shorter than the Hub says
                    try:
                        body = fetch(f"{HUB}/{repo}/raw/{f['sha']}/README.md")
                        if old is None or body.startswith(old):  # sources are never overwritten, a cut copy is
                            write_atomic(card, body)
                    except Fail as e:
                        if e.code not in (401, 403):
                            raise
                        gated = True  # a gated repo serves its files after its terms are accepted; its page shows the card
                files += [] if gated else [card]
            if f["config_file"]:
                try:
                    f["config"].update(pick(get(f"{HUB}/{repo}/raw/{f['sha']}/config.json")))
                except Fail as e:
                    f["config"]["error"] = str(e)
            f["papers"] = []
            for pid in f["arxiv"][:2]:
                try:
                    p = get(f"{HUB}/api/papers/{pid}")
                except Fail:
                    continue
                gh = str(p.get("githubRepo") or "")
                f["papers"].append({"id": pid, "title": clean(p.get("title") or "", 200),
                                    "abstract": clean(p.get("summary") or "", 3000),  # the authors' own, never ai_summary
                                    "published": (p.get("publishedAt") or "")[:10] or None,
                                    "github": clean(gh, 200) if gh.startswith("https://github.com/") else None})
            f["quantized"] = derivatives(repo)
        except Fail as e:
            print(f"FAIL\t{repo}\t{e}")
            code = 1
            continue
        except (AttributeError, KeyError, TypeError, IndexError) as e:
            print(f"FAIL\t{repo}\t{odd(e, 'Hub')}")
            code = 1
            continue
        path = save_facts(topic, f)
        files.append(path)
        print(f"FACTS\t{repo}\t{files[0].as_posix() if len(files) > 1 else 'card gated' if gated else 'no card'}\t"
              f"{path.as_posix()}")
        if gated:
            print(f"HOP\t{repo}\tcard\tpage {HUB}/{repo}")
        for name, pat in feats:
            hits = grep(files, pat, topic)
            for h in hits[:3 if name in needs else 1] or ["not read: the card is gated" if gated else "not stated"]:
                print(f"FEATURE\t{repo}\t{name}\t{h}")
            if not hits and name in needs:
                for p in f["papers"]:
                    print(f"HOP\t{repo}\t{name}\tpaper https://arxiv.org/abs/{p['id']}")
                    if p["github"]:
                        print(f"HOP\t{repo}\t{name}\trepo {p['github']}")
                if not f["papers"]:
                    print(f"HOP\t{repo}\t{name}\tnone: the card links no paper")
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(description="Model leaderboards, shortlists and model facts for the models mode.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="save one board table to <topic>/sources/board-*.tsv")
    s.add_argument("topic")
    s.add_argument("--board", required=True, help="asr, tts, llm, slm or hub:<org>/<dataset>")
    s.add_argument("--table", help="asr: english, multilingual, longform, private; tts: quality, streaming")
    s.add_argument("--lang", help="tts quality: the board's language, e.g. Korean (default English)")
    s.add_argument("--clone", action="store_true", help="tts quality: the voice cloning results")
    s.add_argument("--hardware", help="tts streaming: A100, CPU or H200 (default A100)")
    s.add_argument("--refresh", action="store_true", help="take another snapshot today")
    s = sub.add_parser("shortlist", help="filter the latest snapshot with Hub facts and mark the front")
    s.add_argument("topic")
    s.add_argument("--board", required=True)
    s.add_argument("--table")
    s.add_argument("--lang", help="asr: a multilingual column; tts: the snapshot's language; else the cards' languages")
    s.add_argument("--clone", action="store_true", help="tts quality: use the voice cloning snapshot")
    s.add_argument("--hardware", help="tts streaming: the snapshot's hardware")
    s.add_argument("--metric", help="the column to rank by (default: the table's first metric)")
    s.add_argument("--max-gb", type=float, help="memory budget for the weights in GB")
    s.add_argument("--license", choices=("permissive", "open", "any"), default="any")
    s.add_argument("--since", help="repo created on or after YYYY-MM-DD")
    s.add_argument("--off-hub", action="store_true", help="let rows with no Hub repo (hosted services) join the front")
    s.add_argument("--top", type=int, default=10, help=f"rows printed, at most {TOP}")
    s = sub.add_parser("follow", help="save cards and facts, grep them for features")
    s.add_argument("topic")
    s.add_argument("repos", nargs="+", metavar="org/name")
    s.add_argument("--need", help="must-have features, comma-separated")
    s.add_argument("--task", choices=tuple(FEATURES), help="feature list (default: from the shortlist's board)")
    args = ap.parse_args(argv)
    topic = Path(args.topic).expanduser()  # a quoted ~ reaches the script unexpanded
    global _end
    _end = time.monotonic() + DEADLINE[args.cmd]
    try:
        terms = egress_terms()
        sent = [args.board if hasattr(args, "board") else "", getattr(args, "lang", None) or ""] + getattr(args, "repos", [])
        for v in sent:
            hit = egress_hit(v, terms)
            if hit:
                print(f"FAIL\tegress\t{clean(v, 80)} contains a term from {hit[1]}")
                return 2
        if args.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since) if args.cmd == "shortlist" else False:
            raise Usage("--since is YYYY-MM-DD")
        return {"snapshot": snapshot, "shortlist": shortlist, "follow": follow}[args.cmd](args, topic)
    except Usage as e:
        print(f"FAIL\tusage\t{e}")
        return 2
    except Drift as e:
        print(f"FAIL\tschema-drift: {args.board} {args.table or ''}\t{clean(e, 300)}".replace(" \t", "\t"))
        return 2
    except Fail as e:
        print(f"FAIL\t{getattr(args, 'board', 'hub')}\t{e}")
        return 1
    except (ValueError, OSError) as e:
        print(f"FAIL\t{getattr(args, 'board', 'hub')}\t{clean(e, 120)}")
        return 1
    except Exception as e:  # a reply of an unexpected shape: a FAIL line, never a traceback
        print(f"FAIL\t{getattr(args, 'board', 'hub')}\t{odd(e, 'board' if args.cmd == 'snapshot' else 'Hub')}")
        return 1
    finally:
        _end = None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
