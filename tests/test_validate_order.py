"""Per-rule regression tests for scripts/validate_order.py.

Every rule the validator claims gets its own counter-example here: a synthetic order that violates
exactly that rule and must be rejected. A rule without a counter-example is a rule we have not proven.

Run:  python3 -m unittest discover -s tests -v     (or)  python3 tests/test_validate_order.py
No dependencies beyond the standard library.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate_order.py"

_spec = importlib.util.spec_from_file_location("validate_order", VALIDATOR)
vo = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(vo)

BASE = """---
id: 001
slug: probe
batch: b1
baseline: "aaaa111"
depends_on: []
write_paths: ["src/**"]
forbidden: ["release/**"]
ruling: R-0001
terminal: ["PROBE_DONE", "PROBE_PARTIAL"]
waive: []
parallelism: "none"
parallelism_reason: "单文件串行，拆不开"
---

## Objective
做一件事。

## Current state
`src/x.py:1` 实测如此。

## Scope
| From | To | Reason |
| --- | --- | --- |
| `src/x.py` | `src/y.py` | 归属 |

## Requirements
### Requirement: 新路径可用
#### Scenario: 可以导入
**WHEN** 执行导入
**THEN** 退出码 0

## Stages
- [ ] 1. 记录 baseline（提交）
- [x] 2. 完成迁移（提交）

## Gates
| Gate | Assertion | Counter-example (required) | Absent / unknown ⇒ |
| --- | --- | --- | --- |
| G1 | 引用为 0 | 加回一处导入必须失败 | fail (typed) |

## Validation
```bash
pytest -q
```

## DoD
1..6

## Acceptance
- PROBE_DONE

## Batch report
- 门：G1 1/1 绿；退出码：0
- 证据：docs/evidence/probe.json
- 缺口：无
"""


def check(name: str, text: str, strict: bool = True):
    """Write an order under a matching file name and return its problems."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_text(text, encoding="utf-8")
        problems, _ = vo.validate_one(path, strict)
    return problems


def must_mention(problems, needle: str):
    return any(needle in p for p in problems), problems


