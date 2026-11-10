"""Runs of the experiment's groups: A, N, B, B-t, C1, C2 and D.

    python3 -m formal.harness.trials run --tasks ID,ID --groups B,C1,C2,D --size small --reps 1 --results formal/stage1/pilot
    python3 -m formal.harness.trials report --results formal/stage1/pilot

One run at a time, in a shuffled order, on the run path of the closed-book screen. A holds no
documents. N holds the folder without the old revision of its own task, which shows whether
the new revision alone can produce the new outcome. B holds the documents under `docs/`, B-t the same with real file times, C1 and C2 add a docs index that
reaches the agent as AGENTS.md, and D holds no documents and reads them through the MemForge
plugin from the API at EXPERIMENT_API_PORT, which must already hold the same folder. A run with
a line in runs.jsonl is skipped, and a recorded STOP.json blocks further runs until --clear-stop.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from harness import home as pilot_home
from harness import parse, sandbox, scan
from harness.common import API_URL, WORK_ROOT, load_secrets
from harness.pilot import Ledger

from ..common import FORMAL, load_tasks
from ..corpus import coexist, docs_index, real_times
from . import screen
from .screen import Setup

GROUP_ISOLATION = {"A": "A", "N": "B", "B": "B", "B-t": "B", "C1": "C", "C2": "C", "D": "D"}
INDEX_POINTS_TO = {"C1": "new", "C2": "old"}
ORDER_SEED = 20261109
DEFAULT_TOKEN_CAP = 2_500_000
ARGUMENT_CHARACTERS = 400


@dataclass(frozen=True)
class TrialSpec:
    task: str
    group: str
    size: str
    rep: int

    @property
    def key(self) -> str:
        return f"{self.task}/{self.group}/{self.size}/{self.rep}"

    @property
    def stem(self) -> str:
        return f"{self.task}__{self.group}__{self.size}__{self.rep}"


def arrangements_of(set_name: str) -> dict[str, int]:
    return {task["id"]: coexist.arrangement_of(task["id"]) for task in coexist.tasks_of(set_name)}


def stage_for(spec: TrialSpec, task: dict):
    """What places the group's documents and index in a run's repository. Groups A and D hold neither."""
    if spec.group in ("A", "D"):
        return None
    set_name = task["doc_set"]

    def stage(repo: Path) -> None:
        arrangements = arrangements_of(set_name)
        times = real_times.times_of(set_name, coexist.layout(set_name, spec.size, arrangements)) if spec.group == "B-t" else None
        docs = repo / "docs"
        placed = coexist.materialize(docs, set_name, spec.size, arrangements, times=times)
        if spec.group == "N":
            (docs / coexist.names_for(task, arrangements[spec.task])["old"]).unlink()
        if spec.group in INDEX_POINTS_TO:
            leak_tokens = [token for task in coexist.tasks_of(set_name) for token in task["leak_tokens"]]
            index = repo / "AGENTS.md"
            index.write_text(docs_index.build(docs, placed, spec.task, INDEX_POINTS_TO[spec.group], leak_tokens), encoding="utf-8")
            stamp = datetime.fromisoformat(coexist.UNIFORM_TIME).timestamp()
            os.utime(index, (stamp, stamp))

    return stage


def _appears(text: str, phrase: str) -> bool:
    """Whether a phrase is in recorded text, which holds it at up to two levels of JSON escaping."""
    once = json.dumps(phrase, ensure_ascii=False)[1:-1]
    return any(form in text for form in (phrase, once, json.dumps(once, ensure_ascii=False)[1:-1]))


def annotate_for(spec: TrialSpec, task: dict):
    """What a run read: the revisions' names and marker sentences, and any memory calls."""
    names = coexist.names_for(task, coexist.arrangement_of(spec.task))

    def annotate(events: dict, rollouts: list[Path], raw_rollouts: str) -> dict:
        commands = " ".join(parse.parse_tool_activity(rollouts)["commands"])
        calls = events["mcp_calls"]
        return {
            "size": spec.size,
            "revision_named_in_a_command": {role: names[role] in commands for role in names},
            "revision_text_seen": {role: _appears(raw_rollouts, task["markers"][role]) for role in names},
            "memory_calls": [{"tool": call.get("tool"), "status": call.get("status"), "arguments": json.dumps(call.get("arguments"), ensure_ascii=False)[:ARGUMENT_CHARACTERS]} for call in calls],
            "relation_notice_seen": any("relation_notice" in json.dumps(call.get("result"), ensure_ascii=False) for call in calls),
            "codex_warnings": [warning[:300] for warning in events["warnings"]],
        }

    return annotate


def setup_for(spec: TrialSpec, task: dict) -> Setup:
    return Setup(isolation=GROUP_ISOLATION[spec.group], stage=stage_for(spec, task), annotate=annotate_for(spec, task))


def all_specs(tasks: Iterable[str], groups: Iterable[str], size: str, reps: int) -> list[TrialSpec]:
    specs = [TrialSpec(task, group, size, rep) for task in tasks for group in groups for rep in range(1, reps + 1)]
    random.Random(ORDER_SEED).shuffle(specs)
    return specs


