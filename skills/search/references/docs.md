# docs

Answer a technical question the open code depends on (an API's behavior, a spec detail, library internals) from primary sources, in one note saved where the repo keeps such notes. Two agents read in the background, so the conversation goes on meanwhile: a local reader on the installed source and a web gatherer on the documentation. This session writes the note.

## Before the agents

- Settle the library and its version from the repo: lockfiles and manifests first (`uv.lock`, `poetry.lock`, `requirements*.txt`, `package-lock.json`, `go.sum`, `Cargo.lock`), then the installed copy (`pip show <package>`, `node_modules/<package>/package.json`). Ask which library or version only when the repo does not settle it, with the candidates found as options.
- Find where the repo keeps notes: a folder of research or decision notes (`docs/notes/`, `docs/research/`, `docs/adr/`, `notes/`), its file naming and its language. With none, the path `docs/research/<slug>.md` is a defaulted slot: show it at the gate and write nothing before the user confirms or changes it.
- Plan line: "docs: local reader and web gatherer (sonnet), note at <path>"; with no installed copy, the web gatherer alone.
- What goes to the web gatherer is generic: library names, versions and public APIs are fine; project names, private code and local paths stay on the machine. Only the local reader's brief names local files.

## Agents

Spawn both in one turn, in the background. Each replies with text and writes no file.

Local reader (`phro-search:local-reader`), when the package is installed:

```
You are a docs reader. Read only the installed package at <path> and these repo files and line ranges: <files and ranges>.

Question: <the question>
Library and version: <name> <version> (from <lockfile or manifest>)

Find the code that decides the answer and follow each claim to the code that owns it. Reply with at most 15 lines:
- <claim> (<path>:<line>, <version>)
Then "Checked and not found:" with what you looked for and where.
```

Web gatherer (`phro-search:web-gatherer`):

```
You are a docs researcher.

Question: <the question in generic terms>
Library and version: <name> <version>

Primary sources, in this order: the official documentation for that version; the specification or standard it implements; the project's repository (code, tests, changelog, maintainers' answers in issues). Blog posts, Q&A sites and generated answers are only leads to a primary source, never evidence.
Follow every claim back to the source that owns it. Reply with at most 15 lines:
- <claim> (<URL>, section "<heading>")
Then "Checked and not found:" with what you looked for and where.
```

## Write and deliver

- Keep working with the user while the agents run; their replies arrive as notifications, so never wait on them in silence.
- When both have replied, write the note at the confirmed path in the repo's layout and language, or this one:

```
# <title>
Question: <question>. Use: <use>. Version: <name> <version>. Date: <YYYY-MM-DD>.
## Answer
<at most 3 lines>
## Evidence
- <claim> (<citation>)
## Checked and not found
- <source>: <what was looked for>
## Caveats
- <version ranges, platforms, settings that change the answer>
```

- Every line under Evidence cites code (`<path>:<line>` with the version) or the version's documentation (URL and section); a claim resting on a blog or Q&A answer goes under Caveats as unconfirmed. Where the code and the docs disagree, the installed code wins for this version, and the disagreement goes under Caveats.
- Run `python -I ${CLAUDE_PLUGIN_ROOT}/scripts/check.py <path>` and rewrite only the flagged spots until it prints OK.
- Reply in the user's language with the note path and the answer in at most 3 lines. "Not found in primary sources", with what was checked, is a valid answer.
- Ask the feedback question in one line; docs keeps no log and no topic folder.
