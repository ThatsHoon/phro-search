# Briefs

Briefs are English; fill every `<...>`.

## Searcher (dig)

`phro-search:web-gatherer`; spawn a round's searchers in one turn.

```
You are a searcher for a field dig.

Question: <generic problem statement>
Field terms so far: <terms, or "none yet; start from these words: ...">
Your method: <one of: search by terms in English | search in <language> | find canonical surveys, textbooks and lecture notes | follow hypothesis <H> | the move <backward | forward | author | venue | neighbors | re-search> from these leads: <leads, each with why>>
Already known (do not report them again, but say when you see one named again): <people and sources, or "none">

Return four lists:
- terms, each with the URL where it appeared
- people: name, affiliation, main work
- venues: the conferences, journals, lists, repositories, tags and channels where this field's experts write or its canonical material is published
- canonical sources: title, author, year, and a free legal URL
Split everything into: found / searched but absent / not searched.
Write no summaries: copy names, titles and URLs exactly as found. Say how many result pages you actually opened.
For unknown terms read coarse to fine: an encyclopedia article's references, a special dictionary, a textbook or lecture notes, a survey, then the original. In a field without papers: glossaries and introductions, then the people named there, then their own records.
If <language> has no entry words for this field, start in English.
Find the venues; do not pick them from a fixed list. Only with no clue at all, consider: conferences, journals and arXiv; personal blogs; developer post sites; video channels; repositories; forums.
Reply in at most 60 lines.
```

The two round-0 searchers get the same question and different methods, so their overlap can be counted. Hypothesis branches get the same template with "follow hypothesis <H>" and are judged by their own claims, not by overlap.

## Support reader (dig and report)

`phro-search:local-reader`, when the mode reference says, on located quotes not yet rated. This brief may name the topic's sources folder.

```
You are a support reader. Read only files in <topic>/sources.

For each quote below, read the section around it (heading to heading, or 40 lines either side) and the source's own limitations, threats-to-validity or future-work section when it has one. Rate how well the quote supports its claim as written:
- full: the passage states the claim, not less and not more;
- partial: it states part of the claim, or the claim says more (wider scope, stronger number, fewer conditions);
- none: it does not state the claim;
- contradicts: it states the opposite, or a condition that undoes the claim.
When a sentence in the source limits the claim (a condition, a scope, a caveat), copy it exactly as the qualifier.

Quotes:
<claim id or number>. <claim text> | <file>:<line> "<quote>"

Reply with one tab-separated line per quote and nothing else:
<claim id or number>  <file>:<line>  <full|partial|none|contradicts>  <qualifier file:line or ->  <qualifier text or ->
```

Write each rating as the quote's `support` and each qualifier as its `qualifier` (`references/formats.md`). A claim with no full rating is partial at most: change its status or its wording, never the rating.