class OrderRules(unittest.TestCase):
    def test_baseline_is_accepted(self):
        self.assertEqual(check("001-probe.md", BASE), [])

    # --- filename and identity -------------------------------------------------
    def test_filename_must_be_numbered_and_kebab(self):
        problems = check("probe.md", BASE)
        self.assertTrue(must_mention(problems, "file name must be")[0], problems)

    def test_id_and_slug_must_match_the_filename(self):
        text = BASE.replace("id: 001", "id: 002").replace("slug: probe", "slug: other")
        problems = check("001-probe.md", text)
        self.assertTrue(must_mention(problems, "!=")[0], problems)

    # --- ruling ----------------------------------------------------------------
    def test_ruling_must_be_quoted_id_not_int(self):
        problems = check("001-probe.md", BASE.replace("ruling: R-0001", "ruling: 123"))
        self.assertTrue(must_mention(problems, "quoted R-NNNN")[0], problems)

    def test_ruling_must_follow_the_pattern(self):
        problems = check("001-probe.md", BASE.replace("ruling: R-0001", 'ruling: "R-12"'))
        self.assertTrue(must_mention(problems, "quoted R-NNNN")[0], problems)

    # --- frontmatter lists -----------------------------------------------------
    def test_write_paths_must_be_a_non_empty_list(self):
        problems = check("001-probe.md", BASE.replace('write_paths: ["src/**"]', "write_paths: []"))
        self.assertTrue(must_mention(problems, "write_paths")[0], problems)

    def test_terminal_must_contain_a_done_state(self):
        problems = check("001-probe.md", BASE.replace('terminal: ["PROBE_DONE", "PROBE_PARTIAL"]', 'terminal: ["PROBE_PARTIAL"]'))
        self.assertTrue(must_mention(problems, "*_DONE")[0], problems)

    def test_parallel_units_must_be_a_list_of_strings(self):
        problems = check("001-probe.md", BASE.replace('parallelism: "none"', 'parallel_units: ["unit-a", 7]'))
        self.assertTrue(must_mention(problems, "parallel_units")[0], problems)

    def test_parallel_units_must_be_unique(self):
        problems = check("001-probe.md", BASE.replace('parallelism: "none"', 'parallel_units: ["unit-a", "unit-a"]'))
        self.assertTrue(must_mention(problems, "must be unique")[0], problems)

    def test_parallel_units_non_empty_is_accepted(self):
        text = BASE.replace('parallelism: "none"\nparallelism_reason: "单文件串行，拆不开"', 'parallel_units: ["unit-a"]')
        self.assertEqual(check("001-probe.md", text), [])

    # --- declaration checks (2026-09-19: silent single-threading was the defect) ---
    def test_missing_parallel_declaration_is_refused_under_strict(self):
        text = BASE.replace('parallelism: "none"\nparallelism_reason: "单文件串行，拆不开"\n', "")
        problems = check("001-probe.md", text)
        self.assertTrue(must_mention(problems, "declare parallelism explicitly")[0], problems)

    def test_empty_parallel_units_without_declaration_is_refused_under_strict(self):
        text = BASE.replace('parallelism: "none"\nparallelism_reason: "单文件串行，拆不开"', "parallel_units: []")
        problems = check("001-probe.md", text)
        self.assertTrue(must_mention(problems, "declare parallelism explicitly")[0], problems)

    def test_parallelism_none_without_reason_is_refused(self):
        problems = check("001-probe.md", BASE.replace('parallelism_reason: "单文件串行，拆不开"', "parallelism_reason: \"\""))
        self.assertTrue(must_mention(problems, "non-empty parallelism_reason")[0], problems)

    def test_advisory_tier_keeps_a_live_queue_workable(self):
        """Outside --strict the same order only warns (exit 0), so a running queue is not blocked."""
        text = BASE.replace('parallelism: "none"\nparallelism_reason: "单文件串行，拆不开"\n', "")
        problems = check("001-probe.md", text, strict=False)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("WARN: "), problems)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "001-probe.md"
            path.write_text(text, encoding="utf-8")
            result = subprocess.run([sys.executable, str(VALIDATOR), str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN", result.stdout)

    def test_revision_mention_without_records_is_refused_under_strict(self):
        text = BASE.replace("## Objective\n做一件事。", "## Objective\n做一件事。修订 v2：改了做法。")
        problems = check("001-probe.md", text)
        self.assertTrue(must_mention(problems, "no `revisions` record")[0], problems)

    def test_instructing_note_about_revisions_is_not_a_claim(self):
        """A template telling the executor what to record must not trip the check."""
        text = BASE.replace("## Acceptance", "## Notes for the executor\n- 纳入修订后在本树 status 记 `已纳入 work order <NNN> 修订 @<sha>`。\n\n## Acceptance")
        self.assertEqual(check("001-probe.md", text), [])

    def test_revisions_records_are_accepted(self):
        text = BASE.replace('waive: []', 'waive: []\nrevisions: [{"at": "abc1234", "what": "改为按家并行", "after_stage": 2, "ruling": "R-0021"}]')
        text = text.replace("## Objective\n做一件事。", "## Objective\n做一件事。修订 v2：改了做法。")
        self.assertEqual(check("001-probe.md", text), [])

    def test_revision_entry_without_sha_is_refused(self):
        text = BASE.replace('waive: []', 'waive: []\nrevisions: [{"what": "改了做法"}]')
        problems = check("001-probe.md", text)
        self.assertTrue(must_mention(problems, "needs both 'at'")[0], problems)

    # --- file naming: split siblings and line prefixes -------------------------
    def test_split_sibling_name_is_accepted(self):
        text = BASE.replace("id: 001", "id: 012a").replace("slug: probe", "slug: thinking-on")
        self.assertEqual(check("012a-thinking-on.md", text), [])

    def test_line_prefixed_name_is_accepted(self):
        text = BASE.replace("id: 001", "id: A12a").replace("slug: probe", "slug: harness-prefix")
        self.assertEqual(check("A12a-harness-prefix.md", text), [])

    def test_legacy_order_without_frontmatter_needs_the_flag(self):
        legacy = "# Work order 37\n\n做一件事。\n"
        self.assertTrue(must_mention(check("037-old.md", legacy), "legacy order")[0])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "037-old.md"
            path.write_text(legacy, encoding="utf-8")
            problems, _ = vo.validate_one(path, True, True)
        self.assertEqual(problems, [])

    # --- sections and waivers --------------------------------------------------
    def test_missing_section_is_a_problem(self):
        problems = check("001-probe.md", BASE.replace("## Gates\n", "## NotGates\n"))
        self.assertTrue(must_mention(problems, "missing section: Gates")[0], problems)

    def test_waive_entry_must_carry_a_reason(self):
        text = BASE.replace("waive: []", 'waive: ["Gates"]').replace("## Gates\n", "## NotGates\n")
        problems = check("001-probe.md", text)
        self.assertTrue(must_mention(problems, "non-empty reason")[0], problems)

    def test_waive_with_reason_is_accepted(self):
        text = BASE.replace("waive: []", 'waive: ["Gates: 复用主树已有门"]').replace("## Gates\n", "## NotGates\n")
        self.assertEqual(check("001-probe.md", text), [])

    def test_waive_may_not_name_an_unknown_section(self):
        problems = check("001-probe.md", BASE.replace("waive: []", 'waive: ["Gates: x", "Nonsense: y"]'))
        self.assertTrue(must_mention(problems, "unknown section")[0], problems)

    # --- requirements and scenarios -------------------------------------------
    def test_each_requirement_needs_its_own_scenario(self):
        text = BASE.replace(
            "### Requirement: 新路径可用\n#### Scenario: 可以导入\n**WHEN** 执行导入\n**THEN** 退出码 0",
            "### Requirement: 新路径可用\n#### Scenario: 可以导入\n**WHEN** 执行导入\n**THEN** 退出码 0\n\n"
            "### Requirement: 旧路径消失\n**WHEN** 查找旧文件\n**THEN** 不存在",
        )
        problems = check("001-probe.md", text)
        self.assertTrue(must_mention(problems, "has no '#### Scenario:' of its own")[0], problems)

    def test_scenario_needs_when_and_then(self):
        problems = check("001-probe.md", BASE.replace("**THEN** 退出码 0", "结果应当正常"))
        self.assertTrue(must_mention(problems, "must carry both")[0], problems)

    # --- gates -----------------------------------------------------------------
    def test_gate_row_with_empty_counter_or_absent_is_rejected(self):
        problems = check("001-probe.md", BASE.replace("| G1 | 引用为 0 | 加回一处导入必须失败 | fail (typed) |", "| G1 | 引用为 0 | | |"))
        self.assertTrue(must_mention(problems, "leaves the counter-example or absent cell empty")[0], problems)

    def test_short_gate_row_is_a_defect_not_skipped(self):
        problems = check("001-probe.md", BASE.replace("| G1 | 引用为 0 | 加回一处导入必须失败 | fail (typed) |", "| G1 | 引用为 0 |"))
        self.assertTrue(must_mention(problems, "short row is a defect")[0], problems)

    def test_header_must_declare_four_columns(self):
        problems = check("001-probe.md", BASE.replace(
            "| Gate | Assertion | Counter-example (required) | Absent / unknown ⇒ |\n| --- | --- | --- | --- |\n| G1 | 引用为 0 | 加回一处导入必须失败 | fail (typed) |",
            "| Gate | Assertion | Note |\n| --- | --- | --- |\n| G1 | 引用为 0 | n/a |",
        ))
        self.assertTrue(must_mention(problems, "at least four columns")[0], problems)

    # --- strict mode -----------------------------------------------------------
    def test_strict_requires_a_runnable_validation_block(self):
        problems = check("001-probe.md", BASE.replace("```bash\npytest -q\n```", "跑一下测试"))
        self.assertTrue(must_mention(problems, "fenced code block")[0], problems)


class BatchGate(unittest.TestCase):
    """The merge gate: every stage box of every order in the batch must be ticked."""

    def run_batch(self, text: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "001-probe.md"
            path.write_text(text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATOR), str(path), "--batch", "b1", "--strict"],
                capture_output=True, text=True,
            )

    def test_unticked_batch_is_refused(self):
        result = self.run_batch(BASE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unticked", result.stdout)

    def test_ticked_batch_is_accepted(self):
        result = self.run_batch(BASE.replace("- [ ]", "- [x]"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_batch_close_needs_a_batch_report(self):
        text = BASE.replace("- [ ]", "- [x]")
        head, _, _ = text.partition("## Batch report")
        result = self.run_batch(head)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Batch report", result.stdout)


class CrossChecks(unittest.TestCase):
    """Directory-level rules: id collisions, depends_on resolution, write_paths overlap."""

    def run_dir(self, orders: dict[str, str], *extra: str):
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in orders.items():
                (Path(tmp) / name).write_text(text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATOR), tmp, "--strict", *extra],
                capture_output=True, text=True,
            )

    def second(self, write_paths: str = '["other/**"]'):
        return (
            BASE.replace("id: 001", "id: 002")
            .replace("slug: probe", "slug: other")
            .replace('write_paths: ["src/**"]', f"write_paths: {write_paths}")
            .replace("batch: b1", "batch: b2")
        )

    def test_duplicate_ids_in_one_directory_are_refused(self):
        text = BASE.replace("slug: probe", "slug: probe-two")
        result = self.run_dir({"001-probe.md": BASE, "001-probe-two.md": text})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate order id", result.stdout)

    def test_overlapping_write_paths_without_serialize_with_are_refused(self):
        result = self.run_dir({"001-probe.md": BASE, "002-other.md": self.second('["src/parser/**"]')})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declare `serialize_with`", result.stdout)

    def test_serialize_with_clears_the_overlap(self):
        other = self.second('["src/parser/**"]').replace("waive: []", 'waive: []\nserialize_with: ["001"]')
        result = self.run_dir({"001-probe.md": BASE, "002-other.md": other})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_non_overlapping_write_paths_pass(self):
        result = self.run_dir({"001-probe.md": BASE, "002-other.md": self.second()})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unresolvable_depends_on_is_refused(self):
        other = self.second().replace("depends_on: []", 'depends_on: [{"order": "099", "condition": "等它落地"}]')
        result = self.run_dir({"001-probe.md": BASE, "002-other.md": other})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("resolves neither", result.stdout)

    def test_depends_on_a_named_tree_is_accepted(self):
        other = self.second().replace(
            "depends_on: []",
            'depends_on: [{"order": "105", "condition": "in the backend tree, merged as abc1234"}]',
        )
        result = self.run_dir({"001-probe.md": BASE, "002-other.md": other})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class QueueDeclaration(unittest.TestCase):
    """The optional queue.json: an overlap between two orders of one single-executor
    queue must not fail, and a declaration that cannot be read must never silently
    weaken the overlap check (that would be a false green in the guard itself)."""

    def run_dir(self, files: dict[str, str], *extra: str):
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in files.items():
                (Path(tmp) / name).write_text(text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATOR), tmp, *extra],
                capture_output=True, text=True,
            )

    def overlapping_pair(self, second_paths: str) -> tuple[str, str]:
        base = BASE.replace(
            'write_paths: ["src/**"]', 'write_paths: ["src/**", "docs/implementation/status.md"]'
        )
        # the second order overlaps the first only through the shared bookkeeping path
        other = (
            BASE.replace("id: 001", "id: 002")
            .replace("slug: probe", "slug: other")
            .replace("batch: b1", "batch: b2")
            .replace('write_paths: ["src/**"]', f"write_paths: {second_paths}")
        )
        return base, other

    def test_shared_bookkeeping_overlap_is_exempted(self):
        base, other = self.overlapping_pair('["other/**", "docs/implementation/status.md"]')
        declaration = json.dumps({"single_executor": True, "shared_paths": ["docs/implementation/status.md"]})
        result = self.run_dir({"001-probe.md": base, "002-other.md": other, "queue.json": declaration}, "--strict")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("exempted", result.stdout)
        self.assertNotIn("declare `serialize_with`", result.stdout)

    def test_unexpected_sharing_is_named_but_does_not_fail(self):
        base, other = self.overlapping_pair('["src/parser/**"]')
        declaration = json.dumps({"single_executor": True, "shared_paths": ["docs/implementation/status.md"]})
        result = self.run_dir({"001-probe.md": base, "002-other.md": other, "queue.json": declaration}, "--strict")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NOTE:", result.stdout)
        self.assertIn("src/**", result.stdout)

    def test_without_the_declaration_the_old_rule_still_applies(self):
        base, other = self.overlapping_pair('["other/**", "docs/implementation/status.md"]')
        result = self.run_dir({"001-probe.md": base, "002-other.md": other}, "--strict")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("declare `serialize_with`", result.stdout)

    def test_a_declaration_that_cannot_be_read_never_weakens_the_check(self):
        base, other = self.overlapping_pair('["other/**", "docs/implementation/status.md"]')
        cases = {
            "not json": "{oops",
            "not an object": "[]",
            "missing single_executor": json.dumps({"shared_paths": ["src/**"]}),
            "missing shared_paths": json.dumps({"single_executor": True}),
            "single_executor false": json.dumps({"single_executor": False, "shared_paths": ["src/**"]}),
        }
        for label, declaration in cases.items():
            with self.subTest(label=label):
                # no --strict on purpose: an unreadable declaration must fail in every mode
                result = self.run_dir({"001-probe.md": base, "002-other.md": other, "queue.json": declaration})
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("queue.json", result.stdout)
