"""Token use of one Claude Code session, split by who spent it: the main session and each subagent type.

Usage:
  python -I dev/agent_cost.py <session.jsonl> [<session.jsonl> ...]

A session transcript lives in ~/.claude/projects/<project>/<session id>.jsonl; its subagents' transcripts
are in the folder beside it, <session id>/subagents/agent-*.jsonl, each with a .meta.json naming its type.
For each session it prints, tab-separated, one line per (who, model):
  USE <who> <model> <calls> input <n> cache-write <n> cache-read <n> output <n> share <percent of output>
then a TOTAL line. "who" is "main" or the subagent type (for example phro-search:web-gatherer). The share
is of output tokens, the most expensive kind; prices differ by model, so compare like with like. Run it on
the transcripts of acceptance runs to see what share of a run the searchers take (R4 in
docs/structure-review.md). It only reads.
"""
import json, sys
from collections import defaultdict
from pathlib import Path

KINDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def usage(path):
    """{model: [calls, input, cache write, cache read, output]} of one transcript; each API reply counts once."""
    out, seen = defaultdict(lambda: [0, 0, 0, 0, 0]), set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        m = e.get("message") if isinstance(e, dict) else None
        if not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
            continue
        key = e.get("requestId") or m.get("id") or e.get("uuid")
        if key in seen:  # one reply is written as several lines, one per content block
            continue
        seen.add(key)
        row = out[m.get("model") or "unknown"]
        row[0] += 1
        for i, k in enumerate(KINDS, 1):
            row[i] += int(m["usage"].get(k) or 0)
    return out


def who(agent_jsonl):
    """The subagent type from the .meta.json beside a subagent transcript."""
    meta = agent_jsonl.with_name(agent_jsonl.stem + ".meta.json")
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("agentType") or "subagent"
    except (OSError, ValueError):
        return "subagent"


def session(path):
    """{(who, model): totals} for one session and its subagents."""
    rows = defaultdict(lambda: [0, 0, 0, 0, 0])
    parts = [("main", path)] + [(who(p), p) for p in sorted((path.with_suffix("") / "subagents").rglob("agent-*.jsonl"))]
    for name, p in parts:
        for model, t in usage(p).items():
            rows[(name, model)] = [a + b for a, b in zip(rows[(name, model)], t)]
    return rows


def main(argv):
    if not argv:
        sys.exit(__doc__)
    for arg in argv:
        rows = session(Path(arg).expanduser())
        out = sum(t[4] for t in rows.values()) or 1
        print(f"SESSION\t{Path(arg).name}")
        for (name, model), t in sorted(rows.items(), key=lambda kv: -kv[1][4]):
            print(f"USE\t{name}\t{model}\t{t[0]}\tinput\t{t[1]}\tcache-write\t{t[2]}\tcache-read\t{t[3]}\toutput\t{t[4]}"
                  f"\tshare\t{100 * t[4] / out:.1f}%")
        total = [sum(t[i] for t in rows.values()) for i in range(5)]
        print(f"TOTAL\t{total[0]} calls\tinput\t{total[1]}\tcache-write\t{total[2]}\tcache-read\t{total[3]}\toutput\t{total[4]}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
