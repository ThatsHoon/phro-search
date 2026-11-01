"""The routing set (R1 in docs/structure-review.md): does the skill fire, with the right mode, and stay quiet on near misses?

Usage:
  python -I dev/routing.py [--prompts FILE] [--runs N] [--kind in|near|out] [--ids ID,ID] [--dry-run]
                           [--plugin-dir DIR | --installed] [--model NAME] [--tools LIST] [--budget USD] [--cap USD]
                           [--timeout S] [--cwd DIR] [--out DIR] [--skill NAME]
  python -I dev/routing.py --from DIR [--prompts FILE] [--runs N] [--kind ...] [--ids ...]

Each prompt of evals/routing/prompts.tsv (id, kind, expect, lang, prompt, note; kind in, near or out; expect a mode,
or none) runs N times (default 3) headless with the installed claude CLI:
  claude -p --output-format stream-json --verbose --tools Skill,Read,Glob,Grep --allowedTools Skill,Read,Glob,Grep
         --max-budget-usd 1 --plugin-dir <repo>
with the prompt on standard input, in a fresh empty folder (or --cwd). Read-only tools and no web, as T5.1 ran;
your user skills load as usual, so the competing skills are present. Every run's stream is saved to
--out (default evals/routing/runs/<stamp>/<id>-<n>.jsonl), and --from re-grades a saved folder without running.

From the stream: the skill fired when a Skill tool call names --skill (default phro-search:search); its mode is
the first references/<mode>.md it read, else the mode of a "PLAN: <mode>;" line it wrote; a run that fired with
neither is "search?" (check it by hand). A Skill call naming another skill is other:<name>.

Output, tab-separated:
  RUN <id> <n> <dig|...|search?|none|other:<skill>|error:<why>> <cost USD>
  PROMPT <id> <kind> <expect> fired <k>/<n> [right <m>/<n>] <PASS|FAIL> [<other skills>]
The verdicts follow R1's thresholds on firing: 90 percent or more of the runs of in-scope prompts, 10 percent or
less of near misses and out-of-scope prompts. Right mode is shown beside firing; T5.1 counted it.
  IN fired <k>/<n> <pct> right mode <m>/<n> <pct> threshold 90% <PASS|FAIL>
  NEAR fired <k>/<n> <pct> threshold 10% <PASS|FAIL>        (near misses)
  OUT fired <k>/<n> <pct> threshold 10% <PASS|FAIL>         (out of scope)
  ROUTING <PASS|FAIL|INCOMPLETE <k> runs failed>
  COST <USD> <n> runs
Failed runs (timeout, no result event) count in no rate and make the verdict INCOMPLETE. No new run starts once
the runs so far cost --cap (default 50 USD, R1's cap per eval pass). --dry-run lists the commands (CMD <id> <n>
<command> stdin <prompt>) and runs nothing. Exit 0 on PASS, 1 otherwise, 2 on a bad prompt file.
"""
import argparse, csv, datetime, json, os, re, shlex, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ("dig", "report", "pulse", "docs", "models", "watch")
KINDS = ("in", "near", "out")
COLUMNS = ["id", "kind", "expect", "lang", "prompt", "note"]
TOOLS = "Skill,Read,Glob,Grep"
REF = re.compile(r"skills[\\/]+search[\\/]+references[\\/]+(" + "|".join(MODES) + r")\.md$")
PLAN = re.compile(r"(?m)^\s*PLAN: *(" + "|".join(MODES) + r")\s*;")
IN_MIN, QUIET_MAX = 0.9, 0.1


def load_prompts(path):
    """Rows of a prompt file as dicts; ValueError names the first bad row."""
    with Path(path).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows or list(rows[0]) != COLUMNS:
        raise ValueError(f"{path}: the header must be {' '.join(COLUMNS)}")
    seen = set()
    for n, r in enumerate(rows, 2):
        bad = (not r["id"] or r["id"] in seen or r["kind"] not in KINDS or not r["prompt"]
               or (r["kind"] == "in") != (r["expect"] in MODES) or (r["kind"] != "in" and r["expect"] != "none"))
        if bad:
            raise ValueError(f"{path}:{n}: bad row (unique id; kind in, near or out; expect a mode for in, none otherwise)")
        seen.add(r["id"])
    return rows


def _name(inp):
    """The skill a Skill tool input names, without a leading slash."""
    for key in ("skill", "command", "name"):
        if isinstance(inp.get(key), str):
            return inp[key].strip().lstrip("/").split()[0] if inp[key].strip() else ""
    return ""


