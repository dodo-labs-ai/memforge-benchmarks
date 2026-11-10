"""Build the pilot's report from results/ alone, so anyone can rebuild it after an audit."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from .common import CONCURRENCY, GROUPS, RESULTS_DIR, TOKEN_CAP, load_tasks
from .parse import read_jsonl

OUTCOMES = ("old", "new", "neither")
FORMAL_RUNS_PER_GROUP = 60


def _table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def outcome_table(runs: list[dict]) -> str:
    rows = []
    for group in GROUPS:
        counts = Counter(run["outcome"] for run in runs if run["group"] == group)
        total = sum(counts.values())
        rows.append([group, *[counts[outcome] for outcome in OUTCOMES], total])
    return _table(["Group", "old", "new", "neither", "runs"], rows)


def task_table(runs: list[dict]) -> str:
    rows = []
    for task in load_tasks():
        row = [task]
        for group in GROUPS:
            counts = Counter(run["outcome"] for run in runs if run["task"] == task and run["group"] == group)
            row.append("/".join(str(counts[outcome]) for outcome in OUTCOMES) if counts else "-")
        rows.append(row)
    return _table(["Task (old/new/neither)", *GROUPS], rows)


def leakage(runs: list[dict]) -> str:
    rows = []
    for task in load_tasks():
        cell = [run for run in runs if run["task"] == task and run["group"] == "A"]
        counts = Counter(run["outcome"] for run in cell)
        details = "; ".join(sorted({run["assertion_detail"][:110] for run in cell}))
        rows.append([task, counts["new"], counts["old"], counts["neither"], details])
    return _table(["Task", "A passes (new)", "A old", "A neither", "What the assertion saw"], rows)


def behaviour_table(runs: list[dict]) -> str:
    rows = []
    for group in GROUPS:
        cell = [run for run in runs if run["group"] == group]
        if not cell:
            continue
        rows.append(
            [
                group,
                len(cell),
                sum(run["read_current_doc"] for run in cell),
                sum(run["read_stale_doc"] for run in cell),
                sum(run["checked_file_times"] for run in cell),
                sum(run["called_memory_tool"] for run in cell),
                sum(run["saw_current_memory"] for run in cell),
                sum(run["saw_stale_memory"] for run in cell),
                sum(run["saw_relation_notice"] for run in cell),
                sum(run["saw_relation_notice_for_task"] for run in cell),
            ]
        )
    return _table(
        ["Group", "runs", "read current doc", "read stale doc", "looked at file times", "called memory tool", "saw current memory", "saw stale memory", "saw any relation notice", "saw this task's notice"],
        rows,
    )


def per_run_table(runs: list[dict]) -> str:
    rows = []
    for run in sorted(runs, key=lambda item: (item["task"], item["group"], item["rep"])):
        tokens = run["tokens"]
        rows.append(
            [
                run["key"], run["status"], run["outcome"], tokens["input"], tokens["cached_input"], tokens["output"],
                run["duration_seconds"], run["turns"], "yes" if run["read_current_doc"] else "no", "yes" if run["read_stale_doc"] else "no",
                ",".join(f"{name}x{count}" for name, count in run["memory_tools"].items()) or "-",
                "yes" if run["saw_relation_notice_for_task"] else ("other" if run["saw_relation_notice"] else "no"),
            ]
        )
    return _table(["Run", "status", "outcome", "input", "cached input", "output", "seconds", "turns", "read current", "read stale", "memory tools", "notice"], rows)


def spend_table(runs: list[dict]) -> str:
    rows = []
    for group in GROUPS:
        cell = [run for run in runs if run["group"] == group]
        if not cell:
            continue
        totals = [run["tokens"]["total"] for run in cell]
        seconds = [run["duration_seconds"] for run in cell]
        rows.append(
            [
                group, len(cell), round(mean(run["tokens"]["input"] for run in cell)), round(mean(run["tokens"]["cached_input"] for run in cell)),
                round(mean(run["tokens"]["output"] for run in cell)), round(mean(totals)), min(totals), max(totals),
                round(mean(seconds), 1), round(median(seconds), 1), round(max(seconds), 1),
            ]
        )
    return _table(["Group", "runs", "mean input", "mean cached input", "mean output", "mean total", "min total", "max total", "mean s", "median s", "max s"], rows)


def projection(runs: list[dict]) -> str:
    """Per-group means times 60 runs per group: 20 tasks x 3 runs. A straight scale-up, not a forecast."""
    lines = []
    total_tokens = cached = output = input_tokens = serial_seconds = 0
    peak_tokens = 0
    for group in GROUPS:
        cell = [run for run in runs if run["group"] == group]
        if not cell:
            lines.append(f"Group {group} has no runs, so the projection leaves it out.")
            continue
        total_tokens += mean(run["tokens"]["total"] for run in cell) * FORMAL_RUNS_PER_GROUP
        input_tokens += mean(run["tokens"]["input"] for run in cell) * FORMAL_RUNS_PER_GROUP
        cached += mean(run["tokens"]["cached_input"] for run in cell) * FORMAL_RUNS_PER_GROUP
        output += mean(run["tokens"]["output"] for run in cell) * FORMAL_RUNS_PER_GROUP
        serial_seconds += mean(run["duration_seconds"] for run in cell) * FORMAL_RUNS_PER_GROUP
        peak_tokens += max(run["tokens"]["total"] for run in cell) * FORMAL_RUNS_PER_GROUP
    lines.append(
        f"240 runs at the pilot's per-group means: {total_tokens / 1e6:.1f} million tokens "
        f"({input_tokens / 1e6:.1f} million input, of which {cached / 1e6:.1f} million cached, and {output / 1e6:.2f} million output). "
        f"With every run at its group's largest pilot value: {peak_tokens / 1e6:.1f} million."
    )
    group_seconds = {group: mean(run["duration_seconds"] for run in runs if run["group"] == group) * FORMAL_RUNS_PER_GROUP for group in GROUPS if any(run["group"] == group for run in runs)}
    harness_shape = sum(value for group, value in group_seconds.items() if group != "D") / CONCURRENCY + group_seconds.get("D", 0)
    lines.append(
        f"Agent time: {serial_seconds / 3600:.1f} hours one at a time, {serial_seconds / 3600 / CONCURRENCY:.1f} hours if every group ran at concurrency {CONCURRENCY}, "
        f"{harness_shape / 3600:.1f} hours as this harness runs them, with group D one at a time."
    )
    lines.append(
        "This scales the pilot and is not a forecast. Group D's searches returned the whole ten-memory corpus; twenty tasks will change the size of what a search returns. Sync and relation discovery for 40 documents are not included."
    )
    return "\n\n".join(lines)


def memforge_section(results: Path) -> str:
    state_path = results / "sandbox_state.json"
    if not state_path.exists():
        return "No sandbox snapshot recorded."
    state = json.loads(state_path.read_text(encoding="utf-8"))
    rows = []
    for task, entry in state["by_task"].items():
        rows.append(
            [
                task,
                f"{len(entry['stale']['memories'])} / {len(entry['current']['memories'])}",
                "yes" if entry["stale_and_current_linked"] else "no",
                ", ".join(entry["labels_between_stale_and_current"]) or "-",
                f"{entry['stale']['document_time_memforge_saw']} / {entry['current']['document_time_memforge_saw']}",
            ]
        )
    usage = "; ".join(
        f"{model}: {entry['calls']} calls, {entry['prompt_tokens']} prompt and {entry['completion_tokens']} completion tokens"
        for model, entry in state["model_usage"].items()
    )
    return (
        _table(["Task", "memories (stale / current)", "linked", "label", "document times (stale / current)"], rows)
        + f"\n\nSandbox commit `{state['memforge_commit']}`. Generation {state['models']['generation']['model_id']} through an OpenAI-compatible endpoint; "
        + f"embedding {state['models']['embedding']['model_id']} through {state['models']['embedding']['provider']}. Relation work: {state['relation_work']}. Model usage logged by MemForge: {usage}."
    )


def isolation_section(runs: list[dict], attempts: list[dict], results: Path) -> str:
    lines = []
    violations = [(run["key"], run["isolation"]["violations"]) for run in attempts if run["isolation"]["violations"]]
    lines.append(f"Runs with an isolation violation: {len(violations)}. {violations if violations else ''}".strip())
    outside = [(run["key"], item.get("command") or item.get("output_excerpt")) for run in attempts for item in run["isolation"]["commands_touching_paths_outside_run"]]
    lines.append(f"Commands or outputs naming a path outside the run's own directory: {len(outside)}.")
    lines += [f"- {key}: `{text[:120]}`" for key, text in outside[:10]]
    issued = sum(run["isolation"]["commands_issued"] for run in attempts)
    refusals = Counter(line for run in attempts for line in run["isolation"]["sandbox_refusals"])
    absent = sum(len(run["isolation"]["commands_absent_from_event_stream"]) for run in attempts)
    lines.append(f"Commands issued, from the session records: {issued}. Absent from the JSON event stream: {absent}. Refused by the sandbox: {sum(refusals.values())}.")
    lines += [f"- {count} x `{line}`" for line, count in refusals.most_common(8)]
    for group in GROUPS:
        checks = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((results / "isolation").glob(f"batch_{group}*.json"))]
        if checks:
            lines.append(
                f"Group {group}, {len(checks)} batch(es): {sum(len(check['requests_reaching_sandbox']) for check in checks)} requests reached the sandbox through its port during them; "
                f"memories and links unchanged in every batch: {all(check['memories_and_links_unchanged'] for check in checks)}."
            )
    matched = [run for run in runs if run["group"] == "D"]
    if matched:
        lines.append(
            f"Group D: {sum(run.get('api_requests_match_tool_calls', False) for run in matched)} of {len(matched)} runs have sandbox requests covering every memory tool call that succeeded."
        )
    return "\n\n".join(lines)


def build(results: Path) -> str:
    runs = read_jsonl(results / "runs.jsonl")
    attempts = read_jsonl(results / "attempts.jsonl")
    probes = read_jsonl(results / "probes.jsonl")
    usage_path = results / "isolation" / "memforge_usage.json"
    memforge_tokens = json.loads(usage_path.read_text())["total_tokens"] if usage_path.exists() else 0
    statuses = Counter(run["status"] for run in attempts)
    retries = sum(1 for run in attempts if run.get("retried"))
    cap_used = sum(run["tokens"]["cap_count"] for run in attempts) + sum(row.get("cap_count", 0) for row in probes) + memforge_tokens
    agent_totals = Counter()
    for run in attempts:
        for key in ("input", "cached_input", "output", "total"):
            agent_totals[key] += run["tokens"][key]
    stop_path = results / "STOP.json"
    sections = [
        "# Stale document pilot\n\n**Pilot. These numbers test the harness; they are not findings.** Three synthetic tasks, three runs per group per task, one model, one coding agent. Nothing here supports a claim about agents or tools in general.",
        f"Runs with a result: {len(runs)} of 36. Attempts: {len(attempts)}, by status {dict(statuses)}. Retries used: {retries}." + (f"\n\nStopped early: {stop_path.read_text().strip()}" if stop_path.exists() else ""),
        "## Group by outcome\n\n" + outcome_table(runs),
        "## By task\n\n" + task_table(runs),
        "## Leakage: group A, no documents\n\nA pass here means the right answer did not need the documents.\n\n" + leakage(runs),
        "## What the agent looked at\n\n" + behaviour_table(runs),
        "## What MemForge made of the documents\n\n" + memforge_section(results),
        "## Isolation\n\n" + isolation_section(runs, attempts, results),
        "## Tokens and time\n\n"
        + f"Agent across all attempts, as measured: {agent_totals['input']} input (of which {agent_totals['cached_input']} cached) and {agent_totals['output']} output. "
        + f"Harness probes: {sum(row.get('input', 0) + row.get('output', 0) for row in probes)}. MemForge's own model calls: {memforge_tokens}. "
        + f"Counter against the {TOKEN_CAP} cap, which adds input, cached input and output as reported: {cap_used}.\n\n"
        + spend_table(runs),
        "## Projection for 240 runs\n\n" + projection(runs) if runs else "",
        "## Every run\n\n" + per_run_table(runs),
    ]
    return "\n\n".join(section for section in sections if section) + "\n"


def main(argv: list[str]) -> int:
    results = Path(argv[0]).resolve() if argv else RESULTS_DIR
    (results / "REPORT.md").write_text(build(results), encoding="utf-8")
    print(results / "REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
