"""The analysis fixed in the published plan: the `new` rate and the five comparisons.

    python3 -m formal.harness.analysis run --results DIR [DIR ...] --out DIR
    python3 -m formal.harness.analysis selftest

Each comparison is a signed sum of cells, computed inside each task and then resampled over
tasks. It reads only `runs.jsonl`, and a later directory's run replaces an earlier one's with the
same key. It calls no model and needs no key.
"""

from __future__ import annotations

import argparse
import platform
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from ..common import SCORED_NUMBERS, load_tasks, write_json
from . import screen

SEED = 20261110
RESAMPLES = 10_000
REPETITIONS = 3
OUTCOMES = ("new", "old", "neither", "declined", "failed")
TOKEN_FIELDS = ("total", "uncached_input", "output")
# The new revision of each marks the old key Deprecated, so a run that opens both needs no help.
WEAK_STALENESS_TESTS = ("t18-otel-peer-service", "t22-otel-rpc-status-code")
EXPECTED_CELLS = (
    ("A", "small"),
    ("B", "small"), ("C1", "small"), ("C2", "small"), ("D", "small"),
    ("B", "large"), ("B-t", "large"), ("C1", "large"), ("C2", "large"), ("D", "large"),
)  # fmt: skip

Rows = dict[tuple[str, str, str], list[dict]]


@dataclass(frozen=True)
class Comparison:
    name: str
    measure: str
    terms: tuple[tuple[int, str, str], ...]
    tasks: tuple[str, ...]


def finished(runs: list[dict]) -> list[dict]:
    return [run for run in runs if run["outcome"] != "failed"]


def measure_of(runs: list[dict], measure: str) -> float | None:
    """A cell's value over its finished runs, or None when it has none."""
    done = finished(runs)
    if not done:
        return None
    if measure == "new_rate":
        return sum(run["outcome"] == "new" for run in done) / len(done)
    return sum(run["tokens"][measure] for run in done) / len(done)


def task_difference(rows: Rows, comparison: Comparison, task: str) -> float | None:
    values = [(weight, measure_of(rows.get((task, group, size), []), comparison.measure)) for weight, group, size in comparison.terms]
    if any(value is None for _, value in values):
        return None
    return sum(weight * value for weight, value in values)


def percentile(ordered: list[float], fraction: float) -> float:
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap(values: list[float], label: str) -> tuple[float, float]:
    """The percentile 95% interval of the mean, resampling tasks. The label gives each comparison its own stream."""
    generator = random.Random(f"{SEED}/{label}")
    means = sorted(sum(generator.choices(values, k=len(values))) / len(values) for _ in range(RESAMPLES))
    return percentile(means, 0.025), percentile(means, 0.975)


def evaluate(rows: Rows, comparison: Comparison) -> dict:
    per_task = {task: task_difference(rows, comparison, task) for task in comparison.tasks}
    values = [value for value in per_task.values() if value is not None]
    result = {
        "name": comparison.name,
        "measure": comparison.measure,
        "per_task": per_task,
        "tasks_used": len(values),
        "tasks_left_out": sorted(task for task, value in per_task.items() if value is None),
        "mean_difference": None,
        "interval_95": None,
        "reading": "no task has both sides",
    }
    if values:
        low, high = bootstrap(values, comparison.name)
        result.update({"mean_difference": sum(values) / len(values), "interval_95": [low, high], "reading": "no difference seen" if low <= 0 <= high else "interval excludes 0"})
    return result


def comparisons_for(tasks: tuple[str, ...]) -> list[Comparison]:
    strong = tuple(task for task in tasks if task not in WEAK_STALENESS_TESTS)
    rate_terms = {
        "1_d_vs_b_large": ((1, "D", "large"), (-1, "B", "large")),
        "2_d_vs_c1_large": ((1, "D", "large"), (-1, "C1", "large")),
        "2_d_vs_c2_large": ((1, "D", "large"), (-1, "C2", "large")),
        "3_size_effect": ((1, "D", "large"), (-1, "B", "large"), (-1, "D", "small"), (1, "B", "small")),
    }
    comparisons = [Comparison(name, "new_rate", terms, tasks) for name, terms in rate_terms.items()]
    comparisons += [
        Comparison(f"4_tokens_d_vs_b_{size}_{field}", field, ((1, "D", size), (-1, "B", size)), tasks)
        for size in ("small", "large")
        for field in TOKEN_FIELDS
    ]
    comparisons.append(Comparison("5_bt_vs_b_large", "new_rate", ((1, "B-t", "large"), (-1, "B", "large")), tasks))
    comparisons += [Comparison(f"{name}_without_weak_tasks", "new_rate", terms, strong) for name, terms in rate_terms.items()]
    return comparisons


def describe_cell(runs: list[dict], group: str) -> dict:
    done = finished(runs)
    cell = {
        "outcomes": {outcome: sum(run["outcome"] == outcome for run in runs) for outcome in OUTCOMES},
        "finished_runs": len(done),
        "new_rate": measure_of(runs, "new_rate"),
        "mean_tokens": {field: measure_of(runs, field) for field in TOKEN_FIELDS},
        "mean_seconds": sum(run["duration_seconds"] for run in done) / len(done) if done else None,
    }
    if group == "D":
        cell["runs_calling_memory_tools"] = sum(bool(run["memory_calls"]) for run in done)
        cell["runs_shown_a_relation_notice"] = sum(bool(run["relation_notice_seen"]) for run in done)
    return cell