def parse_stream(lines, skill="phro-search:search"):
    """What one stream-json run shows: fired, mode, via (read or plan), others, cost, error, listed."""
    got = {"fired": False, "mode": None, "via": None, "others": [], "cost": None, "error": "no result event", "listed": None}
    plan = None
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        kind = e.get("type")
        if kind == "system" and e.get("subtype") == "init":
            names = [x if isinstance(x, str) else x.get("name", "") for x in (e.get("skills") or []) + (e.get("slash_commands") or [])]
            got["listed"] = skill in names
        elif kind == "assistant":
            content = (e.get("message") or {}).get("content") or []
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and plan is None and (m := PLAN.search(block.get("text") or "")):
                    plan = m.group(1)
                if block.get("type") != "tool_use":
                    continue
                inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                if block.get("name") == "Skill":
                    name = _name(inp)
                    if name == skill:
                        got["fired"] = True
                    elif name and name not in got["others"]:
                        got["others"].append(name)
                elif block.get("name") == "Read" and got["fired"] and got["mode"] is None:
                    if m := REF.search(str(inp.get("file_path") or "")):
                        got["mode"], got["via"] = m.group(1), "read"
        elif kind == "result":
            got["cost"] = float(e.get("total_cost_usd") or 0)
            got["error"] = (e.get("subtype") or "error") if e.get("is_error") else None
            if plan is None and (m := PLAN.search(str(e.get("result") or ""))):
                plan = m.group(1)
    if got["fired"] and got["mode"] is None and plan:
        got["mode"], got["via"] = plan, "plan"
    return got


def outcome(got):
    """One word for a run: the mode, search? (fired, mode unknown), none, other:<skill> or error:<why>."""
    if got["error"]:
        return "error:" + got["error"]
    if got["fired"]:
        return got["mode"] or "search?"
    return "other:" + got["others"][0] if got["others"] else "none"


def command(a):
    """The claude command of one run (the prompt goes to standard input)."""
    cmd = [a.claude, "-p", "--output-format", "stream-json", "--verbose", "--tools", a.tools, "--allowedTools", a.tools,
           "--max-budget-usd", str(a.budget), "--no-session-persistence"]
    if not a.installed:
        cmd += ["--plugin-dir", str(Path(a.plugin_dir).expanduser())]
    if a.model:
        cmd += ["--model", a.model]
    return cmd


def run_once(a, cmd, prompt):
    """(stream lines, error) of one headless run."""
    work = Path(a.cwd).expanduser() if a.cwd else Path(tempfile.mkdtemp(prefix="routing-"))
    try:
        r = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, cwd=work, timeout=a.timeout)
        return r.stdout.decode("utf-8", errors="replace").splitlines(), None
    except subprocess.TimeoutExpired as e:
        return (e.stdout or b"").decode("utf-8", errors="replace").splitlines(), "timeout"
    except OSError as e:
        return [], f"cannot start claude: {e.strerror or e}"
    finally:
        if not a.cwd:
            shutil.rmtree(work, ignore_errors=True)


def pct(k, n):
    return f"{k}/{n} {100 * k / n:.1f}%" if n else f"{k}/{n}"


def verdict(k, n, ok):
    return "-" if not n else ("PASS" if ok(k / n) else "FAIL")


