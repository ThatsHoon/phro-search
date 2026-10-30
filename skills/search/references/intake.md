# Intake

Load this when the need is not formalized. SKILL.md holds the steps; this file holds the tactics. Questions, candidate briefs and the brief are shown in the user's language; the brief is stored in English in `map.md`.

## 1. Read the need level

| Level | Example request | Tactic |
|---|---|---|
| formalized | "Compare tools A and B for checking quotes against PDFs; a table with sources." | one-line plan; gate only if a slot was inferred or defaulted |
| conscious | "Is there research on asking users good follow-up questions?" | probe, candidate briefs, one round on what is left |
| compromised | "Find papers on beam search." (the use: an ASR output that repeats words) | ask the use first, then candidates that include the restated object |
| visceral | "Our onboarding feels slow and I don't know why." | neutral situation and use questions first, then candidates that include "map the field first" |

The levels are points on a continuum, not stages (Taylor 1968): take the nearest row.

Neutral questions for a visceral need ask about the situation, the gap and the use, never about the topic:
- What were you trying to do when this came up?
- What would you do with the answer once you have it?
- What have you tried, read or ruled out already?

## 2. Harvest

Cheap sources first; mark each slot stated, inferred (from what) or unknown.
- The conversation: goals, constraints, links and names (seeds), the words the user uses.
- The open repo: README, CLAUDE.md, manifests (languages, frameworks, versions), recent doc headings. Send anything deeper to a subagent and keep asking the questions that do not depend on it.
- Earlier topics: `ls ~/research/` and `grep -h "^brief:\|^feedback:" ~/research/*/log.md`. A similar earlier brief turns its choices (deliverable, depth, source kinds, budget) into the recommended options, marked "as last time". Feedback that a brief missed ("too shallow", "wrong sense of the term") becomes a question or a default this time. Show anything learned this way; never apply it unseen.
- Nothing harvested goes into a query, a probe or a subagent brief.

## 3. Probe

- 1 to 3 standard web searches by the main session, built from the user's words with every private detail removed: `<term> meaning`, `<term> survey`, `<term> vs <neighbor>`.
- Pull out: the senses of an ambiguous term; the sub-areas; the main options or entities; how recent the activity is (latest years seen); the field's own terms for the user's words.
- The vocabulary bridge, one line per pair, shown once: `<user's words> = <field term> (<synonyms>)`. Candidate briefs and every later query use the field's terms.
- Show only the bridge and what the candidates need. Result snippets are not findings: name sub-areas and works, never their results or numbers, which stay unread until the run.
- A probe never downloads, chains or spawns. Anything more is research and waits for the gate.

## 4. Candidate briefs

```
A (recommended: <one reason>). <object in the field's terms>. Deliverable: <deliverable> (<mode>). Done when: <2 or 3 required claims or the done condition>.
B. <a different object or deliverable>. Deliverable: ... Done when: ...
C. Map the field first: its terms, people and venues, then a sharper brief (dig round 0).
```

- 2 or 3 readings that differ in object or deliverable, not in wording.
- A visceral need always gets "map the field first"; a compromised one gets a restated object (the use behind the means).
- With AskUserQuestion, one question whose options are the candidates, previews holding each mini brief; otherwise a numbered list. The user picks, combines or corrects one; the pick fills use, object, deliverable and done condition at once.

Example, conscious: "Is there research on asking users good follow-up questions?"
- A (recommended: the request asks whether research exists). dig: clarifying questions in conversational search and dialogue systems. Done when: venues; canonical papers; measured gains; where clarifying questions fail.
- B. report: compare 3 practical ways to add clarifying questions to a chat product, with a decision table.
- C. Map the field first.

## 5. Slots

Ask in this order; skip a slot whose every answer leads to the same plan (it takes its default).

