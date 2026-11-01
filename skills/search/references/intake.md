# Intake

SKILL.md holds the intake steps; this file holds their tactics.

## 1. Read the need level

| Level | Example request |
|---|---|
| formalized | "Compare tools A and B for checking quotes against PDFs; a table with sources." |
| conscious | "Is there research on asking users good follow-up questions?" |
| compromised | "Find papers on beam search." (the use: an ASR output that repeats words) |
| visceral | "Our onboarding feels slow and I don't know why." |

The levels are points on a continuum, not stages (Taylor 1968): take the nearest row.

Neutral questions for a visceral need ask about the situation, the gap and the use, never about the topic:
- What were you trying to do when this came up?
- What would you do with the answer once you have it?
- What have you tried, read or ruled out already?

## 2. Harvest

Cheap sources first; an inferred slot records what it was inferred from.
- The conversation: goals, constraints, links and names (seeds), the words the user uses.
- The open repo: manifests give languages, frameworks and versions. Send anything deeper to a subagent and keep asking the questions that do not depend on it.
- Related earlier topics (the Grep in SKILL.md intake step 1): a similar earlier brief turns its choices (deliverable, depth, source kinds, budget) into the recommended options, marked "as last time". Feedback that a brief missed ("too shallow", "wrong sense of the term") becomes a question or a default this time. Show anything learned this way; never apply it unseen.

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
C. Map the field first (dig round 0). Deliverable: a map of the field's terms, people and venues. Done when: the map names them and a sharper brief is drafted from it.
```

- 2 or 3 readings that differ in object or deliverable, not in wording. Every candidate, C included, states its deliverable and done condition.
- With AskUserQuestion, one question whose options are the candidates, previews holding each mini brief; otherwise one question in the section 6 template, a candidate per option. The pick fills use, object, deliverable and done condition at once.

Example, conscious: "Is there research on asking users good follow-up questions?"
- A (recommended: the request asks whether research exists). dig: clarifying questions in conversational search and dialogue systems. Done when: venues; canonical papers; measured gains; where clarifying questions fail.
- B. report: compare 3 practical ways to add clarifying questions to a chat product. Done when: a decision table over cost, measured gain and risk.
- C. Map the field first, as in the template.

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

```
1. <question>
   a. <option> (recommended: <reason in a few words>)
   b. <option>
   c. Don't know: take a.
```

- Follow-ups take this shape too. The recommended option is the likeliest answer or, when none is likelier, the safe default (such as "any domain"); "don't know" records the default as an assumption; "yes" accepts every recommended option.
- Options, not blanks: a user who lacks the field's words recognizes the right option long before they can phrase it. A detail with many possible answers (a cloud, a language) gets the likeliest 2 or 3 and "other: say which".
- One decision per question. Questions that change the mode come first, then the object, then constraints that remove options, then scope and evidence bar.
- Field terms with the user's words in parentheses on first use.
- No leading questions, no tool internals, nothing this session or the topic's `log.md` already answered. A stated fact or rule taken in its usual reading is recorded as an assumption.
- AskUserQuestion when the host has it: one call per round, "(Recommended)" on the first option.

Good: "Which do you need first? a. A field map with the originals (recommended: the field is new to you). b. A decision report comparing the main options. c. Don't know: take a."
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

- A finding that changes the question: ask once before re-scoping, log the reason; reworded, added or dropped claims count as brief drift.
- A hand-off to another mode copies the brief, and its slots count as stated: ask only what the new mode adds (report: the key questions; models: constraints and required features; pulse: the window) and what the new request changes.
