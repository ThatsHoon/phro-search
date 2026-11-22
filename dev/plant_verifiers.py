"""The planted verifier set (R1, R6 in docs/structure-review.md): build the verifier briefs for planted claims, then
collect the replies into a claims.json that dev/score_verifiers.py grades.

Usage:
  python -I dev/plant_verifiers.py build <spec.json> <research root> <run folder> [--votes N]
  python -I dev/plant_verifiers.py run <run folder> [--workers N] [--budget USD] [--cap USD] [--plugin-dir DIR | --installed]
  python -I dev/plant_verifiers.py collect <run folder>

The spec is a JSON list. Each item plants one central claim of a delivered report:
  {"id": "p01", "topic": "<topic folder>", "claim": "<its claims.json id>", "truth": true, "variant": "true"}
A false item also carries "claim_text" (the planted wording) and may carry "replace", a list of [old, new] pairs
applied to the quote and to the context paragraph (a quote the source does not hold). Variants: true, overstated
(the wording says more than the real quote), altered (a number or a word changed in claim, quote and context).

build takes each claim's quote, URL, label, standing and venue from <research root>/<topic>/claims.json and the
paragraph around its first located quote from the topic's newest extracts-*.json and sources/. It fills the verifier
brief exactly as skills/search/references/report.md words it today, so a change to that brief is what the next run
measures. It writes <run>/claims.json, <run>/planted.tsv and one brief per vote, <run>/briefs/<id>-<n>.txt, with
the starting points of the claim's standing in report.md's order. --votes is 1 to 3 (default 2).

run sends each brief that has no saved reply to a headless verifier, --workers at a time (default 6):
  claude -p --agent phro-search:verifier --output-format json --max-budget-usd <budget> --plugin-dir <repo>
with the brief on standard input, and saves the reply, as it came, to <run>/votes/<id>-<n>.json. --budget caps one
verifier (default 1 USD) and --cap the whole pass (default 50): no verifier starts past it. --installed tests the
installed plugin instead of this repo. It prints one RAN line per brief with its cost and the total.
collect writes the replies that parse as the vote object into <run>/claims.json, each dated today, and prints
  VOTE <id>-<n> <refuted|held|no vote>
  COLLECTED <votes> votes on <claims> claims, <missing> missing
A reply that is missing, not that JSON object, or without a true or false refuted is no vote, as in report.md.
"""
import argparse, concurrent.futures, datetime, json, re, shutil, subprocess, sys, threading
from pathlib import Path

REPORT_MD = Path(__file__).resolve().parents[1] / "skills" / "search" / "references" / "report.md"
STARTS = {"reviewed": ["what is withheld", "counter-evidence", "benchmark and marketing"]}
OPEN_STARTS = ["results", "counter-evidence", "benchmark and marketing"]


def brief_parts(text):
    """(template, {standing: check}) from report.md."""
    m = re.search(r"```\n(You are a verifier\..*?)\n```", text, re.S)
    opened = re.search(r'^The check for `open-post` and `unknown`: "(.*)"$', text, re.M)
    reviewed = re.search(r'^The check for `reviewed`: "(.*)"$', text, re.M)
    if not (m and opened and reviewed):
        raise ValueError("report.md: the verifier brief or a standing's check was not found")
    return m.group(1), {"reviewed": reviewed.group(1), "open": opened.group(1)}


def paragraph(lines, line, end):
    """The contiguous non-blank lines around lines line..end (1-based), at most 40."""
    lo, hi = line - 1, (end or line) - 1
    while lo > 0 and lines[lo - 1].strip() and hi - lo < 39:
        lo -= 1
    while hi + 1 < len(lines) and lines[hi + 1].strip() and hi - lo < 39:
        hi += 1
    return "\n".join(lines[lo:hi + 1])


def context(topic, cid, quote):
    """The paragraph around the claim's first located quote in the newest view that has it, else the quote."""
    for view in sorted(topic.glob("extracts-*.json"), reverse=True):
        data = json.loads(view.read_text(encoding="utf-8-sig"))
        for c in data.get("claims", []):
            if c.get("id") != cid:
                continue
            for q in c.get("quotes") or []:
                src = topic / "sources" / str(q.get("file"))
                if src.is_file() and isinstance(q.get("line"), int):
                    lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
                    if 0 < q["line"] <= len(lines):
                        return paragraph(lines, q["line"], q.get("end"))
    return quote


def question(topic):
    m = re.search(r"^Object:\s*(.+)$", (topic / "map.md").read_text(encoding="utf-8-sig"), re.M) if (topic / "map.md").is_file() else None
    return m.group(1).strip() if m else topic.name


def fill(template, checks, claim, ctx, start, q):
    standing = claim.get("standing") or "unknown"
    out = template
    for old, new in [("<its claims.json text, copied exactly>", claim["claim"]), ('"<quote>" from <URL> (<label>)',
                     f'"{claim["quote"]}" from {claim.get("url", "")} ({claim.get("label", "")})'),
                     ("<standing>, <venue>", f'{standing}, {claim.get("venue") or "-"}'),
                     ("<the located paragraph, from its first line to its last>", ctx), ("<the row's starting point>", start),
                     ("<Q>", q), ("<the standing's check, below>", checks["reviewed" if standing == "reviewed" else "open"])]:
        if old not in out:
            raise ValueError(f"report.md: the verifier brief has no slot {old}")
        out = out.replace(old, new)
    return out


