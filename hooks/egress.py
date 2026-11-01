"""PreToolUse hook: exit 2 (reason on stderr) when a WebSearch or WebFetch input holds a private term.
Any failure also exits 2, so a broken guard never lets a call through silently, and so does a check that runs past
DEADLINE: the hook's timeout would let the call through. egress.sh starts it, only where a term list exists.
Standalone on purpose: it imports nothing from the scripts."""
import json, os, re, sys, threading, unicodedata, urllib.parse
from pathlib import Path

DEADLINE = 6  # seconds for the check once Python runs, under the hook's 10 s timeout with room for a slow start


def egress_terms(cwd=None):
    """(term, source) pairs from ~/.claude/phro-search/forbidden.txt and the nearest .phro/project.json at or above cwd."""
    found = []
    path = Path.home() / ".claude" / "phro-search" / "forbidden.txt"
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


def block(reason):
    print(f"phro-search egress: {reason}", file=sys.stderr)
    sys.exit(2)


def decide(raw):
    """The reason to block the hook event in raw (bytes), or None to let it through."""
    data = json.loads(raw.decode("utf-8"))
    tool = data.get("tool_name")
    if tool not in ("WebSearch", "WebFetch"):
        return None
    terms = egress_terms(data.get("cwd"))
    todo = [data.get("tool_input")]
    while todo:
        x = todo.pop()
        if isinstance(x, dict):
            todo += x.values()
        elif isinstance(x, list):
            todo += x
        elif isinstance(x, str):
            hit = egress_hit(x, terms)
            if hit:
                return (f"blocked {tool}: the input contains '{hit[0]}', listed in {hit[1]}. Rewrite it as a "
                        "generic problem statement without project names, data or code names.")
    return None


def main():
    result = []

    def work():
        try:
            result.append(decide(sys.stdin.buffer.read()))
        except Exception as e:
            result.append(f"cannot check this call ({type(e).__name__}: {e}); if a term list is at fault, fix or remove "
                          "~/.claude/phro-search/forbidden.txt or the nearest .phro/project.json")

    t = threading.Thread(target=work, daemon=True)  # a hung read or a slow disk cannot hold the main thread
    t.start()
    t.join(DEADLINE)
    if not result:
        print(f"phro-search egress: the check did not finish within {DEADLINE} s, so the call is blocked; retry it",
              file=sys.stderr, flush=True)
        os._exit(2)  # the worker may still hold standard input
    if result[0]:
        block(result[0])


if __name__ == "__main__":
    main()
