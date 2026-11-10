"""Prove the stage 0 settings through Codex itself, with a loopback stand-in for the model.

    python3 -m formal.harness.harness_check

No request leaves the machine and the key is a dummy. Each check drives `codex exec` as a
real run does and reads what happened from Codex's request bodies and session records:

- the default effort for the model, with and without the pin;
- what a shell command sees: git, python, python3, the time zone and any xcrun noise,
  against the same command under the pilot's settings;
- what a run's profile refuses, allows and blocks, through `codex sandbox`;
- web search absent from the tools the model is offered;
- how much of a long AGENTS.md reaches the first prompt;
- the whole run path on one task, from a fixture written by the stand-in through to the
  recorded outcome and a replay of the recorded diff.

The env file is read only for the values the scrubber must remove.
"""

from __future__ import annotations

import getpass
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from harness import home as pilot_home
from harness import scan
from harness.common import CODEX_BIN, RUN_PATH as PILOT_RUN_PATH, WORK_ROOT, load_secrets
from harness.pilot import COMMON_OVERRIDES

from ..common import MODEL, REAL_GIT_DIR, REASONING_EFFORT, REPO, STAGE0, TASKS_DIR, TIMEZONE, load_tasks
from . import home as run_home
from . import screen
from .mock_model import MockModel

DUMMY_KEY = "loopback-only-not-a-key"
# Python comes first because under the pilot's settings each git call took over seven
# seconds, and the stand-in closes the turn when the first output comes back.
SHELL_REPORT = (
    "echo PATH=$PATH; echo TZ=$TZ; echo DATEZONE=$(date +%Z); echo PYTHON=$(command -v python); python --version; "
    "echo PYTHON3=$(command -v python3); python3 --version; "
    "python -c 'import sys; print(\"PYREAL=\" + sys.base_prefix)'; python3 -c 'import sys; print(\"PY3REAL=\" + sys.base_prefix)'; "
    "cat <<'HEREDOC_END'\nHEREDOC=works\nHEREDOC_END\necho JAVA_HOME_SET=${JAVA_HOME:+yes}; "
    "echo GIT=$(command -v git); git --version; git status --short; git log --oneline -1; git diff --stat; true"
)