| Slot | Ask when | Question pattern | Default when unknown |
|---|---|---|---|
| Use | first, unless stated | What will the result feed: a fix, a decision, a build, a write-up? | the likeliest use from context, as an assumption |
| Object | after the probe | the candidate briefs | none: always settled |
| Situation | visceral or compromised | What have you tried or ruled out? | nothing known |
| Deliverable | after the use | options from the modes | follows from the use |
| Constraints | when they remove options | memory or device, license, cost, latency, runtime | none |
| Scope | when time, region or language changes the sources | options from the probe | no window; sources in English and the user's language |
| Evidence bar | when the field mixes papers and practice | papers, official docs, practitioner posts, measurements | by the field |
| Audience | when it changes depth or register | you, your team, a decision maker | the user |
| Done when | always; drafted by the system | These claims define done: change any? | the drafted claims |
| Out of scope | when the situation shows known material | Skip what you already know: ...? | none |
| Budget | stated in the plan line; asked only when the ceiling is high | rounds or agents and the ceiling | the mode's default |

Seeds and Hypothesis are harvested, not asked, unless they would change the plan: ask "Start from the link you mentioned?" only when a seed was vague, and "You expect X: should the run test that directly?" only when the user leans toward an answer. A hypothesis is tested, never assumed.

## 6. Writing a question

- Options, not blanks: a user who lacks the field's words recognizes the right option long before they can phrase it.
- The recommended option first, marked, with its reason in a few words; "yes" accepts it.
- A "don't know" option that takes the default and records it as an assumption.
- One decision per question; at most 4 questions per round, the ones that change the mode first, then the object, then constraints that remove options, then scope and evidence bar.
- Field terms with the user's words in parentheses on first use.
- No leading questions, no tool internals, no facts the environment can give, nothing this session or the topic's `log.md` already answered.
- AskUserQuestion when the host has it: one call per round, up to 4 questions, "(Recommended)" on the first option, previews for candidate briefs.

Good: "Which do you need first? 1. A field map with the originals (recommended: the field is new to you). 2. A decision report comparing the main options. 3. Don't know: take 1."
Bad, and why:
- "What exactly do you want to research?" (a blank with no options)
- "Should I use OpenAlex?" (a tool internal, not the user's decision)
- "Shall I find papers proving that X works?" (leading; the run tests X)
- "Which version of the library are you on?" when the lockfile says so (a fact to look up)

## 7. The brief

Stored as the first section of `map.md` (English), shown to the user in their language:

```
## Brief
Title: <title in the user's language>
Use: <what the result feeds>
Object: <in the field's terms> (anchor terms: <terms that disambiguate>)
Situation: <known, tried, ruled out>
Seeds: <links, names, papers the search starts from>
Hypothesis: <expected answer, tested and never assumed>
Deliverable: <deliverable> (<mode>)
Audience: <who reads it>
Scope: <window, region, languages, domain limits>
Constraints: <hard limits>
Evidence bar: <source kinds that count>
Out of scope: <known already or not wanted>
Budget: <rounds or agents, ceiling>
Assumptions: <slot>: <value> (defaulted) | <slot>: <value> (inferred from <where>)
Required claims:
- [ ] C1 Where this field's knowledge gathers (venues)
- [ ] C2 <claim>
```

Empty slots are left out. Required claims for dig: the first is always the venues; at least one carries the request's exact condition in its own words; at least half can only be answered by reading originals (how well it works, where it fails, what is missing), not "X exists"; a request for tips or how-tos gets one claim asking for the research behind the tips. For report they are 3 to 6 key questions (Q1 to Q6) the report must answer, at least one in the request's own words.

## 8. During the run

- dig: after round 0, show the map (terms, people, venues) and the two directions, then confirm the direction and the required claims in one round, unless dig.md's skip condition holds.
- A finding that changes the question: ask once before re-scoping, log the reason; reworded, added or dropped claims count as brief drift.
- A hand-off to another mode copies the brief and asks only what changes.
- Log the intake line after the gate and add re-scopes and drift at delivery (`references/formats.md`).
