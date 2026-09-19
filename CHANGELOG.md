# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for its skill contract: a breaking change is one that
invalidates an existing order, charter or ledger, or that changes what a conforming order must contain.

## [Unreleased]

### Added

- **`queue.json`: a single-executor queue declares its shared paths once.** One executor runs one
  queue's orders strictly serially, so an overlap *between two orders of the same queue* cannot put
  two writers on one file — but the validator cannot see that from the orders alone, and a queue
  where every order necessarily writes its own `status.md` / `evidence/**` / `tests/**` drowns the
  real signal. Measured on a live project: 22 and 37 hard failures inside two single queues, and 59
  lines per cross-tree sweep, all of them bookkeeping. A queue now says it once, in a `queue.json`
  next to its orders: `{"single_executor": true, "shared_paths": [...]}`. Overlaps covered by
  `shared_paths` are exempted (one summary line); uncovered ones print a `NOTE` that never fails the
  run, so unexpected sharing stays visible. A declaration that cannot be read, or that omits
  `single_executor` / `shared_paths`, is a hard failure in every mode — a guard must never be
  weakened by being unreadable. No file means no change at all, and cross-queue overlap still fails
  (validate two queues together in one directory that carries no `queue.json`).

## [0.2.0] - 2026-09-19

Breaking for conforming orders: an order must now declare its parallelism and a batch close
needs a `## Batch report`, and the validator rejects more than it used to.

### Fixed

- **The interpreter floor is now stated**: the validator needs Python 3.7 or newer (it uses
  `from __future__ import annotations`, which an older interpreter rejects while parsing, before any
  friendly error could be printed). Found by running it on a host that only had Python 3.6.

### Added

- **The human contract (§0c)**: the workflow's point is spending the human's time on decisions, so joining and
  leaving are both free. The human does three things - give the goal, rule, accept - and the return surface is the
  ledgers (the "what needs you" section, the approval queue, the newest checkpoints), not the chat log. Questions
  that genuinely need a human are batched into one place with option, cost, recommendation and the consequence of
  not deciding; anything the scheduler can decide, it decides. Work never stalls while the human is away, and
  reading costs one screen, with detail left in files. Both READMEs now name the human cost under the problems
  they fix, and an eval case covers the "I am leaving for a few hours" request.


- **Checkpoints are for mid-course acceptance**: the purpose is now stated as a rule rather than implied by
  "inspection window" - the user should not have to wait for everything to finish before verifying something and
  giving new decisions. Each order that closes something user-visible gets its own checkpoint
  (`checkpoint/<batch>-<order>`), batch checkpoints stay as they were, the report must name what can be tried now,
  what is deliberately not in yet and the known defects, and the scheduler's roll-up lists each tree's newest
  checkpoint with its distance from HEAD so a stale window is visible instead of silent. A checkpoint still never
  stops the executor; an eval case covers the "I want to look now and give new direction" request.


- **Entry path**: the trigger text now names planning, splitting work across several agents or sessions,
  supervising a long-running loop, resuming unfinished work and wanting independent eyes, in both languages.
  `SKILL.md` §0a states that selecting the skill makes the session the scheduler and gives the first-round
  script (read the site measured, then present a menu of options with costs, record the user's choice, hand over
  launch material, start dispatching), and §3.0 walks the decision path from a goal to a formation.
- **`assets/role-goal-prompts.md`**: launch prompts for the optional roles and loops - reviewer, acceptance
  poller, reuse scout, scheduler loop - so a new session can be opened by pasting, not by writing the prompt from
  scratch, plus the one-writer-per-file discipline those sessions share.


- **`parallelism` must be declared, and cross-checks exist** (driven by a live queue review; the measurements are
  from a real run, no project details). An omitted or empty `parallel_units` list used to mean "single-threaded"
  silently - in one queue **64 of 81 orders carried an empty list**, so executors were locked to one thread and
  nobody had decided it. An order must now either list real `parallel_units` or declare
  `parallelism: "none"` with a `parallelism_reason`. The validator also gained four cross-checks: duplicate ids in
  one set, `depends_on` entries that resolve neither to a local order nor to a pinned external condition,
  **overlapping `write_paths` between two orders** (at least one side must declare `serialize_with`; this used to
  be kept in prose), and `--manifest` reconciliation. Declarations are advisory by default and hard failures under
  `--strict`, so a running queue stays workable while batch close and merge cannot pass.
