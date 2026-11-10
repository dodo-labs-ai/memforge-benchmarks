"""Run the capped pilot: resumable, one result written as each run finishes.

    python3 -m harness.pilot preflight
    python3 -m harness.pilot selftest
    python3 -m harness.pilot reparse
    python3 -m harness.pilot audit
    python3 -m harness.pilot run [--batch A,B,C,D] [--only TASK/GROUP/REP ...] [--force] [--results DIR]

A run that already has a line in runs.jsonl is skipped, so killing and restarting
loses at most the runs in flight. Groups run as separate batches, which lets the
sandbox's access log prove that groups A, B and C never reached it; group D runs one
at a time, which ties every request in that log to one run.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import home as run_home
from . import parse, sandbox, scan
from .common import (
    API_URL,
    CODEX_BIN,
    CODEX_VERSION,
    CONCURRENCY,
    GROUPS,
    MAX_RETRIES,
    MEMORY_READ_TOOLS,
    MODEL,
    PLUGIN_VERSION,
    REPO,
    RESULTS_DIR,
    RUN_PATH,
    RUN_TIMEOUT_SECONDS,
    RUNS_PER_CELL,
    TASKS_DIR,
    TOKEN_CAP,
    WORK_ROOT,
    corpus_manifest,
    load_secrets,
    load_tasks,
)

ORDER_SEED = 20261104
# The value is a placeholder in anything recorded; the real one is in the process only.
ENDPOINT_PLACEHOLDER = "<OpenAI-compatible endpoint>"
COMMON_OVERRIDES = (
    'model_provider="relay"',
    'model_providers.relay.name="relay"',
    'model_providers.relay.env_key="MEMFORGE_RELAY_API_KEY"',
    'model_providers.relay.wire_api="responses"',
    # Codex retries nothing on its own, so every retry is visible and counted here.
    "model_providers.relay.request_max_retries=0",
    "model_providers.relay.stream_max_retries=0",
    "features.unbounded_connection_retries=false",
    'web_search="disabled"',
    "features.memories=false",
    "memories.generate_memories=false",
    "memories.use_memories=false",
    "features.plugin_discovery_prefetch=false",
    "features.tool_suggest=false",
    "features.remote_plugin=false",
    "features.daemon_auto_start=false",
    "analytics.enabled=false",
    "check_for_update_on_startup=false",
    'shell_environment_policy.inherit="core"',
    'approval_policy="never"',
    'history.persistence="none"',
)


@dataclass(frozen=True)
class RunSpec:
    task: str
    group: str
    rep: int

    @property
    def key(self) -> str:
        return f"{self.task}/{self.group}/{self.rep}"

    @property
    def stem(self) -> str:
        return f"{self.task}__{self.group}__{self.rep}"


def codex_argv(group: str, repo: Path, prompt: str, endpoint: str, *, strict: bool | None = None) -> list[str]:
    strict = group != "D" if strict is None else strict
    argv = [CODEX_BIN, "exec", "--json", "-m", MODEL, "-C", str(repo)]
    if strict:
        argv.append("--strict-config")
    if group == "D":
        # The plugin's hook was read and is static text. Non-interactive Codex has no
        # way to accept it, and an interactive user would be asked once.
        argv.append("--dangerously-bypass-hook-trust")
    for override in (*COMMON_OVERRIDES, f'model_providers.relay.base_url="{endpoint}"'):
        argv += ["-c", override]
    argv.append(prompt)
    return argv


def codex_env(dirs: run_home.RunDirs, api_key: str | None) -> dict[str, str]:
    env = {"PATH": RUN_PATH, "HOME": str(dirs.home), "CODEX_HOME": str(dirs.codex_home), "TMPDIR": str(dirs.tmp)}
    if api_key is not None:
        env["MEMFORGE_RELAY_API_KEY"] = api_key
    return env


def now() -> datetime:
    return datetime.now(timezone.utc)


class Ledger:
    """Results on disk are the only state, so a restart continues where this stopped."""

    def __init__(self, results: Path) -> None:
        self.results = results
        self.transcripts = results / "transcripts"
        self.transcripts.mkdir(parents=True, exist_ok=True)
        (results / "isolation").mkdir(exist_ok=True)
        self.runs_file = results / "runs.jsonl"
        self.attempts_file = results / "attempts.jsonl"
        self.stop_file = results / "STOP.json"
        self.lock = threading.Lock()
        self.stop_reason: str | None = None
        self.largest_run = 1_000_000

    def _read(self, path: Path) -> list[dict]:
        return parse.read_jsonl(path)

    def done_keys(self) -> set[str]:
        return {row["key"] for row in self._read(self.runs_file)}

    def retries_used(self) -> int:
        return sum(1 for row in self._read(self.attempts_file) if row.get("retried"))

    def tokens_used(self) -> int:
        """Input, cached input and output as reported, added up: the cap's own measure."""
        total = sum(row["tokens"]["cap_count"] for row in self._read(self.attempts_file))
        for name in ("probes.jsonl",):
            total += sum(row.get("cap_count", 0) for row in self._read(self.results / name))
        usage = self.results / "isolation" / "memforge_usage.json"
        if usage.exists():
            total += json.loads(usage.read_text())["total_tokens"]
        return total

    def _append(self, path: Path, row: dict) -> None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def record_attempt(self, row: dict) -> None:
        with self.lock:
            self._append(self.attempts_file, row)
            self.largest_run = max(self.largest_run, row["tokens"]["cap_count"])

    def record_run(self, row: dict) -> None:
        with self.lock:
            self._append(self.runs_file, row)

    def stop(self, reason: str) -> None:
        with self.lock:
            if self.stop_reason is None:
                self.stop_reason = reason
                self.stop_file.write_text(json.dumps({"reason": reason, "at": now().isoformat()}, indent=2) + "\n")
                print(f"STOP: {reason}", flush=True)


