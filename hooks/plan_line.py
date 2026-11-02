"""PreToolUse check for Agent, WebSearch and WebFetch: once a run of the search skill has loaded its mode reference, the
plan line (SKILL.md, Routing step 4) must be in the transcript before the call goes out. Exit 2 blocks and tells the
model why; anything unreadable lets the call through, since this guards a habit and not a boundary. The probe comes
before the mode reference, so it passes. A Bash call to a script is not seen: R17 keeps hooks off Bash. A message's text
can reach the transcript just after its tool calls go out, so a miss is read again for about 2 s before it blocks."""
import json, re, sys, time

MODE_REFERENCE = re.compile(r"[\\/]references[\\/](dig|report|pulse|docs|models|watch)\.md$")
PLAN = re.compile(r"^PLAN: ", re.M)


def owed(lines):
    """True when the latest run of the skill has read a mode reference and sent no plan line since."""
    running = loaded = planned = False
    for line in lines:
        started = "<command-name>/phro-search:search<" in line
        try:
            blocks = json.loads(line)["message"]["content"]
        except (ValueError, KeyError, TypeError):
            blocks = []
        for b in blocks if isinstance(blocks, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                planned = planned or bool(PLAN.search(b.get("text") or ""))
            elif b.get("type") == "tool_use" and b.get("name") == "Skill":
                started = started or (b.get("input") or {}).get("skill") == "phro-search:search"
            elif b.get("type") == "tool_use" and b.get("name") == "Read":
                loaded = loaded or bool(MODE_REFERENCE.search(str((b.get("input") or {}).get("file_path"))))
        if started:
            running, loaded, planned = True, False, False
    return running and loaded and not planned


def main():
    try:
        path = json.load(sys.stdin)["transcript_path"]
        for _ in range(10):
            with open(path, encoding="utf-8", errors="replace") as f:
                if not owed(f):
                    return 0
            time.sleep(.2)
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    print("phro-search: no plan line yet, so retrying is blocked too. Start your next message with "
          "PLAN: <mode>; <rounds, agents or steps>; ceiling <n> <calls>, with a harmless read such as the topic's map.md "
          "if nothing else is due, and repeat this call in the message after it.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
