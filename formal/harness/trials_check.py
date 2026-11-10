"""Prove the document groups' run path through Codex itself, with a loopback stand-in for the model.

    python3 -m formal.harness.trials_check [--with-plugin]

No request leaves the machine and the key is a dummy. For each group the stand-in reports what
the run's repository holds, then writes a task's `new` fixture, and the check reads the outcome,
the isolation findings and the first prompt. `--with-plugin` adds group D, which needs a MemForge
API that holds the large GOV.UK folder at EXPERIMENT_API_PORT.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from harness import scan
from harness.common import WORK_ROOT, load_secrets

from ..common import load_tasks
from ..corpus import coexist
from . import trials
from .harness_check import DUMMY_KEY, _fixture_command
from .mock_model import MockModel

TASK = "t01-govuk-db-admin-role"
REPORT_COMMAND = (
    'echo DOCS=$(test -d docs && find docs -type f | wc -l | tr -d " "); '
    'echo FILE_TIMES=$(test -d docs && find docs -type f -exec stat -f %m {} + | sort -u | wc -l | tr -d " "); '
    'echo DIRECTORY_TIMES=$(find . -path ./.git -prune -o -type d -exec stat -f %m {} + | sort -u | wc -l | tr -d " "); '
    'echo INDEX_LINES=$(test -f AGENTS.md && wc -l < AGENTS.md | tr -d " ")\n'
)


def _output_of(mock: MockModel) -> str:
    output = ""
    for item in mock.requests[-1].get("input", []):
        if item.get("type") in ("custom_tool_call_output", "function_call_output"):
            value = item.get("output")
            output += value if isinstance(value, str) else "\n".join(part.get("text", "") for part in value)
    return output.replace("\\n", "\n")


def _value(output: str, name: str) -> str | None:
    found = re.search(rf"\b{name}=(\S*)", output)
    return found.group(1) if found else None


def check_group(group: str, size: str, secrets: dict) -> dict:
    tasks = {TASK: load_tasks()[TASK]}
    names = coexist.names_for(tasks[TASK], coexist.arrangement_of(TASK))
    command = REPORT_COMMAND + f'echo OLD_FILE=$(test -f docs/{names["old"]} && echo present || echo absent)\n' + _fixture_command(TASK, "new")
    # A plugin run also makes one memory search, the call an agent would make.
    script = f"await tools.mcp__memforge__search({{query: 'database admin secret'}}); text(JSON.stringify(await tools.exec_command({{cmd: {json.dumps(command)}, max_output_tokens: 4000}})));" if group == "D" else None
    mock = MockModel(command, script=script)
    with tempfile.TemporaryDirectory() as raw:
        results = Path(raw) / "results"
        try:
            code = trials.run_specs(trials.all_specs(tasks, [group], size, 1), tasks, results, mock.base_url, DUMMY_KEY, scan.Scrubber(secrets), token_cap=5_000_000, report=print)
            first_prompt = json.dumps(mock.requests[0].get("input", []), ensure_ascii=False) if mock.requests else ""
            output = _output_of(mock) if mock.requests else ""
        finally:
            mock.close()
        rows = [json.loads(line) for line in (results / "attempts.jsonl").read_text().splitlines()] if (results / "attempts.jsonl").exists() else []
    row = rows[-1] if rows else {}
    return {
        "exit_code": code,
        "status": row.get("status"),
        "outcome": row.get("outcome"),
        "violations": (row.get("isolation") or {}).get("violations"),
        "documents": _value(output, "DOCS"),
        "old_file": _value(output, "OLD_FILE"),
        "file_times": _value(output, "FILE_TIMES"),
        "directory_times": _value(output, "DIRECTORY_TIMES"),
        "index_lines": _value(output, "INDEX_LINES"),
        "index_reaches_first_prompt": "# Docs index" in first_prompt,
        "index_names_new": names["new"] in first_prompt,
        "index_names_old": names["old"] in first_prompt,
        "plugin_guidance_in_first_prompt": "MemForge Usage Guidance" in first_prompt,
        "memory_tools_offered": "mcp__memforge" in first_prompt,
        "plugin_feature_traces": (row.get("isolation") or {}).get("plugin_tree_unchanged"),
        "other_hosts": (row.get("egress") or {}).get("other_hosts"),
        "memory_calls": [call["status"] for call in row.get("memory_calls", [])],
        "codex_warnings": row.get("codex_warnings"),
    }


def expected(group: str, row: dict) -> list[str]:
    wanted = {"status": "completed", "outcome": "new", "violations": [], "file_times": "1", "directory_times": "1", "documents": "30", "index_reaches_first_prompt": group in ("C1", "C2"), "plugin_guidance_in_first_prompt": group == "D"}
    if group == "C1":
        wanted.update({"index_names_new": True, "index_names_old": False})
    if group == "C2":
        wanted.update({"index_names_new": False, "index_names_old": True})
    if group == "B-t":
        del wanted["file_times"]
        wanted["documents"] = str(len(coexist.layout("govuk", "large", trials.arrangements_of("govuk"))))
    if group == "N":
        wanted.update({"documents": "29", "old_file": "absent"})
    if group == "A":
        wanted.update({"documents": "", "file_times": ""})
    if group == "D":
        wanted.update({"documents": "", "file_times": "", "memory_tools_offered": True, "plugin_feature_traces": True, "memory_calls": ["completed"]})
    problems = [f"{group}: {key} is {row.get(key)!r}, wanted {value!r}" for key, value in wanted.items() if row.get(key) != value]
    if group == "B-t" and int(row.get("file_times") or 0) < 2:
        problems.append(f"B-t: file_times is {row.get('file_times')!r}, wanted real times")
    return problems


def main(argv: list[str]) -> int:
    secrets = load_secrets()
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    report = {group: check_group(group, "small", secrets) for group in ("A", "N", "B", "C1", "C2")}
    report["B-t"] = check_group("B-t", "large", secrets)
    if "--with-plugin" in argv:
        report["D"] = check_group("D", "large", secrets)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    problems = [problem for group, row in report.items() for problem in expected(group, row)]
    print("trials check " + ("ok" if not problems else f"FAILED: {problems}"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
