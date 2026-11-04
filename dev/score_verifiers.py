"""The verifier set (R1, R6 in docs/structure-review.md): how often verifiers refute true claims and let false ones survive.

Usage:
  python -I dev/score_verifiers.py <planted file> <claims.json>

The planted file lists the planted claims, one per line: claim id, truth (true or false), and an optional note
such as the variant (overstated, outdated, contradicted, true), tab- or space-separated. Blank lines, lines
starting with # and a header line (truth in the second column) are skipped. claims.json is the report's, with
the votes the verifiers gave (references/report.md).

A vote is one parsed reply, with refuted true or false; anything else is no vote. The verdict follows the vote
rule of report.md, computed from the votes (a verdict field that disagrees gets a # note): 2 refutations,
refuted; one vote that holds with high or medium confidence, survived; any other single vote or none, unverified;
otherwise survived. A run sends one verifier first on a reviewed source, so on the FALSE line "votes not refuting" is
the chance that a single verifier lets a false claim pass.

Output, tab-separated:
  CLAIM <id> <truth> refuted <r>/<votes> <verdict> <ok|false refutation|false survival|no verdict>
  MISSING <id> not in claims.json
  TRUE <n> claims votes refuting <r>/<v> <pct> verdicts refuted <k>/<n> <pct> unverified <u>
  FALSE <n> claims votes not refuting <r>/<v> <pct> verdicts survived <k>/<n> <pct> unverified <u>
  R6 false refutations of true claims <k>/<n> <pct> of verdicts threshold 10% <crossed|not crossed> <what follows>
R6's switch ("If you are unsure, the claim is refuted" becomes "refuted needs a stated reason from the check list;
could not check is no vote") is judged on verdicts: the share of true claims with a verdict that end refuted, since
a true claim refuted is what the report loses. The vote rates are shown on the TRUE and FALSE lines. It only reads.
"""
import argparse, json, sys
from pathlib import Path

THRESHOLD = 0.10


def read_planted(path):
    """[(id, truth)] in file order; ValueError names a bad line."""
    out = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        parts = line.split("\t") if "\t" in line else line.split()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(parts) < 2 or parts[1].strip().lower() not in ("true", "false"):
            if not out and len(parts) >= 2 and parts[1].strip().lower() == "truth":
                continue  # a header line
            raise ValueError(f"{path}:{n}: want <claim id> <true|false>")
        out.append((parts[0].strip(), parts[1].strip().lower() == "true"))
    return out


def votes(claim):
    """The refuted values of a claim's votes that parsed."""
    return [v["refuted"] for v in claim.get("votes") or [] if isinstance(v, dict) and isinstance(v.get("refuted"), bool)]


def verdict(vs, low=False):
    """low: the claim's single vote, if that is all it has, is low in confidence."""
    if sum(vs) >= 2:
        return "refuted"
    return "survived" if len(vs) >= 2 or (vs == [False] and not low) else "unverified"


def pct(k, n):
    return f"{k}/{n} {100 * k / n:.1f}%" if n else f"{k}/{n}"


def main(argv=None):
    p = argparse.ArgumentParser(prog="score_verifiers.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("planted", help="planted claims: claim id and truth (true or false) per line")
    p.add_argument("claims", help="the claims.json with the verifiers' votes")
    a = p.parse_args(argv)
    try:
        planted = read_planted(Path(a.planted).expanduser())
        data = json.loads(Path(a.claims).expanduser().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        print(f"FAIL\t{getattr(e, 'strerror', None) or e}")
        return 1
    claims = data.get("claims", []) if isinstance(data, dict) else data
    by_id = {c.get("id"): c for c in claims if isinstance(c, dict)}
    tally = {True: [0, 0, 0, 0, 0], False: [0, 0, 0, 0, 0]}  # claims, votes, refuting votes, refuted verdicts, survived verdicts
    unverified = {True: 0, False: 0}
    notes = []
    for cid, truth in planted:
        c = by_id.get(cid)
        if c is None:
            print(f"MISSING\t{cid}\tnot in claims.json")
            continue
        vs = votes(c)
        v = verdict(vs, any(str(x.get("confidence")).lower() == "low" for x in c.get("votes") or [] if isinstance(x, dict)))
        if len(vs) < 3:
            notes.append(f"# {cid}: {len(vs)} of 3 votes")
        if c.get("verdict") and c["verdict"] != v:
            notes.append(f"# {cid}: verdict in claims.json is {c['verdict']}, the votes give {v}")
        t = tally[truth]
        t[0], t[1], t[2] = t[0] + 1, t[1] + len(vs), t[2] + sum(vs)
        t[3] += v == "refuted"
        t[4] += v == "survived"
        unverified[truth] += v == "unverified"
        if v == "unverified":
            mark = "no verdict"
        elif truth:
            mark = "false refutation" if v == "refuted" else "ok"
        else:
            mark = "false survival" if v == "survived" else "ok"
        print("\t".join(["CLAIM", cid, "true" if truth else "false", f"refuted {sum(vs)}/{len(vs)}", v, mark]))
    for note in notes:
        print(note)
    n, nv, r, refuted, _ = tally[True]
    print("\t".join(["TRUE", f"{n} claims", "votes refuting " + pct(r, nv), "verdicts refuted " + pct(refuted, n),
                     f"unverified {unverified[True]}"]))
    n, nv, r, _, survived = tally[False]
    print("\t".join(["FALSE", f"{n} claims", "votes not refuting " + pct(nv - r, nv), "verdicts survived " + pct(survived, n),
                     f"unverified {unverified[False]}"]))
    n, _, _, refuted, _ = tally[True]
    judged = n - unverified[True]
    if not judged:
        print("R6\tno verdicts on true claims\tthreshold 10%\t-\tno decision")
        return 0
    tail = (["crossed", "switch to: refuted needs a stated reason from the check list; could not check is no vote"]
            if refuted / judged > THRESHOLD else ["not crossed", "keep the vote rule"])
    print("\t".join(["R6", f"false refutations of true claims {pct(refuted, judged)} of verdicts", "threshold 10%"] + tail))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
