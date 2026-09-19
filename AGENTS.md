# AGENTS.md — working on this repository

This repository *is* a skill (an agent-facing workflow). If you are an agent asked to change it, read
`CONTRIBUTING.md` first; the short version:

## The two invariants

1. **One copy of the rules.** `SKILL.md` holds every rule. Everything else — `GETTING-STARTED.md`, `assets/`,
   `references/`, `README.md` — may point at it and summarise for humans, but must not restate a rule. If you
   see a rule written twice, deduplicate it in the same change.
2. **Every guard must be shown to fail.** `examples/conforming/` must pass the validator and
   `examples/nonconforming/` must fail it. CI checks both directions; a change that makes the negative example
   pass is a bug in your change, not in the example.

## Before you commit

```bash
# requires Python 3.7+ (CI runs 3.12); the validator will not even parse on older interpreters
python3 -c "import json,pathlib; json.loads(pathlib.Path('evals/evals.json').read_text())"
python3 -m py_compile scripts/validate_order.py
python3 -m unittest discover -s tests                                     # per-rule counter-examples
python3 tests/fill_template.py                                            # shipped template stays usable
python3 scripts/validate_order.py examples/conforming --strict            # must pass
python3 scripts/validate_order.py examples/nonconforming --strict; test $? -ne 0   # must fail
# optional, and only if you have the Claude Code CLI: validates the plugin/marketplace manifests
claude plugin validate .
```

## Changing behaviour

- Behaviour change → add or amend an eval case in `evals/evals.json`.
- Order-format change → update `assets/work-order-template.md` **and** `scripts/validate_order.py` together,
  plus the conforming/nonconforming examples.
- Rule change → `SKILL.md` only, then check that nothing else now contradicts it.
- Add a `CHANGELOG.md` entry under *Unreleased* for anything a consumer would notice.

## Never

- Add absolute home paths, employer or client names, or examples lifted from a private project.
- Add dependencies, vendored code, or anything that stops `validate_order.py` from running on a stock Python 3.
- Push, force-push, or rewrite published history as part of a change under review; propose the commit instead.
- Write a rule that cannot be checked (see the SECURITY policy: an unenforceable rule is a security bug).

## Layout

| Path | Role |
| --- | --- |
| `SKILL.md` | The scheduler's rules — the single text |
| `GETTING-STARTED.md` | Human onboarding |
| `assets/` | Templates: work order, worktree charter, prefs, status, executor charter, launch prompt |
| `references/` | Checklists: initialisation, false green |
| `scripts/validate_order.py` | Structural validator (and the batch merge gate) |
| `evals/evals.json` | Behavioural test cases |
| `examples/` | One conforming and one nonconforming order, both exercised by CI |
