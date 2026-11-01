# phro-search

A Claude Code plugin with one research skill. It first works out what you actually need, then picks how to research it: dig into an unfamiliar field down to the original sources, write a decision report whose central claims are checked, read what communities said and shipped in the last N days, answer a technical question from primary documentation, pick a backbone model from public leaderboards, or watch a topic's venues for new posts.

Status: in development, not released. The design and the build plan are in `docs/plans/`.

## Install

After the first release:

```bash
claude plugin marketplace add ThatsHoon/phro
claude plugin install phro-search@phro
```

## Requirements

- Python 3.10 or later. The scripts use the standard library only. The skill runs them as `python3` on macOS and Linux and as `python` on Windows.
- Windows: Git Bash (it comes with Git for Windows). Claude Code runs the plugin's egress hook through it (`sh`); without it the hook cannot start, and web searches and fetches may be blocked.
- poppler, for PDFs that are not on arXiv: `pdftotext` reads their text. arXiv papers are read from their HTML version and need nothing.
- tesseract and `pdftoppm` (from poppler), for scanned PDFs with no text layer. Korean and Japanese OCR need tesseract's `kor` and `jpn` language data as well.
- yt-dlp, for video captions and the pulse mode's YouTube lane.

Without one of these tools, the run goes on: the script prints a `FAIL` line, or a skipped lane, with the install command for your system.

| Tool | macOS | Debian, Ubuntu | Windows |
|---|---|---|---|
| poppler | `brew install poppler` | `sudo apt install poppler-utils` | `scoop install poppler` |
| tesseract | `brew install tesseract` | `sudo apt install tesseract-ocr` | `winget install UB-Mannheim.TesseractOCR` |
| yt-dlp | `brew install yt-dlp` | `pipx install yt-dlp` | `winget install yt-dlp.yt-dlp` |

On other Linux systems, use your package manager's poppler, tesseract and yt-dlp packages.

### Private terms

Searches and fetches carry a generic problem statement only. To have the hook and the scripts block terms that must never leave your machine (project names, client names, code names), list them in `~/.claude/phro-search/forbidden.txt`, one term per line; lines starting with `#` are comments, and terms shorter than 2 characters are ignored. A project can add its own list in `.phro/project.json` at its root:

```json
{"egress": {"forbidden_terms": ["project-codename", "client name"]}}
```

Matching ignores case and Unicode width, and also checks percent-decoded URLs. Where no list exists, the hook lets every call through without starting Python.

### Allowing the scripts

The skill calls each script with literal paths, one command per call, so one allow rule in your Claude Code settings covers them. The scripts sit in the plugin's install folder, whose path holds `phro-search`:

```json
{"permissions": {"allow": ["Bash(python3 -I */phro-search/*/scripts/*.py *)"]}}
```

On Windows, use `"Bash(python -I */phro-search/*/scripts/*.py *)"`. If Claude still asks, compare the rule with the command it shows and adjust the path pattern.

## Waiting for subagents

dig and report close a round only when every subagent of it has reported. In interactive sessions Claude Code runs subagents in the background by default, and their results arrive in later turns; the skill keeps the round open meanwhile. To let Claude wait for them instead, set `CLAUDE_CODE_FORK_SUBAGENT=0` in the `env` of your Claude Code settings. `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` makes Claude always wait, which also stops the docs mode from answering while its agents read.

## Tests

```bash
python3 -I -m unittest discover -s tests -t . -v
```

On Windows, run `python` instead of `python3`.

Intake evals in `evals/intake/` run real sessions (about 4 USD per set). The open set may search the web; the shut set has no tools beyond reading:

```bash
claude plugin eval . --tag open --scaffold --allow-tools WebSearch --no-publish
claude plugin eval . --tag shut --no-publish
```

The routing set and the scorers for round-0 recall and the verifier set are described in `evals/README.md`; they run headless with `claude -p` in your own environment.

The answers to the feedback question that closes each result are logged per topic as `feedback: fit=...; missing=...` lines. `python3 -I dev/feedback_gold.py ~/research` lists each missing item as a gold-item candidate for the eval set of its mode; add the ones that hold up by hand.

## License

MIT
