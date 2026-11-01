# phro-search

A Claude Code plugin with one research skill. It first works out what you actually need, then picks how to research it: dig into an unfamiliar field down to the original sources, write a decision report whose central claims are checked, read what communities said and shipped in the last N days, answer a technical question from primary documentation, pick a backbone model from public leaderboards, or watch a topic's venues for new posts.

Status: in development, not released. The design and the build plan are in `docs/plans/`.

## Install

After the first release:

```bash
claude plugin marketplace add ThatsHoon/phro
claude plugin install phro-search@phro
```

## Waiting for subagents

dig and report close a round only when every subagent of it has reported. In interactive sessions Claude Code runs subagents in the background by default, and their results arrive in later turns; the skill keeps the round open meanwhile. To let Claude wait for them instead, set `CLAUDE_CODE_FORK_SUBAGENT=0` in the `env` of your Claude Code settings. `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` makes Claude always wait, which also stops the docs mode from answering while its agents read.

## Tests

```bash
python -I -m unittest discover -s tests -t . -v
```

Intake evals in `evals/intake/` run real sessions (about 4 USD per set). The open set may search the web; the shut set has no tools beyond reading:

```bash
claude plugin eval . --tag open --scaffold --allow-tools WebSearch --no-publish
claude plugin eval . --tag shut --no-publish
```

## License

MIT