def _child_mcp_pid(parent: int) -> int | None:
    pending = [parent]
    while pending:
        pid = pending.pop()
        children = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
        for child in children:
            command = subprocess.run(["ps", "-o", "command=", "-p", child], capture_output=True, text=True).stdout
            if "memforge_mcp" in command:
                return int(child)
            pending.append(int(child))
    return None


def sample_mcp_process(codex_pid: int, stop: threading.Event, found: dict) -> None:
    """Read the plugin MCP process's real environment, names listed below only."""
    wanted = ("HOME", "CODEX_HOME", "MEMFORGE_API_URL", "MEMFORGE_EDITION", "MEMFORGE_MCP_CLIENT", "MEMFORGE_CODEX_CONFIG")
    while not stop.wait(1.0):
        pid = _child_mcp_pid(codex_pid)
        if pid is None:
            continue
        text = subprocess.run(["ps", "-Eww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
        cwd = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        found["pid_seen"] = True
        found["cwd"] = next((line[1:] for line in cwd.splitlines() if line.startswith("n")), None)
        for name in wanted:
            match = re.search(rf"(?:^|\s){name}=(\S*)", text)
            found[name] = match.group(1) if match else None
        found["api_token_present"] = bool(re.search(r"(?:^|\s)MEMFORGE_API_TOKEN=\S", text))
        return


def run_assertion(task: str, repo: Path, tmp: Path) -> dict:
    """Classify the workspace with the task's own script, offline and without any key."""
    command = [
        "/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)",
        shutil.which("python3", path=RUN_PATH), str(TASKS_DIR / task / "assert_outcome.py"), str(repo),
    ]
    env = {"PATH": RUN_PATH, "HOME": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "en_US.UTF-8"}
    try:
        result = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"outcome": "neither", "detail": "the assertion timed out after 60 seconds"}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        verdict = json.loads(lines[-1])
        if verdict.get("outcome") in ("old", "new", "neither"):
            return verdict
    except (IndexError, ValueError):
        pass
    return {"outcome": "neither", "detail": f"the assertion gave no verdict: exit {result.returncode}: {result.stderr[-300:]}"}


def token_counts(events: dict, rollout: dict) -> dict:
    """Prefer the turn totals; a killed run has only its session record's running total."""
    usage = events["usage"] or rollout["tokens"]
    source = "events" if events["usage"] else ("rollout" if rollout["tokens"] else "none")
    input_tokens = int(usage.get("input_tokens", 0))
    cached = int(usage.get("cached_input_tokens", 0))
    output = int(usage.get("output_tokens", 0))
    return {
        "input": input_tokens,
        "cached_input": cached,
        "output": output,
        "reasoning_output": int(usage.get("reasoning_output_tokens", 0)),
        "uncached_input": input_tokens - cached,
        "total": input_tokens + output,
        "cap_count": input_tokens + cached + output,
        "source": source,
    }


def execute(spec: RunSpec, attempt: int, task: dict, memory_roles: dict, secrets: dict, ledger: Ledger, scrubber: scan.Scrubber) -> dict:
    dirs = run_home.new_run_dirs()
    run_home.prepare_home(dirs, spec.group)
    run_home.prepare_repo(dirs, spec.task, spec.group)
    plugin_hash_before = run_home.plugin_tree_hash(dirs.home) if spec.group == "D" else None
    argv = codex_argv(spec.group, dirs.repo, task["prompt"], secrets["MEMFORGE_RELAY_BASE_URL"].rstrip("/"))
    env = codex_env(dirs, secrets["MEMFORGE_RELAY_API_KEY"])
    events_path, stderr_path = dirs.root / "events.jsonl", dirs.root / "stderr.txt"
    started = now()
    begun = time.monotonic()
    mcp_seen: dict = {}
    with events_path.open("wb") as events_out, stderr_path.open("wb") as stderr_out:
        process = subprocess.Popen(
            argv, cwd=dirs.repo, env=env, stdin=subprocess.DEVNULL, stdout=events_out, stderr=stderr_out, start_new_session=True
        )
        sampler_stop = threading.Event()
        sampler = None
        if spec.group == "D":
            sampler = threading.Thread(target=sample_mcp_process, args=(process.pid, sampler_stop, mcp_seen), daemon=True)
            sampler.start()
        timed_out = False
        try:
            process.wait(timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            sampler_stop.set()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            process.wait()
    duration = time.monotonic() - begun
    finished = now()
    leftovers = subprocess.run(["pgrep", "-f", str(dirs.root)], capture_output=True, text=True).stdout.split()
    for pid in leftovers:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except (ProcessLookupError, ValueError, PermissionError):
            pass

    rollouts = sorted(dirs.codex_home.glob("sessions/**/*.jsonl"))
    events = parse.parse_events(events_path)
    rollout = parse.parse_rollouts(rollouts)
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    failure = parse.classify_failure(events["failures"], stderr_text)
    if process.returncode not in (0, None) and not timed_out and not events["failures"]:
        tail = stderr_text[-2000:]
        failure = "rate_limited" if parse.RATE_LIMIT.search(tail) else "transport" if parse.TRANSPORT.search(tail) else "other"
    status = "timeout" if timed_out else {None: "completed", "rate_limited": "rate_limited", "transport": "transport_failure", "other": "error"}[failure]
    verdict = run_assertion(spec.task, dirs.repo, dirs.tmp)
    diff = run_home.workspace_diff(dirs)
    manifest = corpus_manifest()["documents"]
    isolation = parse.isolation_findings(events, rollout, parse.parse_tool_activity(rollouts), str(dirs.root), str(dirs.repo), spec.group)
    if spec.group == "D":
        isolation["mcp_process"] = dict(mcp_seen)
        isolation["plugin_tree_unchanged"] = run_home.plugin_tree_hash(dirs.home) == plugin_hash_before
        if mcp_seen.get("pid_seen"):
            if mcp_seen.get("HOME") != str(dirs.home):
                isolation["violations"].append("the plugin's MCP process has another HOME")
            if mcp_seen.get("api_token_present"):
                isolation["violations"].append("the plugin's MCP process holds an API token")
            if mcp_seen.get("MEMFORGE_API_URL") not in (None, API_URL):
                isolation["violations"].append("the plugin's MCP process names another target")
        if not isolation["plugin_tree_unchanged"]:
            isolation["violations"].append("the plugin's files changed during the run")
    elif (dirs.codex_home / "plugins").exists() and any((dirs.codex_home / "plugins").rglob("memforge_mcp.py")):
        isolation["violations"].append("a group without the plugin has it installed")

    stem = spec.stem if attempt == 1 else f"{spec.stem}.attempt{attempt}"
    scrubbed = 0
    for source, suffix in ((events_path, "events.jsonl"), (stderr_path, "stderr.txt")):
        text, hits = scrubber.scrub(source.read_text(encoding="utf-8", errors="replace"))
        scrubbed += hits
        (ledger.transcripts / f"{stem}.{suffix}").write_text(text, encoding="utf-8")
    rollout_lines = []
    for path in rollouts:
        text, hits = scrubber.scrub(path.read_text(encoding="utf-8", errors="replace"))
        scrubbed += hits
        rollout_lines.append(text)
    (ledger.transcripts / f"{stem}.rollout.jsonl").write_text("".join(rollout_lines), encoding="utf-8")
    text, hits = scrubber.scrub(diff)
    scrubbed += hits
    (ledger.transcripts / f"{stem}.diff").write_text(text, encoding="utf-8")

    record = {
        "key": spec.key,
        "task": spec.task,
        "group": spec.group,
        "rep": spec.rep,
        "attempt": attempt,
        "run_dir_id": dirs.root.name,
        "status": status,
        "failure_messages": [scrubber.scrub(message)[0][:500] for message in events["failures"]],
        "exit_code": process.returncode,
        "outcome": verdict["outcome"],
        "assertion_detail": scrubber.scrub(str(verdict.get("detail", "")))[0][:600],
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round(duration, 1),
        "tokens": token_counts(events, rollout),
        "turns": events["turns"],
        "command_count": len(events["commands"]),
        "files_changed": run_home_changed(diff),
        **parse.documents_seen(events["commands"], manifest, spec.task),
        **parse.memory_usage(events["mcp_calls"], memory_roles, spec.task),
        "checked_file_times": parse.checked_file_times(events["commands"]),
        "final_message": scrubber.scrub(events["messages"][-1] if events["messages"] else "")[0][:3000],
        "model": rollout["model"],
        "model_provider": rollout["model_provider"],
        "reasoning_effort": rollout["effort"],
        "isolation": isolation,
        "transcript_scrub_hits": scrubbed,
        "transcripts": f"transcripts/{stem}",
        "rerun_command": f"EXPERIMENT_ENV_FILE=<env file> python3 -m harness.pilot run --only {spec.key} --force --results <other dir>",
    }
    # Parsing kept command text in memory only; the record holds no copy of an endpoint or key.
    shutil.rmtree(dirs.root, ignore_errors=True)
    return record


def run_home_changed(diff: str) -> list[str]:
    return sorted(set(re.findall(r"^diff --git a/(\S+) ", diff, flags=re.MULTILINE)))


def run_one(spec: RunSpec, tasks: dict, memory_roles: dict, secrets: dict, ledger: Ledger, scrubber: scan.Scrubber, api_check: bool) -> None:
    attempt = 0
    while ledger.stop_reason is None:
        attempt += 1
        record = execute(spec, attempt, tasks[spec.task], memory_roles, secrets, ledger, scrubber)
        print(
            f"{spec.key} attempt {attempt}: {record['status']} outcome={record['outcome']} "
            f"tokens={record['tokens']['total']} {record['duration_seconds']}s memory={record['memory_tools']}",
            flush=True,
        )
        retry = False
        if record["status"] == "rate_limited":
            ledger.stop(f"rate limited during {spec.key}")
        elif record["status"] == "transport_failure":
            with ledger.lock:
                used = sum(1 for row in parse.read_jsonl(ledger.attempts_file) if row.get("retried"))
            if used < MAX_RETRIES:
                retry = True
            else:
                ledger.stop(f"{MAX_RETRIES} retries used and {spec.key} failed on transport again")
        record["retried"] = retry
        if api_check:
            time.sleep(2)
            start, end = datetime.fromisoformat(record["started_at"]), datetime.fromisoformat(record["finished_at"])
            requests = sandbox.access_requests(start - timedelta(seconds=1), end + timedelta(seconds=1))
            record["api_requests"] = [f"{item['method']} {item['path']} {item['status']}" for item in requests]
            data_requests = [item for item in requests if item["path"] != "/.well-known/memforge"]
            completed = sum(record["memory_tools"].values())
            record["api_requests_match_tool_calls"] = len(data_requests) >= completed
            if not record["api_requests_match_tool_calls"]:
                record["isolation"]["violations"].append(
                    f"{completed} memory tool calls succeeded but the sandbox logged {len(data_requests)} requests"
                )
        ledger.record_attempt(record)
        if record["isolation"]["violations"]:
            ledger.stop(f"isolation violation in {spec.key}: {record['isolation']['violations']}")
        if not retry:
            if record["status"] != "rate_limited" and not record["isolation"]["violations"]:
                ledger.record_run(record)
            return


def all_specs(tasks: dict, groups: tuple[str, ...]) -> list[RunSpec]:
    specs = [RunSpec(task, group, rep) for task in tasks for group in groups for rep in range(1, RUNS_PER_CELL + 1)]
    random.Random(ORDER_SEED).shuffle(specs)
    return specs


def run_batch(group: str, specs: list[RunSpec], tasks: dict, memory_roles: dict, secrets: dict, ledger: Ledger, scrubber: scan.Scrubber) -> None:
    concurrency = 1 if group == "D" else CONCURRENCY
    in_flight: set = set()
    pending = list(specs)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while pending or in_flight:
            while pending and len(in_flight) < concurrency and ledger.stop_reason is None:
                # A run in flight may still spend what the largest run so far spent.
                reserved = (len(in_flight) + 1) * ledger.largest_run
                if ledger.tokens_used() + reserved >= TOKEN_CAP:
                    ledger.stop(f"token cap {TOKEN_CAP} would be reached")
                    break
                spec = pending.pop(0)
                in_flight.add(pool.submit(run_one, spec, tasks, memory_roles, secrets, ledger, scrubber, group == "D"))
            if ledger.stop_reason is not None:
                pending.clear()
            if not in_flight:
                break
            finished, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in finished:
                future.result()
            if group == "D":
                time.sleep(3)


def developer_project_state() -> dict:
    """The developer's own Compose project, read only, without its labels or paths."""
    state: dict = {"containers": {}, "volume": None}
    names = subprocess.run(
        ["docker", "ps", "-a", "--filter", "label=com.docker.compose.project=memforge", "--format", "{{.Names}}"], capture_output=True, text=True
    ).stdout.split()
    for name in sorted(names):
        raw = subprocess.run(["docker", "inspect", name], capture_output=True, text=True).stdout
        item = json.loads(raw)[0]
        state["containers"][name] = {
            "id": item["Id"],
            "image": item["Image"],
            "status": item["State"]["Status"],
            "started_at": item["State"]["StartedAt"],
            "finished_at": item["State"]["FinishedAt"],
        }
    raw = subprocess.run(["docker", "volume", "inspect", "memforge_memforge-data"], capture_output=True, text=True).stdout
    if raw.strip():
        item = json.loads(raw)[0]
        state["volume"] = {"name": item["Name"], "created_at": item["CreatedAt"]}
    listeners = subprocess.run(["lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
    state["listeners_on_default_plugin_port"] = max(0, len(listeners.splitlines()) - 1)
    return state


def memory_roles_of(state: dict) -> dict:
    roles = {}
    for task, entry in state["by_task"].items():
        for role in ("stale", "current"):
            for memory in entry[role]["memories"]:
                roles[memory["id"]] = (task, role)
    return roles


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def commit_results(message: str, results: Path, secrets: dict) -> None:
    if results != RESULTS_DIR:
        return
    findings = scan.scan_repository(secrets)
    if findings:
        raise SystemExit(f"scan found hits, nothing committed: {findings}")
    subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode
    if changed:
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=REPO, check=True)


def cmd_run(args: argparse.Namespace) -> int:
    results = Path(args.results).resolve() if args.results else RESULTS_DIR
    ledger = Ledger(results)
    if ledger.stop_file.exists() and not args.clear_stop:
        print(f"refusing to continue: {ledger.stop_file.read_text()}", file=sys.stderr)
        return 3
    ledger.stop_file.unlink(missing_ok=True)
    secrets = load_secrets()
    scrubber = scan.Scrubber(secrets)
    tasks = load_tasks()
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    state = sandbox.verify()
    memory_roles = memory_roles_of(state)
    write_json(results / "isolation" / "memforge_usage.json", {"usage": state["model_usage"], "total_tokens": sum(entry["prompt_tokens"] + entry["completion_tokens"] for entry in state["model_usage"].values())})
    groups = tuple(args.batch.split(",")) if args.batch else GROUPS
    done = set() if args.force else ledger.done_keys()
    specs = all_specs(tasks, GROUPS)
    if args.only:
        specs = [spec for spec in specs if spec.key in set(args.only)]
    for group in groups:
        batch = [spec for spec in specs if spec.group == group and spec.key not in done]
        if not batch or ledger.stop_reason:
            continue
        print(f"batch {group}: {len(batch)} runs, tokens so far {ledger.tokens_used()}", flush=True)
        before = sandbox.snapshot()
        time.sleep(2)
        window_start = now()
        run_batch(group, batch, tasks, memory_roles, secrets, ledger, scrubber)
        window_end = now()
        time.sleep(2)
        requests = sandbox.access_requests(window_start, window_end)
        after = sandbox.snapshot()
        check = {
            "group": group,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "requests_reaching_sandbox": requests,
            "memories_and_links_unchanged": sandbox.fingerprint(before) == sandbox.fingerprint(after),
            "memforge_usage_in_window": sandbox.model_usage(window_start),
            "developer_project": developer_project_state(),
        }
        name = f"batch_{group}" if not args.only else f"batch_{group}_{window_start.strftime('%H%M%S')}"
        write_json(results / "isolation" / f"{name}.json", check)
        if group != "D" and requests:
            ledger.stop(f"group {group} runs coincided with {len(requests)} requests reaching the sandbox")
        if not check["memories_and_links_unchanged"]:
            ledger.stop(f"memories or links changed during batch {group}")
        write_json(results / "sandbox_state.json", after)
        commit_results(f"Record pilot batch {group}", results, secrets)
        print(f"batch {group} recorded", flush=True)
    code = 3 if ledger.stop_reason else 0
    print("finished" if code == 0 else f"stopped: {ledger.stop_reason}", flush=True)
    return code


# -- Checks that need no model call ------------------------------------------------------------


def sandbox_policy_probe(group: str) -> dict:
    """Run a script under the run's own profile and report what it could reach."""
    dirs = run_home.new_run_dirs()
    try:
        run_home.prepare_home(dirs, group)
        run_home.prepare_repo(dirs, "job-retries", group)
        checks = {
            "developer_codex_config": f"test -r {Path.home()}/.codex/config.toml && head -c 1 {Path.home()}/.codex/config.toml",
            "developer_home": f"ls {Path.home()}",
            "this_repository": f"ls {REPO}",
            "sandbox_docs_folder": f"ls {sandbox.DOCS_DIR}",
            "work_root": f"ls {WORK_ROOT}",
            "shared_tmp": "ls /private/tmp",
            "var_tmp": "ls /private/var/tmp",
            "marketplace_area": f"ls {dirs.codex_home}/.tmp",
            "outside_write": f"touch {WORK_ROOT}/x-{dirs.root.name}",
            "home_write": f"touch {dirs.home}/x",
        }
        expected_refused = dict(checks)
        allowed = {
            "repo_write": "touch probe.txt && rm probe.txt",
            "tmp_write": f"touch {dirs.tmp}/x",
            "python": "python3 -c 'print(1)'",
            "grep_docs_or_repo": "grep -rl retry .",
        }
        network = {
            "sandbox_api": f"curl -s -m 5 -o /dev/null {API_URL}/api/v1/health",
            "public_internet": "curl -s -m 5 -o /dev/null https://example.com",
        }
        outcome = {"refused": {}, "allowed": {}, "network_blocked": {}}
        env = codex_env(dirs, None)

        def attempt(script: str) -> bool:
            result = subprocess.run(
                [CODEX_BIN, "sandbox", "-P", "iso", "-C", str(dirs.repo), "--", "/bin/sh", "-c", script],
                env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
            )
            return result.returncode == 0

        for name, script in expected_refused.items():
            outcome["refused"][name] = not attempt(script)
        for name, script in allowed.items():
            outcome["allowed"][name] = attempt(script)
        for name, script in network.items():
            outcome["network_blocked"][name] = not attempt(script)
        return outcome
    finally:
        shutil.rmtree(dirs.root, ignore_errors=True)


def group_context_probe(group: str, endpoint: str) -> dict:
    """The model-visible prompt and the MCP servers of a group's home, with no model call."""
    dirs = run_home.new_run_dirs()
    try:
        run_home.prepare_home(dirs, group)
        run_home.prepare_repo(dirs, "job-retries", group)
        env = codex_env(dirs, None)
        overrides = []
        for override in (*COMMON_OVERRIDES, f'model_providers.relay.base_url="{endpoint}"'):
            overrides += ["-c", override]
        servers = subprocess.run([CODEX_BIN, "mcp", "list", "--json"], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=dirs.repo)
        prompt = subprocess.run(
            [CODEX_BIN, "debug", "prompt-input", *overrides, "-c", f'model="{MODEL}"', "probe"],
            env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, cwd=dirs.repo,
        )
        text = prompt.stdout
        return {
            "config_toml": re.sub(re.escape(dirs.root.name), "<run>", run_home.config_toml(dirs, group)),
            "mcp_servers": [item.get("name") for item in json.loads(servers.stdout or "[]")],
            "prompt_input_ok": prompt.returncode == 0,
            "prompt_has_docs_index": "# Docs index" in text,
            "prompt_mentions_developer_home": str(Path.home()) in text,
            "prompt_mentions_memforge": "memforge" in text.lower(),
            "skill_roots": [root.replace(dirs.root.name, "<run>") for root in re.findall(r"`r\d+` = `([^`]+)`", text)],
        }
    finally:
        shutil.rmtree(dirs.root, ignore_errors=True)


def cmd_preflight(_args: argparse.Namespace) -> int:
    secrets = load_secrets()
    problems: list[str] = []
    version = subprocess.run([CODEX_BIN, "--version"], capture_output=True, text=True, env={"PATH": RUN_PATH}).stdout.strip()
    if version != f"codex-cli {CODEX_VERSION}":
        problems.append(f"Codex is {version}")
    if secrets["MEMFORGE_RELAY_MODEL"] != MODEL:
        problems.append(f"the env file names model {secrets['MEMFORGE_RELAY_MODEL']}")
    template = run_home.check_template()
    if template["version"] != PLUGIN_VERSION or not template["cache_matches_marketplace_checkout"]:
        problems.append(f"template home: {template}")
    state = sandbox.verify()
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    report = {
        "codex_version": version,
        "template": template,
        "sandbox": {"commit": state["memforge_commit"], "models": state["models"], "relation_work": state["relation_work"], "by_task": state["by_task"]},
        "memforge_usage": state["model_usage"],
        "groups": {},
        "developer_project": developer_project_state(),
    }
    endpoint = secrets["MEMFORGE_RELAY_BASE_URL"].rstrip("/")
    for group in GROUPS:
        policy = sandbox_policy_probe(group)
        context = group_context_probe(group, endpoint)
        report["groups"][group] = {"sandbox_policy": policy, "context": context}
        if not all(policy["refused"].values()):
            problems.append(f"group {group} reached something it must not: {policy['refused']}")
        if not all(policy["allowed"].values()):
            problems.append(f"group {group} lacks something it needs: {policy['allowed']}")
        if not all(policy["network_blocked"].values()):
            problems.append(f"group {group} shell has network: {policy['network_blocked']}")
        if context["mcp_servers"] != (["memforge"] if group == "D" else []):
            problems.append(f"group {group} has MCP servers {context['mcp_servers']}")
        if context["prompt_has_docs_index"] != (group == "C"):
            problems.append(f"group {group} docs index in prompt: {context['prompt_has_docs_index']}")
        if context["prompt_mentions_developer_home"]:
            problems.append(f"group {group}'s prompt mentions the developer's home")
    report["problems"] = problems
    scrubbed, _ = scan.Scrubber(secrets).scrub(json.dumps(report, indent=2, ensure_ascii=False))
    (RESULTS_DIR / "isolation").mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "isolation" / "preflight.json").write_text(scrubbed + "\n", encoding="utf-8")
    print("preflight " + ("ok" if not problems else f"FAILED: {problems}"))
    return 1 if problems else 0


def cmd_reparse(args: argparse.Namespace) -> int:
    """Recompute what a record derives from its transcripts, so a parser fix reaches old runs."""
    results = Path(args.results).resolve() if args.results else RESULTS_DIR
    state = json.loads((results / "sandbox_state.json").read_text(encoding="utf-8"))
    roles = memory_roles_of(state)
    manifest = corpus_manifest()["documents"]
    for name in ("attempts.jsonl", "runs.jsonl"):
        rows = parse.read_jsonl(results / name)
        for row in rows:
            base = results / row["transcripts"]
            events = parse.parse_events(base.parent / f"{base.name}.events.jsonl")
            rollout = parse.parse_rollouts([base.parent / f"{base.name}.rollout.jsonl"])
            root = WORK_ROOT / row["run_dir_id"]
            activity = parse.parse_tool_activity([base.parent / f"{base.name}.rollout.jsonl"])
            fresh = parse.isolation_findings(events, rollout, activity, str(root), str(root / "repo"), row["group"])
            carried = [item for item in row["isolation"]["violations"] if "MCP process" in item or "plugin's files" in item or "sandbox logged" in item]
            fresh["violations"] += carried
            row["isolation"].update(fresh)
            row.update(parse.documents_seen(events["commands"], manifest, row["task"]))
            row.update(parse.memory_usage(events["mcp_calls"], roles, row["task"]))
            row["checked_file_times"] = parse.checked_file_times(events["commands"])
        (results / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Replay every recorded diff on a fresh task repository and classify it again."""
    results = Path(args.results).resolve() if args.results else RESULTS_DIR
    disagreements = 0
    rows = parse.read_jsonl(results / "runs.jsonl")
    for row in rows:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            shutil.copytree(TASKS_DIR / row["task"] / "repo", repo, ignore=shutil.ignore_patterns("__pycache__"))
            diff = (results / f"{row['transcripts']}.diff").read_text(encoding="utf-8")
            if diff.strip():
                applied = subprocess.run(["git", "apply", "-"], input=diff, text=True, cwd=repo, capture_output=True)
                if applied.returncode != 0:
                    disagreements += 1
                    print(f"{row['key']}: its diff does not apply: {applied.stderr[:200]}")
                    continue
            verdict = run_assertion(row["task"], repo, root)
        if verdict["outcome"] != row["outcome"]:
            disagreements += 1
            print(f"{row['key']}: recorded {row['outcome']}, replay {verdict['outcome']}: {verdict.get('detail')}")
    print(f"replayed {len(rows)} diffs, {disagreements} disagreements")
    return 1 if disagreements else 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    """Each assertion must give the right verdict on known solutions and on the untouched repository."""
    failures = []
    for task_id, task in load_tasks().items():
        for expected in ("old", "new", "neither", "untouched"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                repo = root / "repo"
                shutil.copytree(TASKS_DIR / task_id / "repo", repo, ignore=shutil.ignore_patterns("__pycache__"))
                if expected != "untouched":
                    shutil.copyfile(TASKS_DIR / task_id / "fixtures" / f"{expected}.py", repo / task["fixture_target"])
                verdict = run_assertion(task_id, repo, root)
                wanted = "neither" if expected == "untouched" else expected
                mark = "ok" if verdict["outcome"] == wanted else "WRONG"
                print(f"{task_id:16} {expected:10} -> {verdict['outcome']:8} {mark}")
                if mark != "ok":
                    failures.append((task_id, expected, verdict))
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="harness.pilot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight").set_defaults(handler=cmd_preflight)
    commands.add_parser("selftest").set_defaults(handler=cmd_selftest)
    audit = commands.add_parser("audit")
    audit.add_argument("--results", help="another results directory")
    audit.set_defaults(handler=cmd_audit)
    reparse = commands.add_parser("reparse")
    reparse.add_argument("--results", help="another results directory")
    reparse.set_defaults(handler=cmd_reparse)
    run = commands.add_parser("run")
    run.add_argument("--batch", help="comma-separated groups, in order")
    run.add_argument("--only", nargs="*", help="run keys such as job-retries/B/2")
    run.add_argument("--force", action="store_true", help="run keys again even if they have results")
    run.add_argument("--clear-stop", action="store_true", help="continue after a recorded stop")
    run.add_argument("--results", help="another results directory, leaving the pilot's untouched")
    run.set_defaults(handler=cmd_run)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
