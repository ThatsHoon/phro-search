# Style

Output rules for the prose written for the user: chat answers, briefs, and the prose of a written report. Quotes are not prose: the evidence pages (`report.html`, `evidence-<stem>.html`), the quotes in `extracts.json` and `extracts-<stem>.json`, and `sources/` stay verbatim, are never checked, and are never cut or edited to pass a check. Read the rules before writing. `check.py` enforces most of them and prints the line and the phrase of each problem.

## Voice

- Write in the user's language. Quotes stay verbatim in their original language and go in blockquotes, with their source.
- Use plain declarative sentences that say who did what: the actor, the action, the object.
- Prefer a name or a number to a vague word: "the cache cut the median latency from 420 ms to 180 ms", not "performance improved significantly".
- Write numbers with their unit (4 s, 6.1 percent, 8 GB) and dates in full with the year (2026-10-30), never "recently" or "last week".
- No stock openers, signposts or closers. Do not announce what comes next (`let's dive in`, `as follows`), do not restate a paragraph at its end (`in conclusion`, `in summary`), and do not offer more help (`hope this helps`, `let me know if`).
- No hype words: `revolutionary`, `groundbreaking`, `game-changer`, `cutting-edge`, and their equivalents in the user's language.
- No translationese filler: English constructions carried into the user's language as stiff stand-ins for a plain verb or particle ("through X", "regarding X", "in terms of X", "by doing X"), and double passives.
- Do not pile up empty modifiers ("various", "effective", "efficient", "powerful", "plays an important role"). One is natural; the check fails when they cluster.
- Vary how sentences open. A connective such as "also", "in particular", "therefore" or "that is" may start at most 3 sentences per document each.
- Keep to one rhetorical question, one lead-in sentence ("the following ...") and two arrows per document.

## Marks

- No emoji and no decorative symbols (check marks, stars, geometric shapes, dingbats).
- No em dash (U+2014), en dash (U+2013) or horizontal bar (U+2015). Use a comma, a colon or parentheses. Write ranges with "to" or a tilde.
- No invisible characters: zero-width space, zero-width joiner and non-joiner, word joiner, byte-order mark, soft hyphen, and the no-break spaces U+00A0 and U+202F. They arrive with pasted web text, so retype pasted lines outside quotes; a quote keeps a no-break space or soft hyphen of its source.
- Bold sparingly: at most 3 bold spans per document, plus 1 per 1,500 characters of body text.
- No AI attribution anywhere: no `Generated with ...`, no `Co-Authored-By`, no "written by" a model, no `as an AI`, and no copied machine-summary fields.

## Check

`check.py` prints each problem as `<line>:<rule>: <detail>`. A count over its limit prints a line 0 summary, then each hit with its line. Rewrite only the flagged spots, then run it again until it prints `OK`. Quote lines, fenced code, inline code and URLs are not checked, except for invisible characters.