- **`revisions` records**: an order whose body claims a revision (`修订 v2`, `Revision 2`) must carry
  `revisions: [{"at": <sha>, "what": ..., "after_stage": N, "ruling": R-xxxx}]`. Instructing notes about revisions
  (a template telling the executor what to record) are not claims and do not trip it.
- **`## Batch report`** closes a batch: gate counts, exit codes, evidence index, remaining gaps.
- **`--legacy-ok`** keeps a pre-v2 queue workable; the rule that replaces the exemption is that an order touched
  again (revised, re-dispatched, split) must be upgraded to the current template.
- **Two documents**: `SKILL.md` §0b states the division of labour (the scheduler gets a menu and may deviate with a
  reason; the executor gets constraints), §12 lists the optional roles and loop shapes, §13 is the
  self-optimisation loop (find a rule that does not fit, record it with evidence, ask the user, then change the
  skill through its normal process). `references/roles-and-loops.md` is the checklist for opening a role.
- **File names** accept `NNN-slug.md` (two to four digits), split siblings (`012a-...`) and line prefixes
  (`A12a-...`), because a real line with prefixed order names could not run the validator at all.

### Fixed


- **The shipped work-order template was still v1** while `SKILL.md` required the v2 format: no frontmatter, no
  `Requirements`/`Scenario`, plain-number stages, and headings (`Exact scope`, `Definitions of Done`) the
  validator does not recognise. Anyone copying the official template would have produced an order that failed the
  official validator. Restored to v2, and CI now proves it: the template is filled in, must pass `--strict`,
  must be refused as an unfinished batch, and must pass once its stages are ticked (`tests/fill_template.py`).
- **Four validator rules were not enforced** (found by external review, reproduced, then fixed):
  a gates table with empty counter-example/absent cells was skipped when the row had fewer cells than the header
  (`continue` instead of a defect); `ruling: 123` passed because a non-string was ignored; a second `Requirement`
  without its own `Scenario` passed; `waive` entries listing a section without a reason passed.
- A variable-shadowing bug introduced while fixing the waive check (a loop variable named `text` clobbered the
  document text), caught by the new per-rule tests.
- **The initialisation checklists disagreed on whether `prefs.md` exists at init.** `SKILL.md` §2 said "只建
  那五样" and `GETTING-STARTED.md`'s step-1 prompt and eval 1 followed it, while
  `references/initialization-checklist.md` (the text §2 points at) and both README quickstarts build six —
  including `prefs.md`, which §1b/§1c/§4b/§10 treat as load-bearing (execution mode, consult-first, cost cap).
  Unified on six files.

### Added

- `tests/test_validate_order.py` — nineteen regression tests, one counter-example per rule, run in CI.
- `tests/fill_template.py` — the template gate described above.
- `examples/walkthrough.md` — a worked batch with a mid-flight decision, a blocker the executor could not decide,
  a revision and its receipt, a checkpoint, a defect found by testing, and a merge pinned to a snapshot.
- CI steps for both new checks. The eval step is now labelled explicitly as *structural only*: `evals/evals.json`
  is parsed, not executed — running the behavioural cases needs an agent (`claude plugin eval`), and the two kinds
  of evidence are kept separate.

### Added

- **Executor-side parallelism, bounded and non-writing.** The scheduler declares the independent units in the order
  (`parallel_units` — the declaration *is* the authorisation), and the executor may fan out subagents inside them:
  depth one, at most four at a time, disjoint files. Subagents never touch the contract, this tree's ledger, or git —
  they produce file changes while the executor alone commits, ticks stages, runs the gates and records their requests
  and cost under the budget in `prefs.md`. A subagent's report is a cited claim, not evidence: the executor must
  re-run that unit's gate before a stage may be ticked. Order and charter templates carry the field, the preferences
  ledger gains a row, and three validator tests cover the malformed cases.