def run_specs(specs: list[TrialSpec], tasks: dict[str, dict], results: Path, endpoint: str, api_key: str, scrubber: scan.Scrubber, *, token_cap: int, report=screen.log) -> int:
    ledger = Ledger(results)
    done = {row["key"] for row in screen.latest_runs(results)}
    pending = [spec for spec in specs if spec.key not in done]
    status = {"done": len(specs) - len(pending), "total": len(specs), "current": set()}
    for spec in pending:
        if ledger.stop_reason is None:
            task = tasks[spec.task]
            screen._run_one(spec, task, endpoint, api_key, ledger, scrubber, screen.MAX_RETRIES, status, report, setup=setup_for(spec, task), spent=ledger.tokens_used, cap=token_cap)
    return 3 if ledger.stop_reason else 0


def memforge_problems(tasks: dict[str, dict], size: str) -> list[str]:
    """Why group D could not run: the plugin template, or an API that does not hold the folder."""
    problems = []
    try:
        pilot_home.check_template()
    except SystemExit as error:
        problems.append(str(error))
    try:
        sources = sandbox.api("GET", "/api/v1/sources").get("data", [])
    except OSError as error:
        return [*problems, f"no API at {API_URL}: {error}"]
    held = {source.get("doc_count") for source in sources}
    for set_name in {task["doc_set"] for task in tasks.values()}:
        expected = len(coexist.layout(set_name, size, arrangements_of(set_name)))
        if expected not in held:
            problems.append(f"the API at {API_URL} holds no source of {expected} documents for {set_name} {size}: {sorted(map(str, held))}")
    return problems


def write_report(results: Path) -> dict:
    """Outcomes per task, group and size, and what the runs read."""
    runs = screen.latest_runs(results)
    attempts = parse.read_jsonl(results / "attempts.jsonl")
    cells: dict[str, dict] = {}
    for row in sorted(runs, key=lambda item: item["key"]):
        cell = cells.setdefault(f"{row['task']}/{row['group']}/{row['size']}", {"outcomes": [], "new_text_seen": [], "old_text_seen": [], "memory_calls": [], "total_tokens": [], "duration_seconds": []})
        cell["outcomes"].append(row["outcome"])
        cell["new_text_seen"].append(row["revision_text_seen"]["new"])
        cell["old_text_seen"].append(row["revision_text_seen"]["old"])
        cell["memory_calls"].append(len(row["memory_calls"]))
        cell["total_tokens"].append(row["tokens"]["total"])
        cell["duration_seconds"].append(row["duration_seconds"])
    summary = {
        "cells": cells,
        "attempts": len(attempts),
        "tokens_of_all_attempts": sum(row["tokens"]["total"] for row in attempts),
        "isolation_violations": [item for row in attempts for item in row["isolation"]["violations"]],
        "other_hosts_flagged": sorted({label for row in attempts for label in row["egress"]["other_hosts"]}),
    }
    (results / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def cmd_run(args: argparse.Namespace) -> int:
    results = Path(args.results).resolve()
    ledger = Ledger(results)
    if ledger.stop_file.exists() and not args.clear_stop:
        print(f"refusing to continue: {ledger.stop_file.read_text()}", file=sys.stderr)
        return 3
    ledger.stop_file.unlink(missing_ok=True)
    secrets = load_secrets()
    every_task = load_tasks()
    tasks = {task_id: every_task[task_id] for task_id in args.tasks.split(",")}
    groups = args.groups.split(",")
    problems = screen.preconditions(secrets)
    if "D" in groups:
        problems += memforge_problems(tasks, args.size)
    if problems:
        print("; ".join(problems), file=sys.stderr)
        return 2
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    code = run_specs(all_specs(tasks, groups, args.size, args.reps), tasks, results, secrets["MEMFORGE_RELAY_BASE_URL"].rstrip("/"), secrets["MEMFORGE_RELAY_API_KEY"], scan.Scrubber(secrets), token_cap=args.token_cap)
    print(json.dumps(write_report(results)["cells"], indent=2, ensure_ascii=False))
    return code


def cmd_report(args: argparse.Namespace) -> int:
    print(json.dumps(write_report(Path(args.results).resolve()), indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="formal.harness.trials")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--tasks", required=True, help="comma-separated task ids")
    run.add_argument("--groups", required=True, help=f"comma-separated, from {','.join(GROUP_ISOLATION)}")
    run.add_argument("--size", choices=("small", "large"), required=True)
    run.add_argument("--reps", type=int, default=1)
    run.add_argument("--results", default=str(FORMAL / "stage1" / "pilot"))
    run.add_argument("--token-cap", type=int, default=DEFAULT_TOKEN_CAP)
    run.add_argument("--clear-stop", action="store_true")
    run.set_defaults(handler=cmd_run)
    report = commands.add_parser("report")
    report.add_argument("--results", default=str(FORMAL / "stage1" / "pilot"))
    report.set_defaults(handler=cmd_report)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