def _bundled_default() -> str | None:
    with tempfile.TemporaryDirectory() as raw:
        env = {"PATH": run_home.RUN_PATH, "HOME": raw, "CODEX_HOME": raw}
        output = subprocess.run([CODEX_BIN, "debug", "models", "--bundled"], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
    catalog = json.loads(output)
    for model in catalog.get("models", catalog):
        if model.get("slug") == MODEL:
            return model.get("default_reasoning_level")
    return None


def _prompt_facts(text: str) -> dict:
    """What a group A run's first prompt holds that it should not."""
    return {
        "names_the_developer_home": str(Path.home()) in text,
        "names_the_developer_account": getpass.getuser() in text,
        "names_memforge": "memforge" in text.lower(),
        "holds_a_docs_index": "# Docs index" in text,
        "offers_memory_tools": "search_memory" in text or "mcp__memforge" in text,
    }


def _run(command: str, *, pinned: bool, pilot_settings: bool = False, task: str = "t16-rustforge-rollup-approval") -> dict:
    """One `codex exec` against the stand-in, which runs `command` once."""
    mock = MockModel(command)
    dirs = run_home.new_run_dirs()
    try:
        if pilot_settings:
            pilot_home.prepare_home(dirs, "A")
            run_home.prepare_repo(dirs, task)
            env = {"PATH": PILOT_RUN_PATH, "HOME": str(dirs.home), "CODEX_HOME": str(dirs.codex_home), "TMPDIR": str(dirs.tmp), "MEMFORGE_RELAY_API_KEY": DUMMY_KEY}
            argv = [CODEX_BIN, "exec", "--json", "-m", MODEL, "-C", str(dirs.repo), "--strict-config"]
            for override in (*COMMON_OVERRIDES, f'model_providers.relay.base_url="{mock.base_url}"'):
                argv += ["-c", override]
            argv.append("probe")
        else:
            run_home.prepare_home(dirs, "A")
            run_home.prepare_repo(dirs, task)
            env = run_home.run_env(dirs, DUMMY_KEY)
            argv = screen.codex_argv(dirs.repo, "probe", mock.base_url, pinned=pinned)
        process = subprocess.run(argv, cwd=dirs.repo, env=env, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
        rollouts = sorted(dirs.codex_home.glob("sessions/**/*.jsonl"))
        # The model's view of the command: what the tool returned, not the event stream.
        output = ""
        for item in (mock.requests[-1] if mock.requests else {}).get("input", []):
            if item.get("type") in ("custom_tool_call_output", "function_call_output"):
                value = item.get("output")
                text = value if isinstance(value, str) else "\n".join(part.get("text", "") for part in value)
                output += text.replace("\\n", "\n")
        first = mock.requests[0] if mock.requests else {}
        return {
            "exit_code": process.returncode,
            "effort_in_request": (first.get("reasoning") or {}).get("effort"),
            "effort_in_session": screen.effort_of(rollouts),
            "timezone_in_prompt": screen.timezone_of(rollouts),
            "tools_offered": json.dumps([item for item in first.get("input", []) if item.get("type") == "additional_tools"]),
            "prompt_facts": _prompt_facts(json.dumps(first.get("input", []))),
            "normalized_prompt": re.sub(r'"id": "[a-z]+_[0-9a-f-]+"', '"id": "x"', json.dumps(first.get("input", [])).replace(dirs.root.name, "run")),
            "background_plugin_sync_traces": sorted(path.name for path in (dirs.codex_home / ".tmp").iterdir()) if (dirs.codex_home / ".tmp").is_dir() else [],
            "request_paths": sorted(set(mock.paths)),
            "output": output.replace(str(dirs.root), "<run>"),
        }
    finally:
        mock.close()
        run_home.kill_leftovers(dirs)
        shutil.rmtree(dirs.root, ignore_errors=True)


def _facts(output: str) -> dict:
    def value(name: str) -> str | None:
        found = re.search(rf"^{name}=(.*)$", output, flags=re.MULTILINE)
        return found.group(1) if found else None

    return {
        "git": value("GIT"),
        "git_version_line": next((line for line in output.splitlines() if line.startswith("git version")), None),
        "python": value("PYTHON"),
        "python3": value("PYTHON3"),
        "python_versions": re.findall(r"^Python (\S+)$", output, flags=re.MULTILINE),
        "python_and_python3_same_interpreter": value("PYREAL") is not None and value("PYREAL") == value("PY3REAL"),
        "tz": value("TZ"),
        "here_documents_work": value("HEREDOC") == "works",
        "machine_java_home_visible": value("JAVA_HOME_SET") == "yes",
        "wall_time": (re.search(r"Wall time:? ([0-9.]+) seconds", output) or [None, None])[1],
        "xcrun_noise_lines": len(re.findall(r"xcrun|xcodebuild\[|DVTDeveloperPaths", output)),
        "operation_not_permitted_lines": len(re.findall(r"[Oo]peration not permitted", output)),
    }


def _agents_md_limit() -> dict:
    """How much of a long AGENTS.md reaches the first prompt, as the plan's index decision needs."""
    rows = {}
    for size in (30_000, 40_000):
        mock = MockModel("true")
        dirs = run_home.new_run_dirs()
        try:
            run_home.prepare_home(dirs, "A")
            run_home.prepare_repo(dirs, "t16-rustforge-rollup-approval")
            lines = [f"INDEXLINE{number:05d} padding padding padding" for number in range(size // 40 + 1)]
            text = "\n".join(lines)[:size]
            (dirs.repo / "AGENTS.md").write_text(text, encoding="utf-8")
            subprocess.run(screen.codex_argv(dirs.repo, "probe", mock.base_url), cwd=dirs.repo, env=run_home.run_env(dirs, DUMMY_KEY), capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
            prompt = json.dumps(mock.requests[0].get("input", [])) if mock.requests else ""
            seen = re.findall(r"INDEXLINE(\d{5})", prompt)
            written = re.findall(r"INDEXLINE(\d{5})", text)
            rows[str(size)] = {
                "lines_written": len(written),
                "lines_in_first_prompt": len(set(seen)),
                "last_line_written": written[-1],
                "last_line_in_first_prompt": max(seen) if seen else None,
                "reached_the_prompt_whole": bool(seen) and max(seen) == written[-1],
            }
        finally:
            mock.close()
            run_home.kill_leftovers(dirs)
            shutil.rmtree(dirs.root, ignore_errors=True)
    return rows


def _sandbox_probe() -> dict:
    """What a run's own profile reaches, under `codex sandbox`."""
    dirs = run_home.new_run_dirs()
    try:
        run_home.prepare_home(dirs, "A")
        run_home.prepare_repo(dirs, "t16-rustforge-rollup-approval")
        env = run_home.run_env(dirs, None)
        home = Path.home()
        refused = {
            "developer_codex_config": f"test -r {home}/.codex/config.toml && head -c 1 {home}/.codex/config.toml",
            "developer_home": f"ls {home}",
            "this_repository": f"ls {REPO}",
            "fetched_documents": f"ls {REPO}/formal/corpus/fetched",
            "work_root": f"ls {WORK_ROOT}",
            "shared_tmp": "ls /private/tmp",
            "var_tmp": "ls /private/var/tmp",
            "outside_write": f"touch {WORK_ROOT}/x-{dirs.root.name}",
            "home_write": f"touch {dirs.home}/x",
        }
        allowed = {
            "repo_write": "touch probe.txt && rm probe.txt",
            "tmp_write": f"touch {dirs.tmp}/x",
            "git_status": "git status --short",
            "python": "python -c 'print(1)'",
            "python3": "python3 -c 'print(1)'",
            "grep_repo": "grep -rl rollup .",
        }
        network = {
            "public_internet": "curl -s -m 5 -o /dev/null https://example.com",
            "loopback": "curl -s -m 5 -o /dev/null http://127.0.0.1:9/",
        }

        def attempt(script: str) -> bool:
            result = subprocess.run(
                [CODEX_BIN, "sandbox", "-P", "iso", "-C", str(dirs.repo), "--", "/bin/zsh", "-lc", script],
                env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
            )
            return result.returncode == 0

        return {
            "refused": {name: not attempt(script) for name, script in refused.items()},
            "allowed": {name: attempt(script) for name, script in allowed.items()},
            "network_blocked": {name: not attempt(script) for name, script in network.items()},
        }
    finally:
        shutil.rmtree(dirs.root, ignore_errors=True)


def _fixture_command(task_id: str, fixture: str) -> str:
    """A shell command that writes a fixture into the workspace, as a run's edits would."""
    root = TASKS_DIR / task_id / "fixtures" / fixture
    parts = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        parts.append(f"mkdir -p \"$(dirname '{relative}')\" && cat > '{relative}' <<'FIXTURE_END'\n{path.read_text(encoding='utf-8')}FIXTURE_END")
    return "\n".join(parts) if parts else "true"


def _full_path(secrets: dict) -> dict:
    """Every run path from prompt to replay, on each outcome of one task."""
    task_id = "t16-rustforge-rollup-approval"
    tasks = {task_id: load_tasks()[task_id]}
    rows = {}
    for fixture in ("new", "old", "neither", "declined"):
        with tempfile.TemporaryDirectory() as raw:
            results = Path(raw) / "results"
            mock = MockModel(_fixture_command(task_id, fixture))
            try:
                code = screen.run_all(tasks, results, mock.base_url, DUMMY_KEY, scan.Scrubber(secrets), report=print, concurrency=3)
            finally:
                mock.close()
            records = [json.loads(line) for line in (results / "runs.jsonl").read_text().splitlines()] if (results / "runs.jsonl").exists() else []
            summary = screen.write_report(results)
            audit = subprocess.run([sys.executable, "-m", "formal.harness.screen", "audit", "--results", str(results)], cwd=REPO, capture_output=True, text=True)
            rows[fixture] = {
                "exit_code": code,
                "outcomes": [row["outcome"] for row in records],
                "statuses": [row["status"] for row in records],
                "efforts": sorted({str(row["reasoning_effort"]) for row in records}),
                "xcrun_noise_lines": sum(row["xcrun_noise_lines"] for row in records),
                "violations": [item for row in records for item in row["isolation"]["violations"]],
                "screen_result": summary["per_task"][task_id]["screen_result"],
                "egress_polls": [row["egress"]["polls"] for row in records],
                "egress_other_hosts": sorted({label for row in records for label in row["egress"]["other_hosts"]}),
                "audit": audit.stdout.strip().splitlines()[-1] if audit.stdout.strip() else audit.stderr[-200:],
            }
    return rows


def _unfinished_runs(secrets: dict) -> dict:
    """A run cut off by the time limit is `failed`, whatever its workspace shows, is rerun once and leaves the rates."""
    task_id = "t16-rustforge-rollup-approval"
    tasks = {task_id: load_tasks()[task_id]}
    rows = {}
    limit, pause = screen.RUN_TIMEOUT_SECONDS, screen.RETRY_PAUSE_SECONDS
    screen.RUN_TIMEOUT_SECONDS, screen.RETRY_PAUSE_SECONDS = 6, 0
    try:
        for name, command in (("workspace_untouched", "sleep 60"), ("workspace_already_new", f"{_fixture_command(task_id, 'new')}\nsleep 60")):
            with tempfile.TemporaryDirectory() as raw:
                results = Path(raw) / "results"
                mock = MockModel(command)
                try:
                    screen.run_all(tasks, results, mock.base_url, DUMMY_KEY, scan.Scrubber(secrets), report=print, concurrency=3)
                finally:
                    mock.close()
                summary = screen.write_report(results)["per_task"][task_id]
                attempts = [json.loads(line) for line in (results / "attempts.jsonl").read_text().splitlines()]
                rows[name] = {
                    "attempts": len(attempts),
                    "statuses": sorted({row["status"] for row in attempts}),
                    "outcomes": sorted({row["outcome"] for row in attempts}),
                    "workspace_outcomes": sorted({row["workspace_outcome"] for row in attempts}),
                    "failed": summary["failed"],
                    "new": summary["new"],
                    "declined": summary["declined"],
                    "new_rate": summary["new_rate"],
                    "screen_result": summary["screen_result"],
                }
    finally:
        screen.RUN_TIMEOUT_SECONDS, screen.RETRY_PAUSE_SECONDS = limit, pause
    return rows


def main() -> int:
    secrets = load_secrets()
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    default = _bundled_default()
    unpinned = _run(SHELL_REPORT, pinned=False)
    pinned = _run(SHELL_REPORT, pinned=True)
    pilot = _run(SHELL_REPORT, pinned=False, pilot_settings=True)
    report = {
        "stand_in_for_the_model": "loopback only; no model call was made",
        "reasoning_effort": {
            "bundled_catalog_default_for_model": default,
            "in_a_request_without_the_pin": unpinned["effort_in_request"],
            "in_a_request_with_the_pin": pinned["effort_in_request"],
            "in_the_session_record_with_the_pin": pinned["effort_in_session"],
            "pinned_value": REASONING_EFFORT,
        },
        "timezone": {"pinned": TIMEZONE, "told_to_the_model": pinned["timezone_in_prompt"], "told_to_the_model_under_the_pilot_settings": pilot["timezone_in_prompt"]},
        "shell_under_formal_settings": _facts(pinned["output"]),
        "shell_under_pilot_settings": _facts(pilot["output"]),
        "web_search_in_the_tools_offered": "web_search" in pinned["tools_offered"],
        "first_prompt": pinned["prompt_facts"],
        "background_plugin_sync": {
            "traces_with_the_plugin_feature_on": unpinned["background_plugin_sync_traces"],
            "traces_with_it_off": pinned["background_plugin_sync_traces"],
            "first_prompt_unchanged_by_turning_it_off": unpinned["normalized_prompt"] == pinned["normalized_prompt"],
        },
        "requests_reached": pinned["request_paths"],
        "agents_md_reaching_the_prompt_by_size_in_bytes": _agents_md_limit(),
        "permission_profile": _sandbox_probe(),
        "full_run_path_by_fixture": _full_path(secrets),
        "unfinished_runs": _unfinished_runs(secrets),
    }
    scrubbed, _ = scan.Scrubber(secrets).scrub(json.dumps(report, indent=2, ensure_ascii=False))
    (STAGE0 / "harness_check.json").write_text(scrubbed + "\n", encoding="utf-8")
    problems = []
    shell = report["shell_under_formal_settings"]
    effort = report["reasoning_effort"]
    if {effort["bundled_catalog_default_for_model"], effort["in_a_request_without_the_pin"], effort["in_a_request_with_the_pin"], effort["in_the_session_record_with_the_pin"]} != {REASONING_EFFORT}:
        problems.append(f"effort: {effort}")
    if shell["git"] != str(Path(REAL_GIT_DIR) / "git"):
        problems.append(f"git is {shell['git']}")
    if shell["xcrun_noise_lines"] or shell["operation_not_permitted_lines"]:
        problems.append(f"shell noise: {shell}")
    if not shell["python_and_python3_same_interpreter"] or len(set(shell["python_versions"])) != 1:
        problems.append(f"python: {shell}")
    if not shell["here_documents_work"]:
        problems.append("here-documents fail")
    if shell["machine_java_home_visible"]:
        problems.append("the machine's JAVA_HOME reaches the shell")
    if shell["tz"] != TIMEZONE:
        problems.append(f"time zone: {shell['tz']}")
    if report["web_search_in_the_tools_offered"]:
        problems.append("web search is offered")
    problems += [f"first prompt: {name}" for name, value in report["first_prompt"].items() if value]
    sync = report["background_plugin_sync"]
    if sync["traces_with_it_off"] or not sync["first_prompt_unchanged_by_turning_it_off"]:
        problems.append(f"background plugin sync: {sync}")
    probe = report["permission_profile"]
    for name, group in probe.items():
        problems += [f"{name}: {item}" for item, good in group.items() if not good]
    for fixture, row in report["full_run_path_by_fixture"].items():
        if set(row["outcomes"]) != {fixture} or row["violations"] or row["xcrun_noise_lines"] or "0 disagreements" not in row["audit"]:
            problems.append(f"full path {fixture}: {row}")
    for name, row in report["unfinished_runs"].items():
        if row["outcomes"] != ["failed"] or row["attempts"] != 6 or row["failed"] != 3 or row["new"] or row["declined"] or row["screen_result"] != "incomplete":
            problems.append(f"unfinished run {name}: {row}")
    print("harness check " + ("ok" if not problems else f"FAILED: {problems}"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