def main(argv=None):
    p = argparse.ArgumentParser(prog="routing.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prompts", default=str(ROOT / "evals/routing/prompts.tsv"), help="prompt file (default the routing set)")
    p.add_argument("--runs", type=int, default=3, help="runs per prompt (default 3)")
    p.add_argument("--kind", choices=KINDS, help="only prompts of this kind")
    p.add_argument("--ids", help="only these prompt ids, comma-separated")
    p.add_argument("--dry-run", action="store_true", help="list the commands and run nothing")
    p.add_argument("--from", dest="saved", metavar="DIR", help="grade the streams saved in DIR instead of running")
    p.add_argument("--plugin-dir", default=str(ROOT), help="plugin folder to load (default this repo)")
    p.add_argument("--installed", action="store_true", help="use the installed plugin, no --plugin-dir")
    p.add_argument("--model", help="model for the runs (default the CLI's)")
    p.add_argument("--tools", default=TOOLS, help=f"tools offered and allowed (default {TOOLS})")
    p.add_argument("--budget", type=float, default=1.0, help="claude --max-budget-usd per run (default 1)")
    p.add_argument("--cap", type=float, default=50.0, help="start no run once the runs cost this many USD (default 50)")
    p.add_argument("--timeout", type=int, default=300, help="seconds per run (default 300)")
    p.add_argument("--cwd", help="folder the runs work in (default a fresh empty one per run)")
    p.add_argument("--out", help="folder for the saved streams (default evals/routing/runs/<stamp>)")
    p.add_argument("--skill", default="phro-search:search", help="the skill that should fire (default phro-search:search)")
    p.add_argument("--claude", default=shutil.which("claude") or "claude", help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    try:
        rows = load_prompts(Path(a.prompts).expanduser())
    except (OSError, ValueError, KeyError) as e:
        print(f"FAIL\t{e}")
        return 2
    if a.kind:
        rows = [r for r in rows if r["kind"] == a.kind]
    if a.ids:
        want = set(a.ids.split(","))
        rows = [r for r in rows if r["id"] in want]
    order = [(r, n) for n in range(1, a.runs + 1) for r in rows]  # round robin: every prompt once before any twice
    cmd = command(a)
    if a.dry_run:
        join = subprocess.list2cmdline if os.name == "nt" else shlex.join
        for r, n in sorted(order, key=lambda x: (rows.index(x[0]), x[1])):
            print("\t".join(["CMD", r["id"], str(n), join(cmd), "stdin", r["prompt"]]))
        return 0
    out = None
    if not a.saved:
        out = Path(a.out).expanduser() if a.out else ROOT / "evals/routing/runs" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out.mkdir(parents=True, exist_ok=True)
    results, total = {}, 0.0
    for r, n in order:
        if a.saved:
            f = Path(a.saved).expanduser() / f"{r['id']}-{n}.jsonl"
            lines, err = (f.read_text(encoding="utf-8", errors="replace").splitlines(), None) if f.is_file() else ([], "no stream")
        elif total >= a.cap:
            lines, err = [], "cost cap"
        else:
            lines, err = run_once(a, cmd, r["prompt"])
            (out / f"{r['id']}-{n}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        got = parse_stream(lines, a.skill)
        if err:
            got["error"] = err
        total += got["cost"] or 0
        results.setdefault(r["id"], []).append((n, got))
    tally = {k: [0, 0, 0] for k in KINDS}  # fired, graded, right
    failed = 0
    for r in rows:
        k, graded, right, others = 0, 0, 0, []
        for n, got in sorted(results.get(r["id"], []), key=lambda x: x[0]):
            word = outcome(got)
            print("\t".join(["RUN", r["id"], str(n), word, "-" if got["cost"] is None else f"{got['cost']:.4f}"]))
            if got["error"]:
                failed += 1
                continue
            graded += 1
            k += got["fired"]
            right += got["fired"] and got["mode"] == r["expect"]
            others += [o for o in got["others"] if o not in others]
        t = tally[r["kind"]]
        t[0], t[1], t[2] = t[0] + k, t[1] + graded, t[2] + right
        if r["kind"] == "in":
            line = ["PROMPT", r["id"], r["kind"], r["expect"], f"fired {k}/{graded}", f"right {right}/{graded}",
                    verdict(k, graded, lambda x: x >= IN_MIN)]
        else:
            line = ["PROMPT", r["id"], r["kind"], r["expect"], f"fired {k}/{graded}", verdict(k, graded, lambda x: x <= QUIET_MAX)]
        print("\t".join(line + ([",".join(others)] if others else [])))
    k, n, right = tally["in"]
    checks = [verdict(k, n, lambda x: x >= IN_MIN)]
    print("\t".join(["IN", "fired " + pct(k, n), "right mode " + pct(right, n), "threshold 90%", checks[0]]))
    for kind in ("near", "out"):
        k, n, _ = tally[kind]
        checks.append(verdict(k, n, lambda x: x <= QUIET_MAX))
        print("\t".join([kind.upper(), "fired " + pct(k, n), "threshold 10%", checks[-1]]))
    if failed:
        print(f"ROUTING\tINCOMPLETE\t{failed} runs failed")
    else:
        print("ROUTING\t" + ("FAIL" if "FAIL" in checks or set(checks) == {"-"} else "PASS"))
    print(f"COST\t{total:.4f} USD\t{sum(len(v) for v in results.values())} runs")
    return 0 if not failed and "FAIL" not in checks and set(checks) != {"-"} else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