def build(a):
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8-sig"))
    template, checks = brief_parts(REPORT_MD.read_text(encoding="utf-8"))
    run = Path(a.run)
    (run / "briefs").mkdir(parents=True, exist_ok=True)
    (run / "votes").mkdir(exist_ok=True)
    claims, planted = [], ["id\ttruth\tvariant"]
    for item in spec:
        topic = Path(a.root).expanduser() / item["topic"]
        src = {c.get("id"): c for c in json.loads((topic / "claims.json").read_text(encoding="utf-8-sig"))}.get(item["claim"])
        if src is None:
            raise ValueError(f'{item["id"]}: {item["topic"]} has no claim {item["claim"]}')
        claim = {k: src.get(k) for k in ("quote", "url", "label", "standing", "venue")}
        claim.update(id=item["id"], claim=item.get("claim_text") or src["claim"], importance="central", votes=[])
        ctx = context(topic, item["claim"], claim["quote"])
        for old, new in item.get("replace") or []:
            if old not in claim["quote"] and old not in ctx:
                raise ValueError(f'{item["id"]}: "{old}" is in neither the quote nor the context')
            claim["quote"], ctx = claim["quote"].replace(old, new), ctx.replace(old, new)
        starts = STARTS.get(claim.get("standing"), OPEN_STARTS)
        for n in range(a.votes):
            (run / "briefs" / f'{item["id"]}-{n + 1}.txt').write_text(
                fill(template, checks, claim, ctx, starts[n], question(topic)), encoding="utf-8", newline="\n")
        claims.append(claim)
        planted.append(f'{item["id"]}\t{"true" if item["truth"] else "false"}\t{item.get("variant", "")}')
    (run / "claims.json").write_text(json.dumps(claims, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    (run / "planted.tsv").write_text("\n".join(planted) + "\n", encoding="utf-8", newline="\n")
    print(f"BUILT\t{len(claims)} claims\t{len(claims) * a.votes} briefs\t{run}")
    return 0


def run(a):
    folder = Path(a.run)
    todo = [b for b in sorted((folder / "briefs").glob("*.txt")) if not (folder / "votes" / (b.stem + ".json")).is_file()]
    cmd = [a.claude, "-p", "--agent", "phro-search:verifier", "--output-format", "json", "--max-budget-usd", str(a.budget)]
    if not a.installed:
        cmd += ["--plugin-dir", str(Path(a.plugin_dir).expanduser())]
    spent, lock = [0.0], threading.Lock()

    def one(brief):
        with lock:
            if spent[0] >= a.cap:
                return brief.stem, None, "not started: cap reached"
        try:
            done = subprocess.run(cmd, input=brief.read_text(encoding="utf-8"), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=a.timeout)
            out = json.loads(done.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            return brief.stem, None, f"failed: {type(e).__name__}"
        if out.get("is_error") or not out.get("result"):
            return brief.stem, None, f"failed: {str(out.get('result') or 'empty reply')[:80]}"
        cost = float(out.get("total_cost_usd") or 0)
        with lock:
            spent[0] += cost
        (folder / "votes" / (brief.stem + ".json")).write_text(str(out.get("result") or ""), encoding="utf-8", newline=chr(10))
        return brief.stem, cost, "ok"

    with concurrent.futures.ThreadPoolExecutor(a.workers) as pool:
        for stem, cost, status in pool.map(one, todo):
            print(f"RAN\t{stem}\t{'-' if cost is None else f'{cost:.2f}'}\t{status}", flush=True)
    print(f"TOTAL\t{len(todo)} briefs\t{spent[0]:.2f} USD")
    return 0


def parse_vote(text):
    """The vote object in a reply, or None."""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    return v if isinstance(v, dict) and isinstance(v.get("refuted"), bool) else None


def collect(a):
    run = Path(a.run)
    claims = json.loads((run / "claims.json").read_text(encoding="utf-8"))
    today, total, missing = datetime.date.today().isoformat(), 0, 0
    for c in claims:
        c["votes"] = []
        for brief in sorted((run / "briefs").glob(f'{c["id"]}-*.txt')):
            reply = run / "votes" / (brief.stem + ".json")
            v = parse_vote(reply.read_text(encoding="utf-8-sig", errors="replace")) if reply.is_file() else None
            if v is None:
                missing += 1
                print(f"VOTE\t{brief.stem}\tno vote")
                continue
            c["votes"].append({**v, "checked": today})
            total += 1
            print(f'VOTE\t{brief.stem}\t{"refuted" if v["refuted"] else "held"}')
    (run / "claims.json").write_text(json.dumps(claims, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"COLLECTED\t{total} votes on {len(claims)} claims, {missing} missing")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="plant_verifiers.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the briefs, claims.json and planted.tsv of a run")
    b.add_argument("spec")
    b.add_argument("root")
    b.add_argument("run")
    b.add_argument("--votes", type=int, choices=(1, 2, 3), default=2)
    r = sub.add_parser("run", help="send the briefs without a saved reply to headless verifiers")
    r.add_argument("run")
    r.add_argument("--workers", type=int, default=6)
    r.add_argument("--budget", type=float, default=1.0, help="USD cap of one verifier")
    r.add_argument("--cap", type=float, default=50.0, help="USD cap of the pass")
    r.add_argument("--timeout", type=int, default=900, help="seconds per verifier")
    r.add_argument("--plugin-dir", default=str(REPORT_MD.parents[3]), help="plugin folder to load (default this repo)")
    r.add_argument("--installed", action="store_true", help="use the installed plugin, no --plugin-dir")
    r.add_argument("--claude", default=shutil.which("claude") or "claude", help=argparse.SUPPRESS)
    c = sub.add_parser("collect", help="write the saved replies into the run's claims.json")
    c.add_argument("run")
    a = p.parse_args(argv)
    try:
        return {"build": build, "run": run, "collect": collect}[a.cmd](a)
    except (OSError, ValueError, KeyError) as e:
        print(f"FAIL\t{getattr(e, 'strerror', None) or e}")
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
