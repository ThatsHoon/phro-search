# phro-search

A Claude Code plugin with one research skill. It first works out what you actually need, then picks how to research it: dig into an unfamiliar field down to the original sources, write a decision report whose central claims are checked, read what communities said and shipped in the last N days, answer a technical question from primary documentation, pick a backbone model from public leaderboards, or watch a topic's venues for new posts.

Status: in development, not released. The design and the build plan are in `docs/plans/`.

## Install

After the first release:

```bash
claude plugin marketplace add ThatsHoon/phro
claude plugin install phro-search@phro
```

## Tests

```bash
python -I -m unittest discover -s tests -t . -v
```

## License

MIT
