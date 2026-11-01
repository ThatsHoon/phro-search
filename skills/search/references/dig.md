# dig

Catch up on a field, from generic words down to its original sources. Two things carry the mode: originals are archived, never summarized, and the stop is set by evidence, not by confidence. Sources for each rule: `references/theory.md`.

- No summaries: detailed notes taken while still exploring, before a focus forms, may bring premature closure (Kuhlthau 1991). An agent's summary closes on the agent's view and drops the details the user judges by. The user reads the originals; the agent points at them.
- Branch instead of committing: picking one direction early makes later searches reinforce it. With two plausible directions, branch and compare (Zhou et al. 2026).
- Chain when words fail: following references and citations avoids having to describe the subject (Bates 1989).

## Before round 0

- The confirmed brief heads `map.md` with 3 to 6 required claims (`references/intake.md`, section 7). The question may change while digging: rewrite the claims, log the reason, count it as drift.
- Plan line: "dig: up to 4 rounds, 2 searchers per round on a light model, at most 8 searcher calls".

## Round 0: map

- Spawn 2 searchers with different methods in one turn (brief: `references/briefs.md`). Default split: English and the user's language. When one language covers the field: term search, and canonical surveys and textbooks.
- Two different methods naming the same items is the sign the map is filling up: the overlap idea of capture-recapture, used here as a heuristic, not a tested stopping rule.
- Wait for both. Add their terms, people, venues and sources to `map.md`, each line ending in (unverified); move their "not searched" items to Next leads. Log per searcher what was asked, what came back, and how many pages it opened. Searcher reports usually rest on result snippets: affiliations, "published" and numbers are often wrong until read in the original.
- Venues are found, not taken from a list: the brief asks where the field's experts write and where its canonical material is published. Log how many items each venue produced.
- Checkpoint: show the map (terms, people, venues) and the two directions; confirm the direction and the required claims in one round. Skip it only when the brief was formalized and round 0 changed neither the directions nor the claims; log the skip and why.

## Rounds 1 to 4: follow

Pick leads with a strong scent: named again and again, surveys and textbooks, cited as canonical, recommended by several practitioners. Six moves, the same for papers and for personal posts:

| Move | Papers | Personal posts | Tools |
|---|---|---|---|
| backward | references | links in the post, "based on X's article" | `chain.py refs`, grep the downloaded text |
| forward | citing works, most cited first | posts that cite or introduce it | `chain.py cites` (`--sort recent` for the newest), a searcher |
| author | the author's other papers | the author's archive, post list, channel | `chain.py author`, a searcher |
| venue | the core conference or journal | tags, forums, curated lists | a searcher |
| neighbors | same issue, same list | related posts, same tag, same playlist | a searcher |
| re-search | new terms from the map | the same, slang and abbreviations too | a searcher |

- In fields without papers the knowledge sits in practitioners' own records: do not restrict the dig to authoritative venues.
- Papers go by DOI: a DOI or id lookup costs nothing, while a title or name search costs 10 of the about 1,000 daily credits ($1.000 a day) OpenAlex gives without a key. Check `chain.py find` title candidates by year, title, type and venue before using one; a title can match a commentary or another record. A work flagged retracted never backs a required claim. For a preprint, look for its published version (`chain.py oa` lists it when OpenAlex merged the records, else `chain.py find` on the title, checking type and venue) and quote that version when it exists. A fetch marked unchecked could not ask OpenAlex: run `chain.py find` on its DOI before it backs a claim.
- OpenAlex lags: for a work under about a year old, 0 refs and 0 cites mean unknown, not none. Backward: grep the reference section of the downloaded text. Forward: a searcher looks for works citing the title.
- Two plausible directions: two searchers on two hypotheses in one turn; compare when both return, then continue.
- Download hits with `fetch.py <topic>/sources <name> <url>`; for a paper pass its DOI, so the legal open-access copies are tried before the publisher. Only OK rows enter the sources table. Every FAIL goes to `log.md` with its reason and URL. Before reporting a canonical work as unreached, look for another legal copy: `chain.py oa <DOI>`, the author's or lab's page, a technical report, an institutional repository, a curated site. Never piracy sites.
- A bot check (403, a browser check page) on a free page: ask the user to open it in their browser and save it, then run `fetch.py <topic>/sources <name> <saved file path>`. Never work around the check.
- Locate: grep the downloaded text for each required claim's passage (`grep -n -i "<words>" <topic>/sources/<file>`, then read a few lines around it) and write `file:line` plus a short quote on the claim line in `map.md`. Location and quote only, no summary or conclusion. A PDF's `.txt` copy is in reading order, which joins a word split at a line end and so also drops the hyphen of a compound split there; check the `.layout.txt` copy when a hyphen matters, and quote a table from it, since it keeps the rows. The quote matters: a line number alone is hard to find.

