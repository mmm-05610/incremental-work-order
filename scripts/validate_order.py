#!/usr/bin/env python3
"""Validate work orders against the incremental-work-order structural contract.

Usage:
  validate_order.py <file-or-dir> [--strict] [--batch <name>] [--legacy-ok]
                    [--manifest <path>] [--json]

Checks (all modes):
  * file name is ``NNN-slug.md`` (two to four digits), ``NNNx-slug.md`` (a split sibling
    such as ``012a-…``) or ``<PREFIX><N>-slug.md`` (line-prefixed, e.g. ``A12a-…``, ``Q12-…``)
  * frontmatter parses; lists are JSON literals; required keys present
  * id/slug agree with the file name; ruling is R-NNNN; write_paths non-empty
  * terminal state list contains a *_DONE entry (and any *_PARTIAL)
  * required sections present, unless waived in the frontmatter `waive` list
  * Requirements: at least one "### Requirement:" and one "#### Scenario:" whose
    body carries **WHEN** and **THEN**
  * Stages: at least one "- [ ]" / "- [x]" checkbox
  * Gates: a markdown table with columns for assertion, counter-example and
    absent-behaviour, and at least one row with non-empty counter-example/absent

Declaration checks (advisory here, hard failures under --strict) — added 2026-09-19:
  * parallelism must be declared one way or the other: a non-empty `parallel_units`
    list, or `parallelism: "none"` with a non-empty `parallelism_reason`.
    An omitted key or `parallel_units: []` used to mean "single-threaded" silently,
    which switched executor parallelism off without anyone noticing (measured on a
    live queue: 64 of 81 orders carried an empty list).
  * `revisions`: a body that speaks of a revision must carry structured records,
    `revisions: [{"at": <sha>, "what": ..., "after_stage": N, "ruling": R-xxxx}]`
  * in `--batch` mode: a `## Batch report` section (gate counts / exit codes /
    evidence index / remaining gaps) is what closes a batch

--strict adds:
  * Validation section must contain a fenced code block with runnable commands
  * the declaration checks above become hard failures

Cross-checks (directory mode; hard failures under --strict, advisory otherwise):
  * duplicate order ids inside the validated set
  * `depends_on` entries resolving neither to an order in this set nor to a pinned
    external condition (a sha-looking token or a named tree)
  * `write_paths` overlap between two orders in the set — at least one side must
    declare `serialize_with` (this is what keeps two parallel lines off one file).
    A queue that declares itself single-executor is exempt from this inside itself:
    see "Queue declaration" below.
  * `--manifest <path>`: batch agreement with the manifest row for that id, and the
    manifest's document pointer must exist next to the manifest or the orders

--batch <name> validates every order declaring that batch in the given directory and
  additionally requires *every* stage checkbox of *every* order in the batch to be
  ticked (the merge gate; mirrors OpenSpec's `validate --archived`).

--legacy-ok exempts orders that carry no frontmatter (the pre-v2 queue) from the
  structural checks; the stage-checkbox gate still applies. The skill's rule: an
  order that is touched again (revised, re-dispatched, split) must be upgraded to
  the current template rather than staying legacy.

Queue declaration (`queue.json`, optional, next to the orders — measured need
2026-09-19): one executor runs one queue's orders strictly one after another, so an
overlap *between two orders of the same queue* cannot put two writers on one file.
The validator cannot know that from the orders alone, and a queue where every order
necessarily writes the same bookkeeping paths (its own `status.md`, `evidence/**`,
`tests/**`) drowns the real signal: measured on a live project, 22 and 37 hard
failures per queue and 59 lines per cross-tree sweep, all of them bookkeeping. The
queue says it once instead:

    {"single_executor": true,
     "shared_paths": ["docs/implementation/status.md", "tests/**"]}

With that file present, an overlap between two orders of this set is not a hard
failure. Overlaps covered by `shared_paths` are exempted (counted in one summary
line); overlaps *not* covered are printed as `NOTE` lines that never fail the run,
so unexpected sharing stays visible. A present-but-malformed declaration is a hard
error in every mode — a guard that cannot be read must never silently downgrade
another guard. Absent file = no change at all. **Cross-queue** overlap (two queues
writing one file) is still a hard failure: validate two queues together in one
directory that carries no `queue.json` (a union sandbox), and at least one side must
declare `serialize_with`.

Requires Python 3.7 or newer - the `from __future__ import annotations` at the top is a
parse-time error on older interpreters (measured: 3.6 refuses the file outright).

Exit code 0 = pass, 1 = violations, 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

NAME_NUMBERED = re.compile(r"^(\d{2,4}[a-z]?)-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
NAME_PREFIXED = re.compile(r"^([A-Za-z]{1,4}\d{1,4}[a-z]?)-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
RULING_RE = re.compile(r"^R-\d{4}$")
SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
EXTERNAL_RE = re.compile(r"tree|树|checkpoint/[\w./-]+")
# Only a *claim* counts: "修订 v2", "修订：", "已修订", "Revision 2"
# — prose like "纳入新单/修订 + 留回执" (an instruction) must not trip it.
REVISION_MARKER = re.compile(r"修订\s*(?:v|V)?\d|修订[版次]|修订[：:]|已修订|Revision\s+\d|revision\s*[:：]\s*\S")
# Sections that *instruct* about revisions (a template telling the executor what to record)
# must not count as a claim that this order was revised.
INSTRUCTING_SECTIONS = ("Notes for the executor", "Checkpoint report", "Batch report", "Validation")
REQUIRED_KEYS = ("id", "slug", "batch", "baseline", "ruling", "write_paths", "terminal")
REQUIRED_SECTIONS = (
    "Objective",
    "Current state",
    "Scope",
    "Requirements",
    "Stages",
    "Gates",
    "Validation",
    "DoD",
    "Acceptance",
)
WARN = "WARN: "


def parse_frontmatter(text: str):
    if not text.startswith("---\n"):
        return None, "missing frontmatter"
    end = text.find("\n---", 4)
    if end < 0:
        return None, "unterminated frontmatter"
    body = text[4:end]
    data = {}
    for line in body.splitlines():
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            return None, f"frontmatter line without ':' -> {line[:40]!r}"
        key, _, raw = line.partition(":")
        key, raw = key.strip(), raw.strip()
        try:
            data[key] = json.loads(raw)
        except json.JSONDecodeError:
            data[key] = raw
    return data, None


def section_body(text: str, title: str) -> str | None:
    """Body of a section, ending at the next heading of the same or higher level.

    Sub-headings inside the section (### inside ##) belong to the body - a naive
    "#+" stop condition truncates Requirements at its first "### Requirement:".
    """
    head = re.compile(rf"^(#+)\s*{re.escape(title)}", re.M)
    match = head.search(text)
    if not match:
        return None
    level = len(match.group(1))
    rest = text[match.end():]
    stop = re.compile(rf"^#{{1,{level}}}(?!#)\s", re.M)
    end = stop.search(rest)
    return rest[:end.start()] if end else rest


def name_parts(filename: str):
    """(id_part, slug) or (None, None). Accepts 106-…, 012a-…, A12a-…, Q12-…"""
    for pattern in (NAME_NUMBERED, NAME_PREFIXED):
        match = pattern.match(filename)
        if match:
            return match.group(1), match.group(2)
    return None, None


def advisory(problems: list[str], message: str, strict: bool) -> None:
    problems.append(message if strict else WARN + message)


def check_parallel_declaration(meta: dict, problems: list[str], strict: bool) -> None:
    units = meta.get("parallel_units")
    mode = meta.get("parallelism")
    reason = meta.get("parallelism_reason")
    if units is not None and (not isinstance(units, list) or any(not isinstance(u, str) or not u.strip() for u in units)):
        problems.append("parallel_units must be a JSON list of non-empty strings (or omit it)")
        return
    if isinstance(units, list) and len(set(units)) != len(units):
        problems.append("parallel_units entries must be unique")
        return
    if units and mode in (None, "units"):
        return
    if mode == "none":
        if isinstance(reason, str) and reason.strip():
            return
        problems.append('parallelism: "none" needs a non-empty parallelism_reason')
        return
    advisory(
        problems,
        "declare parallelism explicitly: a non-empty parallel_units list, or "
        'parallelism: "none" with a parallelism_reason (an empty or missing list used to '
        "mean single-threaded without anyone deciding it)",
        strict,
    )


def claims_a_revision(text: str) -> bool:
    """True when the order itself claims a revision, ignoring instructing sections."""
    body = text
    for title in INSTRUCTING_SECTIONS:
        section = section_body(body, title)
        if section is not None:
            body = body.replace(section, "")
    return bool(REVISION_MARKER.search(body))


def check_revisions(meta: dict, text: str, problems: list[str], strict: bool) -> None:
    revisions = meta.get("revisions")
    if revisions is not None:
        if not isinstance(revisions, list) or any(not isinstance(r, dict) for r in revisions):
            problems.append('revisions must be a JSON list of objects, e.g. [{"at": "abc1234", "what": "..."}]')
            return
        for index, entry in enumerate(revisions, 1):
            if not str(entry.get("at", "")).strip() or not str(entry.get("what", "")).strip():
                problems.append(f"revisions entry {index} needs both 'at' (sha) and 'what' (one line)")
        return
    if claims_a_revision(text):
        advisory(
            problems,
            "the body mentions a revision but frontmatter carries no `revisions` record "
            '([{"at": <sha>, "what": ..., "after_stage": N, "ruling": R-xxxx}])',
            strict,
        )


def check_batch_report(text: str, problems: list[str], strict: bool) -> None:
    body = section_body(text, "Batch report")
    if body is None:
        advisory(
            problems,
            "batch close needs a `## Batch report` section (gate counts / exit codes / evidence index / remaining gaps)",
            strict,
        )
        return
    for label in ("门", "退出码", "证据", "缺口"):
        if label not in body:
            problems.append(f"Batch report is missing the '{label}' line")
            break


def validate_one(path: Path, strict: bool = False, legacy_ok: bool = False, batch: str | None = None):
    """Problems for one order file. Advisory findings are prefixed with WARN unless strict."""
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")

    number, slug = name_parts(path.name)
    if not number:
        problems.append(
            "file name must be NNN-slug.md, NNNx-slug.md or <PREFIX><N>-slug.md "
            "(e.g. 106-x.md, 012a-x.md, A12a-x.md)"
        )

    meta, err = parse_frontmatter(text)
    if meta is None:
        if not legacy_ok:
            problems.append(
                err + " (legacy order: an order that is touched again must be upgraded to the current "
                "template, or pass --legacy-ok to accept the pre-v2 queue)"
            )
        if batch is not None:
            stages = section_body(text, "Stages") or ""
            unticked = len(re.findall(r"^\s*-\s*\[\s\]", stages, re.M))
            if unticked:
                problems.append(f"batch {batch}: {unticked} stage checkbox(es) still unticked (merge gate)")
        return problems, {"__legacy__": True}

    for key in REQUIRED_KEYS:
        if key not in meta:
            problems.append(f"frontmatter missing key: {key}")
    if number and str(meta.get("id")) not in ("None", number):
        problems.append(f"frontmatter id {meta.get('id')!r} != file id {number!r}")
    if slug and meta.get("slug") not in (None, slug):
        problems.append(f"frontmatter slug {meta.get('slug')!r} != file slug {slug!r}")
    ruling = meta.get("ruling")
    if not isinstance(ruling, str) or not RULING_RE.match(ruling):
        problems.append(f"ruling must be a quoted R-NNNN id, got {ruling!r} (waiving a ruling is not allowed)")
    paths = meta.get("write_paths")
    if not isinstance(paths, list) or not paths:
        problems.append("write_paths must be a non-empty JSON list")
    serial = meta.get("serialize_with")
    if serial is not None and not isinstance(serial, (str, list)):
        problems.append("serialize_with must be an order id or a JSON list of order ids")
    terminal = meta.get("terminal")
    if not isinstance(terminal, list) or not terminal:
        problems.append("terminal must be a non-empty JSON list")
    elif not any(isinstance(t, str) and t.endswith("_DONE") for t in terminal):
        problems.append("terminal must contain a *_DONE entry")

    check_parallel_declaration(meta, problems, strict)
    check_revisions(meta, text, problems, strict)
    if batch is not None:
        check_batch_report(text, problems, strict)

    waived = meta.get("waive") if isinstance(meta.get("waive"), list) else []
    waived_keys = set()
    for entry in waived:
        raw_entry = str(entry)
        entry_name, sep, reason = raw_entry.partition(":")
        if not sep or not reason.strip():
            problems.append(f"waive entry {raw_entry!r} must be '<section>: <reason>' with a non-empty reason")
        key = entry_name.strip()
        if key and key not in REQUIRED_SECTIONS:
            problems.append(f"waive entry names an unknown section: {key!r}")
        waived_keys.add(key)
    for title in REQUIRED_SECTIONS:
        if section_body(text, title) is None and title not in waived_keys:
            problems.append(f"missing section: {title} (or waive it with a reason)")

    requirements = section_body(text, "Requirements")
    if requirements is not None:
        if "### Requirement:" not in requirements:
            problems.append("Requirements needs at least one '### Requirement:'")
        for index, block in enumerate(re.split(r"^###\s+Requirement:", requirements, flags=re.M)[1:], 1):
            if "#### Scenario:" not in block:
                problems.append(f"Requirement {index} has no '#### Scenario:' of its own")
        scenarios = re.findall(r"####\s+Scenario:.*?(?=####\s+Scenario:|\Z)", requirements, re.S)
        if not scenarios:
            problems.append("Requirements needs at least one '#### Scenario:'")
        for index, scenario in enumerate(scenarios, 1):
            if "**WHEN**" not in scenario or "**THEN**" not in scenario:
                problems.append(f"scenario {index} must carry both **WHEN** and **THEN**")

    stages = section_body(text, "Stages")
    if stages is not None:
        boxes = re.findall(r"^\s*-\s*\[( |x|X)\]", stages, re.M)
        if not boxes:
            problems.append("Stages needs at least one '- [ ]' or '- [x]' checkbox")
        if batch is not None:
            unticked = len(re.findall(r"^\s*-\s*\[\s\]", stages, re.M))
            if unticked:
                problems.append(f"batch {batch}: {unticked} stage checkbox(es) still unticked (merge gate)")

    gates = section_body(text, "Gates")
    if gates is not None:
        rows = [r for r in gates.splitlines() if r.strip().startswith("|")]
        if len(rows) < 3:
            problems.append("Gates needs a table with a header and at least one data row")
        else:
            header, _, *data = rows
            if not re.search(r"反例|counter", header, re.I):
                problems.append("Gates table needs a counter-example column")
            if not re.search(r"缺席|absent", header, re.I):
                problems.append("Gates table needs an absent-behaviour column")
            header_cells = [c.strip() for c in header.strip().strip("|").split("|")]
            if len(header_cells) < 4:
                problems.append("Gates table needs at least four columns: gate / assertion / counter-example / absent")
            for i, raw in enumerate(data, 1):
                if set(raw.strip()) <= set("|-: "):
                    continue  # separator row
                cells = [c.strip() for c in raw.strip().strip("|").split("|")]
                if len(cells) < len(header_cells):
                    problems.append(
                        f"Gates row {i} has {len(cells)} cells but the header declares {len(header_cells)}"
                        " — a short row is a defect, not something to skip"
                    )
                    continue
                if not cells[-2] or not cells[-1]:
                    problems.append(f"Gates row {i} leaves the counter-example or absent cell empty")

    if strict:
        validation = section_body(text, "Validation")
        if validation is not None and "```" not in validation:
            problems.append("strict: Validation needs a fenced code block with runnable commands")

    return problems, meta


def _path_prefix(value: str) -> str:
    return value.rstrip("*").rstrip("/")


def overlapping_paths(paths_a, paths_b) -> set[str]:
    if not isinstance(paths_a, list) or not isinstance(paths_b, list):
        return set()
    out = set()
    for a in paths_a:
        if not isinstance(a, str) or not a.strip():
            continue
        pa = _path_prefix(a)
        for b in paths_b:
            if not isinstance(b, str) or not b.strip():
                continue
            pb = _path_prefix(b)
            if pa == pb or pa.startswith(pb + "/") or pb.startswith(pa + "/"):
                out.add(a)
    return out


def _declares_serialization(meta: dict, other_id: str) -> bool:
    serial = meta.get("serialize_with")
    if isinstance(serial, str):
        return serial.strip() == other_id
    if isinstance(serial, list):
        return any(isinstance(s, str) and s.strip() == other_id for s in serial)
    return False


QUEUE_DECLARATION = "queue.json"


def _glob_matches(pattern: str, path: str) -> bool:
    """Match one declared shared-path pattern against one overlapping write path.

    `**` crosses directory separators, `*` and `?` do not, and the match is anchored:
    a declared pattern has to cover the whole overlapping path, so a broader overlap
    than the queue declared stays uncovered (and therefore visible).
    """
    regex = ""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern[index : index + 2] == "**":
                regex += ".*"
                index += 2
                continue
            regex += "[^/]*"
        elif char == "?":
            regex += "[^/]"
        else:
            regex += re.escape(char)
        index += 1
    return re.fullmatch(regex, path) is not None


def load_queue_declaration(orders_root: Path) -> tuple[dict | None, list[str]]:
    """Read the optional ``queue.json`` sitting next to a queue's orders.

    Absent file = no declaration, and the overlap check behaves exactly as before.
    A present but malformed declaration is a hard problem in every mode: the one
    thing a declaration must never do is weaken a guard by being unreadable.
    """
    path = orders_root / QUEUE_DECLARATION
    if not path.exists():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [
            f"{QUEUE_DECLARATION}: unreadable or not valid JSON ({exc}) — a declaration that cannot be "
            "read must fail rather than silently exempting overlaps"
        ]
    if not isinstance(data, dict):
        return None, [f"{QUEUE_DECLARATION}: the top level must be an object"]
    if data.get("single_executor") is not True:
        return None, [
            f'{QUEUE_DECLARATION}: `"single_executor": true` is the only declaration that changes the '
            f'overlap check; found {data.get("single_executor")!r}'
        ]
    shared = data.get("shared_paths")
    if not isinstance(shared, list) or not shared or not all(isinstance(s, str) and s.strip() for s in shared):
        return None, [
            f"{QUEUE_DECLARATION}: shared_paths must be a non-empty list of path patterns — without it the "
            "declaration would exempt every path, not just the shared bookkeeping ones"
        ]
    return data, []


def cross_checks(
    entries: list[tuple[Path, dict]], strict: bool, declaration: dict | None = None
) -> tuple[dict[str, list[str]], list[str]]:
    """Directory-level checks: id collisions, depends_on resolution, write_paths overlap.

    Returns `(problems, notes)`. Notes never make the run fail: they are how a
    single-executor queue keeps unexpected sharing visible after the noise from its
    own bookkeeping paths has been exempted.
    """
    problems: dict[str, list[str]] = {}
    notes: list[str] = []

    def add(path: Path, message: str) -> None:
        problems.setdefault(str(path), []).append(message if strict else WARN + message)

    live = [(path, meta) for path, meta in entries if not meta.get("__legacy__")]
    by_id: dict[str, list[Path]] = {}
    for path, meta in live:
        by_id.setdefault(str(meta.get("id")), []).append(path)
    for order_id, paths in by_id.items():
        if len(paths) > 1:
            for path in paths:
                others = ", ".join(str(p.name) for p in paths if p != path)
                add(path, f"duplicate order id {order_id} inside the validated set (also in {others})")

    known = set(by_id)
    for path, meta in live:
        deps = meta.get("depends_on")
        if deps is None:
            continue
        if not isinstance(deps, list):
            problems.setdefault(str(path), []).append("depends_on must be a JSON list")
            continue
        for entry in deps:
            if isinstance(entry, dict):
                target = str(entry.get("order", "")).strip()
                condition = str(entry.get("condition", "")).strip()
            else:
                target, condition = str(entry).strip(), ""
            if not target:
                problems.setdefault(str(path), []).append("depends_on entry without an order id")
                continue
            if target in known:
                continue
            if SHA_RE.search(condition) or EXTERNAL_RE.search(condition):
                continue
            add(
                path,
                f"depends_on {target!r} resolves neither to an order in this set nor to a pinned "
                "external condition (name the tree, tag or sha in `condition`)",
            )

    single_executor = bool(declaration) and declaration.get("single_executor") is True
    shared_patterns = [str(p) for p in declaration.get("shared_paths", [])] if single_executor else []
    exempted = 0
    for index, (path_a, meta_a) in enumerate(live):
        for path_b, meta_b in live[index + 1:]:
            shared = overlapping_paths(meta_a.get("write_paths"), meta_b.get("write_paths"))
            if not shared:
                continue
            id_a, id_b = str(meta_a.get("id")), str(meta_b.get("id"))
            if _declares_serialization(meta_a, id_b) or _declares_serialization(meta_b, id_a):
                continue
            if single_executor:
                unexplained = sorted(
                    path
                    for path in shared
                    if not any(_glob_matches(pattern, path) for pattern in shared_patterns)
                )
                if unexplained:
                    notes.append(
                        f"NOTE: {id_a} and {id_b} both declare {', '.join(unexplained)}, which "
                        f"{QUEUE_DECLARATION} does not list as shared — one executor runs this queue strictly "
                        "serially so this is not a failure, but unexpected sharing is worth a second look"
                    )
                else:
                    exempted += 1
                continue
            add(
                path_a,
                f"write_paths overlap with order {id_b} on {', '.join(sorted(shared))}: declare "
                "`serialize_with` on one side (or re-slice) so two lines never edit one file at once",
            )
    if exempted:
        notes.append(
            f"NOTE: `{QUEUE_DECLARATION}` declares this queue single_executor, so {exempted} write_paths overlap(s) "
            "between its own orders were exempted (one executor, orders run serially); cross-queue overlap still fails"
        )
    return problems, notes


def manifest_checks(entries: list[tuple[Path, dict]], manifest_path: Path, strict: bool) -> dict[str, list[str]]:
    problems: dict[str, list[str]] = {}

    def add(key: str, message: str) -> None:
        problems.setdefault(key, []).append(message if strict else WARN + message)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"<manifest>": [f"cannot read manifest {manifest_path}: {exc}"]}
    rows = {}
    for row in manifest.get("orders", []) or []:
        if isinstance(row, dict) and row.get("id") is not None:
            rows[str(row["id"])] = row
    for path, meta in entries:
        if meta.get("__legacy__"):
            continue
        row = rows.get(str(meta.get("id")))
        if row is None:
            continue
        row_batch, order_batch = str(row.get("batch", "")), str(meta.get("batch", ""))
        if row_batch and order_batch and row_batch != order_batch:
            add(str(path), f"manifest says batch {row_batch!r} but the order says {order_batch!r}")
        document = row.get("document")
        if isinstance(document, str) and document:
            candidates = [manifest_path.parent / document, path.parent / Path(document).name]
            if not any(candidate.exists() for candidate in candidates):
                add(str(path), f"manifest document {document!r} exists neither next to the manifest nor next to the orders")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="order file, directory of orders, or directory of a sub-tree docs/implementation")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--batch", metavar="NAME")
    ap.add_argument("--legacy-ok", action="store_true", help="accept the pre-v2 queue (no frontmatter) with the checkbox gate only")
    ap.add_argument("--manifest", metavar="PATH", help="reconcile order rows with a manifest.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.target)
    if not root.exists():
        print(f"no such path: {root}", file=sys.stderr)
        return 2
    if root.is_dir():
        orders_dir = root / "work-orders"
        candidates = sorted(orders_dir.glob("*.md")) if orders_dir.is_dir() else sorted(root.glob("*.md"))
        declaration_dirs = [orders_dir, root] if orders_dir.is_dir() else [root]
    else:
        candidates = [root]
        declaration_dirs = [root]
    if not candidates:
        print(f"no order files under {root}", file=sys.stderr)
        return 2

    report: dict[str, list[str]] = {}
    declaration: dict | None = None
    for candidate_dir in declaration_dirs:
        found, declaration_problems = load_queue_declaration(candidate_dir)
        if declaration_problems:
            report.setdefault(str(candidate_dir / QUEUE_DECLARATION), []).extend(declaration_problems)
            break
        if found is not None:
            declaration = found
            break
    entries: list[tuple[Path, dict]] = []
    for path in candidates:
        problems, meta = validate_one(path, args.strict, args.legacy_ok, args.batch)
        if args.batch and not meta.get("__legacy__") and str(meta.get("batch", "")) != args.batch:
            continue
        report[str(path)] = problems
        entries.append((path, meta))

    if args.batch and not report:
        print(f"batch {args.batch}: no orders found", file=sys.stderr)
        return 1

    cross_problems, notes = cross_checks(entries, args.strict, declaration)
    for key, problems in cross_problems.items():
        report.setdefault(key, []).extend(problems)
    if args.manifest:
        for key, problems in manifest_checks(entries, Path(args.manifest), args.strict).items():
            report.setdefault(key, []).extend(problems)

    fatal = False
    for problems in report.values():
        hard = problems if args.strict else [p for p in problems if not p.startswith(WARN)]
        fatal = fatal or bool(hard)

    if args.json:
        print(json.dumps({"batch": args.batch, "orders": report, "notes": notes, "ok": not fatal}, ensure_ascii=False, indent=2))
    else:
        for path, problems in report.items():
            if not problems:
                print(f"OK   {path}")
                continue
            hard = problems if args.strict else [p for p in problems if not p.startswith(WARN)]
            print(f"{'FAIL' if hard else 'WARN'} {path}")
            for problem in problems:
                print(f"     - {problem}")
        for note in notes:
            print(note)
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