def load_rows(directories: list[Path], tasks: tuple[str, ...]) -> Rows:
    latest = {run["key"]: run for directory in directories for run in screen.latest_runs(directory)}
    cells = set(EXPECTED_CELLS)
    rows: Rows = {}
    for run in latest.values():
        if run["task"] in tasks and (run["group"], run["size"]) in cells:
            rows.setdefault((run["task"], run["group"], run["size"]), []).append(run)
    return rows


def scored_tasks() -> tuple[str, ...]:
    return tuple(sorted(task for task, spec in load_tasks().items() if spec["number"] in SCORED_NUMBERS))


def analyse(rows: Rows, tasks: tuple[str, ...]) -> dict:
    cells = {f"{task}/{group}/{size}": describe_cell(rows.get((task, group, size), []), group) for task in tasks for group, size in EXPECTED_CELLS}
    incomplete = sorted(name for name, cell in cells.items() if cell["finished_runs"] < REPETITIONS)
    return {
        "seed": SEED,
        "resamples": RESAMPLES,
        "python": platform.python_version(),
        "tasks": list(tasks),
        "cells_expected": len(cells),
        "cells_with_fewer_than_three_finished_runs": incomplete,
        "comparisons": [evaluate(rows, comparison) for comparison in comparisons_for(tasks)],
        "cells": cells,
    }


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}" if abs(value) < 100 else f"{value:,.0f}"


def render(report: dict) -> str:
    lines = ["# Analysis", "", f"Tasks: {len(report['tasks'])}. Cells below three finished runs: {len(report['cells_with_fewer_than_three_finished_runs'])} of {report['cells_expected']}.", ""]
    lines += ["| Comparison | Tasks | Mean difference | 95% interval | Reading | Left out |", "|---|---|---|---|---|---|"]
    for item in report["comparisons"]:
        interval = "n/a" if item["interval_95"] is None else f"{_number(item['interval_95'][0])} to {_number(item['interval_95'][1])}"
        lines.append(f"| {item['name']} | {item['tasks_used']} | {_number(item['mean_difference'])} | {interval} | {item['reading']} | {', '.join(task.split('-')[0] for task in item['tasks_left_out']) or 'none'} |")
    lines += ["", "| Cell | new | old | neither | declined | failed | Mean total tokens |", "|---|---|---|---|---|---|---|"]
    for name, cell in report["cells"].items():
        counts = cell["outcomes"]
        lines.append(f"| {name} | {counts['new']} | {counts['old']} | {counts['neither']} | {counts['declined']} | {counts['failed']} | {_number(cell['mean_tokens']['total'])} |")
    return "\n".join(lines) + "\n"


def _run(task: str, group: str, size: str, outcome: str, total: int = 100) -> dict:
    return {"task": task, "group": group, "size": size, "outcome": outcome, "tokens": {"total": total, "uncached_input": total // 2, "output": 10}, "duration_seconds": 10.0, "memory_calls": [], "relation_notice_seen": False}


def selftest() -> int:
    tasks = tuple(f"t{number}" for number in range(8))
    rows: Rows = {}
    for task in tasks:
        rows[(task, "D", "large")] = [_run(task, "D", "large", "new", 300)] * 3
        rows[(task, "B", "large")] = [_run(task, "B", "large", "new", 100), *[_run(task, "B", "large", "old", 100)] * 2]
        rows[(task, "D", "small")] = [_run(task, "D", "small", "old")] * 3
        rows[(task, "B", "small")] = [_run(task, "B", "small", "old")] * 3
    rows[("t0", "B", "large")] = [_run("t0", "B", "large", "new"), _run("t0", "B", "large", "declined"), _run("t0", "B", "large", "failed")]
    del rows[("t1", "D", "large")]
    by_name = {item["name"]: item for item in analyse(rows, tasks)["comparisons"]}
    first = by_name["1_d_vs_b_large"]
    size_effect = by_name["3_size_effect"]
    no_change = evaluate({("t", "D", "large"): [_run("t", "D", "large", "old")], ("t", "B", "large"): [_run("t", "B", "large", "old")]}, Comparison("c", "new_rate", ((1, "D", "large"), (-1, "B", "large")), ("t",)))
    mixed = [0.0, 1.0] * 4
    checks = {
        "failed is outside the rate and declined is inside it": abs(first["per_task"]["t0"] - 0.5) < 1e-9,
        "a task with an empty cell is left out and named": first["tasks_left_out"] == ["t1"] and first["tasks_used"] == 7,
        "a mean over tasks": abs(first["mean_difference"] - (0.5 + 6 * 2 / 3) / 7) < 1e-9,
        "the interval excludes 0 for an all-positive difference": first["reading"] == "interval excludes 0",
        "the size effect is a difference of differences": abs(size_effect["per_task"]["t2"] - 2 / 3) < 1e-9,
        "the token measure uses token counts": by_name["4_tokens_d_vs_b_large_total"]["per_task"]["t2"] == 200,
        "the same label gives the same interval": bootstrap(mixed, "x") == bootstrap(mixed, "x"),
        "no change reads as no difference seen": no_change["reading"] == "no difference seen",
        "percentiles interpolate": percentile([0.0, 1.0, 2.0], 0.25) == 0.5,
    }
    for name, passed in checks.items():
        print(("ok    " if passed else "FAIL  ") + name)
    return 0 if all(checks.values()) else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="formal.harness.analysis")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--results", nargs="+", required=True, type=Path)
    run.add_argument("--out", required=True, type=Path)
    commands.add_parser("selftest")
    args = parser.parse_args(argv)
    if args.command == "selftest":
        return selftest()
    tasks = scored_tasks()
    report = analyse(load_rows(args.results, tasks), tasks)
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "analysis.json", report)
    (args.out / "analysis.md").write_text(render(report), encoding="utf-8")
    print(render(report).split("\n\n")[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