## End of each round (the main session decides)

Wait until every searcher of the round has returned; stop any that is no longer waited for. Round 0 only builds the map. A round counts once leads were downloaded and at least one backward, forward or author move was made (in a field without papers, following a downloaded post's links backward counts). A round where the searchers came back empty-handed and the main session searched itself still counts, but its saturation is not counted. Empty-handed means none of the pages a searcher named turned out to be a hit once downloaded.

Stop when one of these holds, and log which:
1. Every required claim has a source location (file:line and a short quote).
2. Saturation: 70 percent or more of the people and sources the searchers named this round were already in `map.md`, and few new terms appeared. Log the numbers ("11 of 14 already known"). Count only searchers that searched the same question with different methods; hypothesis branches overlap little by design, so judge each branch by its own claims. "Known" includes what the main session found itself, and the searchers get the same known list.
3. Four rounds done: list the claims not reached and why.
4. Wall: the originals for the remaining claims are all behind logins or paywalls, with nothing left in front of the wall. A partial claim counts when its missing part is walled. Free pages blocked only by bot checks go to the user's browser first.
5. Budget: a time or count limit agreed in the brief came first. Say how far each measure got (claims sourced, saturation numbers); never pretend a measure was met.

Never stop before round 1 is done, even when round 0 seems to cover every claim: stopping early and missing is the other typical error of search agents. When not stopping, write 2 to 4 leads for the next round to `log.md` first.

## Evidence page

1. Write `extracts.json` (`references/formats.md`): one entry per required claim with excerpts copied verbatim from the sources, translations for quotes in other languages, marks, disagreements side by side, and what was not reached. The agent writes only headings, statuses, one-line notes and translations; a note says who did what, never which side is right.
2. Run `report.py <topic_dir>`. Fix each MISMATCH by copying the source text exactly, never by editing the source or loosening the quote into a paraphrase. Auto-caption errors stay as they are.
3. `report.py <topic_dir> --check` passes before delivery.

## Deliver

First check that no searcher or background process from this run is still going; stop it and log it. Then, in the user's language:
1. The stop reason (one of the five).
2. Per required claim, its source location (`sources/<file>` and line), one or two lines each.
3. What was not reached.
4. The evidence page path first (`report.html`), then 2 to 4 originals to read, each with where to read in it.
5. Important items behind walls: URL and why it matters; the user opens them in their own logged-in browser. Never log in or create accounts.
6. Process problems noticed (tool failures, searchers overstepping their brief).
7. The feedback question; log the answer verbatim.

No summary or explanation unless the user asks; write it only then. Run `check.py` on the exact reply after its last edit (a saved file, or `-` for standard input) and send that text unchanged; never run it on report.html or sources. When the map has venues with feeds, offer in one line to watch them.

## Limits

- At most 2 searchers at once: saturation is counted between two methods, and more searchers cost more and blur the overlap.
- Searchers search the web, so the brief's generic problem statement is all they get.
- Copies in `sources/` are for local reading only; reports quote briefly and link.