### Changed

- **Merges are pinned to the checkpoint's commit sha**, not to the executor's branch. Because the executor never
  stops, the branch keeps moving after approval; the approval therefore binds to `checkpoint/<batch>^{commit}`,
  which must match `merge_back[].sha`. If the main tree moves between approval and merge, the integration
  conditions are re-checked first.
- **Delivery uses a pathspec commit** (`git add -N -- <path>` then `git commit -- <path>`). A bare
  `git add` + `git commit` in a shared worktree commits the executor's staged files too — reproduced locally, and
  now forbidden in the rules, with a pre-commit check of the staged path set.


### Added

- **Plugin packaging**: `.claude-plugin/marketplace.json` and `plugin.json`, so the skill installs with
  `claude plugin marketplace add mmm-05610/incremental-work-order` and
  `claude plugin install incremental-work-order@incremental-work-order` (Claude Code, and ZCode which reads the
  same marketplace format). The manifest passes `claude plugin validate`.
- **`install.sh`**: a dependency-free installer for any agent — picks the first existing skills directory,
  supports `--target`, `--tag`, `--from`, `--copy` and `--update`, and refuses to overwrite an existing install.

### Changed

- README install section (both languages) now documents the three routes with the measured facts (Skills (1),
  ~150 tokens always-on / ~1.9k on invoke) instead of a single clone command.

## [0.1.0] - 2026-09-18

First public release of the workflow.

### Added

- **The model**: one main tree schedules; each sub-tree executes its own slice of work orders; trees are
  hierarchical (a parent may write the sub-trees it dispatched, inside a whitelist; siblings and outside repos
  get no orders at all).
- **Orders as the contract of record**, living in the executing tree's `docs/implementation/work-orders/`, with
  a fixed structure: JSON frontmatter (id, slug, batch, baseline, decidable dependency conditions, write paths,
  ruling id, terminal codes, waivers), requirements carried as WHEN/THEN scenarios, checkbox stages, and a gates
  table whose counter-example and absent-behaviour columns are mandatory.
- **Batches and checkpoints**: a batch ends with a `checkpoint/<batch>` tag and a checkpoint report in the
  executing tree's own ledger; the executor carries straight on. A checkpoint is an inspection window, not a stop.
- **Delivery is the notification**: writing an order into a sub-tree and committing it there is what notifies the
  executor, which re-reads at every stage boundary; nothing is message-passed between sessions and no copies drift.
- **Ledgers**: a dispatch view (`manifest.json`), a roll-up with known gaps and cost (`status.md`), a citable
  decision ledger (`rulings.md`, `R-0001` …) and a preferences ledger (`prefs.md`).
- **Flexibility with a paper trail**: the rules are defaults; deviations require a written `waive` reason. The
  non-waivable floor is credentials and protected paths, no pushing or auto-merging a mainline, and user approval
  for opening a tree, merging, widening scope or loosening acceptance.
- **Two execution modes**: `dispatch` (sub-tree plus its own long-running session, the default) and `solo` (the
  main tree implements directly, optionally with a subagent, keeping every ledger and gate).
- **`scripts/validate_order.py`** — a dependency-free structural validator: `--strict`, `--json`, and
  `--batch <name>`, whose checkbox check doubles as the merge gate.
- **Anti-false-green checklist**: gates must state what they do when a resource is absent, guards must be proven
  to detect a positive, documentation/code contradictions must not be pinned green by a test, and PARTIAL must
  never be written as DONE.
- **Templates**: work order, worktree charter, preferences ledger, executor capacity ledger, executor charter,
  and the ≤15-line launch prompt that the scheduler hands to the user inline.
- **Eighteen behavioural eval cases** in `evals/evals.json`.

### Notes

- Borrowed with attribution: OpenSpec's strict structural validation and archived-checkbox gate, its
  proposal/tasks layout and its requirement/scenario convention; Spec Kit's per-project constitution, narrowed
  here into a preferences ledger.
- Deliberately not included: session spawning (an agent cannot open a session, so the human pastes the launch
  prompt), dispatching into repositories you do not own, automatic merging, and silent loosening of acceptance.
