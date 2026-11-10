"""The closed-book screen: each task with no documents, three runs, at most three at a time.

    python3 -m formal.harness.screen run [--tasks all|scored|reserves|ID,ID] [--concurrency N] [--results DIR] [--clear-stop] [--rerun-failed] [--commit]
    python3 -m formal.harness.screen report [--results DIR]
    python3 -m formal.harness.screen audit [--results DIR]

Each task gets one result:

    already_known   two or more of three runs reach `new`: the plan's rule drops the task
    inconclusive    two or more of three runs decline, usually because the guide the prompt
                    cites is not there: such a run says nothing about prior knowledge, so
                    the user decides what happens to the task
    incomplete      fewer than three runs finished
    kept            none of these

A run counts only if Codex finished it. A run that timed out or ended on an error is rerun
once. A transport failure, which includes an error page from the endpoint's gateway, is
retried after a pause. Retries are limited to 15 across the screen. A run still unfinished
after that has the outcome `failed`, whatever its workspace shows, and stays out of every
rate, and --rerun-failed runs it again later: every attempt stays in attempts.jsonl and the
latest line of a run in runs.jsonl stands. `run` is resumable: a run with a line in runs.jsonl
is skipped, and a recorded STOP.json blocks further runs until --clear-stop. It stops on any
rate limit and before the stage's token cap. Only group A exists here, so no documents, index
or plugin can reach a run.
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
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from harness import parse, scan
from harness import home as pilot_home
from harness.common import API_URL, CODEX_BIN, CODEX_VERSION, WORK_ROOT, load_secrets
from harness.pilot import COMMON_OVERRIDES, Ledger, run_home_changed, sample_mcp_process, token_counts

from ..common import MODEL, PROGRESS_LOG, REASONING_EFFORT, REPO, RESERVE_NUMBERS, SCORED_NUMBERS, STAGE0, TASKS_DIR, TIMEZONE, load_tasks
from . import budget, egress
from . import home as run_home
from .assertion import run_assertion

GROUP = "A"
REPETITIONS = 3
ORDER_SEED = 20261105
MAX_RETRIES = 15
RETRY_PAUSE_SECONDS = 30
MAX_CONCURRENCY = 3
RUN_TIMEOUT_SECONDS = 600
HEARTBEAT_SECONDS = 60
RESULTS = STAGE0 / "screen"
RERUNNABLE = {"transport_failure", "timeout", "error"}
_MACHINE_PROXY = egress.machine_proxy()
# Cloudflare's own codes for "the origin did not answer properly". The pilot's pattern stops at 504.
_GATEWAY_ERROR = re.compile(r"\bstatus 52[0-9]\b")
_XCRUN = re.compile(r"xcrun|xcodebuild\[|DVTDeveloperPaths")
FORMAL_OVERRIDES = (f'model_reasoning_effort="{REASONING_EFFORT}"', f'shell_environment_policy.set.TZ="{TIMEZONE}"')
# With the plugin feature on, Codex lists and clones a curated plugin repository in the
# background of every run. A group with no plugin turns it off, which leaves the prompt as it was.
NO_PLUGIN_OVERRIDE = "features.plugins=false"


@dataclass(frozen=True)
class RunSpec:
    task: str
    rep: int

    @property
    def group(self) -> str:
        return GROUP

    @property
    def key(self) -> str:
        return f"{self.task}/{GROUP}/{self.rep}"

    @property
    def stem(self) -> str:
        return f"{self.task}__{GROUP}__{self.rep}"


@dataclass(frozen=True)
class Setup:
    """What a run holds beyond the task's own repository."""

    isolation: str = GROUP  # the kind of group the isolation checks hold the run to: A, B, C or D
    stage: Callable[[Path], None] | None = None  # places documents and an index in the repository
    annotate: Callable[[dict, list[Path], str], dict] | None = None  # extra fields for the record

    @property
    def plugin(self) -> bool:
        return self.isolation == "D"


def log(message: str) -> None:
    PROGRESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_LOG.open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {message}\n")
    print(message, flush=True)


def codex_argv(repo: Path, prompt: str, endpoint: str, *, pinned: bool = True, plugin: bool = False) -> list[str]:
    argv = [CODEX_BIN, "exec", "--json", "-m", MODEL, "-C", str(repo)]
    # Codex does not know the plugin's settings table, and has no way to accept its static
    # hook in a non-interactive run, where a user would be asked once.
    argv.append("--dangerously-bypass-hook-trust" if plugin else "--strict-config")
    overrides = [*COMMON_OVERRIDES, f'model_providers.relay.base_url="{endpoint}"']
    if pinned:
        overrides += FORMAL_OVERRIDES
        if not plugin:
            overrides.append(NO_PLUGIN_OVERRIDE)
    for override in overrides:
        argv += ["-c", override]
    argv.append(prompt)
    return argv


def effort_of(rollouts: list[Path]) -> str | None:
    """The effort the session really ran at. Its turn context holds it under the collaboration mode."""
    for path in rollouts:
        for row in parse.read_jsonl(path):
            if row.get("type") == "turn_context":
                return (((row.get("payload") or {}).get("collaboration_mode") or {}).get("settings") or {}).get("reasoning_effort")
    return None


def timezone_of(rollouts: list[Path]) -> str | None:
    """The time zone the model was told, from the environment context of its first prompt."""
    for path in rollouts:
        found = re.search(r"<timezone>([^<]+)</timezone>", path.read_text(encoding="utf-8", errors="replace"))
        if found:
            return found.group(1)
    return None


def plugin_findings(dirs: run_home.RunDirs, tree_before: str, mcp_process: dict) -> dict:
    """What a plugin run's MCP process and plugin files say about its isolation."""
    violations = []
    unchanged = pilot_home.plugin_tree_hash(dirs.home) == tree_before
    if mcp_process.get("pid_seen"):
        if mcp_process.get("HOME") != str(dirs.home):
            violations.append("the plugin's MCP process has another HOME")
        if mcp_process.get("api_token_present"):
            violations.append("the plugin's MCP process holds an API token")
        if mcp_process.get("MEMFORGE_API_URL") not in (None, API_URL):
            violations.append("the plugin's MCP process names another target")
    if not unchanged:
        violations.append("the plugin's files changed during the run")
    return {"violations": violations, "mcp_process": mcp_process, "plugin_tree_unchanged": unchanged}


def execute(spec: RunSpec, attempt: int, task: dict, endpoint: str, api_key: str, ledger: Ledger, scrubber: scan.Scrubber, setup: Setup = Setup()) -> dict:
    dirs = run_home.new_run_dirs()
    run_home.prepare_home(dirs, setup.isolation)
    run_home.prepare_repo(dirs, spec.task, setup.stage)
    plugin_tree_before = pilot_home.plugin_tree_hash(dirs.home) if setup.plugin else None
    mcp_process: dict = {}
    sampler_stop = threading.Event()
    events_path, stderr_path = dirs.root / "events.jsonl", dirs.root / "stderr.txt"
    started = datetime.now(timezone.utc)
    begun = time.monotonic()
    timed_out = False
    proxy = egress.LoggingProxy(urlparse(endpoint).hostname, _MACHINE_PROXY)
    with events_path.open("wb") as events_out, stderr_path.open("wb") as stderr_out:
        process = subprocess.Popen(
            codex_argv(dirs.repo, task["prompt"], endpoint, plugin=setup.plugin), cwd=dirs.repo, env={**run_home.run_env(dirs, api_key), **proxy.env()},
            stdin=subprocess.DEVNULL, stdout=events_out, stderr=stderr_out, start_new_session=True,
        )
        watch = egress.Watch(process.pid, proxy)
        if setup.plugin:
            threading.Thread(target=sample_mcp_process, args=(process.pid, sampler_stop, mcp_process), daemon=True).start()
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
            connections = json.loads(scrubber.scrub(json.dumps(watch.stop()))[0])
    duration = time.monotonic() - begun
    run_home.kill_leftovers(dirs)
    rollouts = sorted(dirs.codex_home.glob("sessions/**/*.jsonl"))
    events = parse.parse_events(events_path)
    rollout = parse.parse_rollouts(rollouts)
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    failure = parse.classify_failure(events["failures"], stderr_text)
    if process.returncode not in (0, None) and not timed_out and not events["failures"]:
        tail = stderr_text[-2000:]
        failure = "rate_limited" if parse.RATE_LIMIT.search(tail) else "transport" if parse.TRANSPORT.search(tail) else "other"
    if failure == "other" and _GATEWAY_ERROR.search(" ".join(events["failures"])):
        failure = "transport"
    status = "timeout" if timed_out else {None: "completed", "rate_limited": "rate_limited", "transport": "transport_failure", "other": "error"}[failure]
    verdict = run_assertion(spec.task, dirs.repo, dirs.tmp)
    diff = run_home.workspace_diff(dirs)
    isolation = parse.isolation_findings(events, rollout, parse.parse_tool_activity(rollouts), str(dirs.root), str(dirs.repo), setup.isolation)
    if setup.plugin:
        found = plugin_findings(dirs, plugin_tree_before, mcp_process)
        isolation["violations"] += found.pop("violations")
        isolation.update(found)
    elif any((dirs.codex_home / "plugins").rglob("memforge_mcp.py")):
        isolation["violations"].append("a group without the plugin has it installed")
    effort = effort_of(rollouts)
    told_timezone = timezone_of(rollouts)
    if effort != REASONING_EFFORT:
        isolation["violations"].append(f"the run's effort is {effort}, not {REASONING_EFFORT}")
    raw_rollouts = "".join(path.read_text(encoding="utf-8", errors="replace") for path in rollouts)
    xcrun_noise = len(_XCRUN.findall(raw_rollouts))
    stem = spec.stem if attempt == 1 else f"{spec.stem}.attempt{attempt}"
    scrubbed = 0
    for text, suffix in ((events_path.read_text(encoding="utf-8", errors="replace"), "events.jsonl"), (stderr_text, "stderr.txt"), (raw_rollouts, "rollout.jsonl"), (diff, "diff")):
        clean, hits = scrubber.scrub(text)
        scrubbed += hits
        (ledger.transcripts / f"{stem}.{suffix}").write_text(clean, encoding="utf-8")
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
        "outcome": verdict["outcome"] if status == "completed" else "failed",
        "workspace_outcome": verdict["outcome"],
        "assertion_detail": scrubber.scrub(str(verdict.get("detail", "")))[0][:600],
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 1),
        "tokens": {**token_counts(events, rollout), "counted_against_the_cap": "total"},
        "turns": events["turns"],
        "command_count": len(events["commands"]),
        "files_changed": run_home_changed(diff),
        "final_message": scrubber.scrub(events["messages"][-1] if events["messages"] else "")[0][:3000],
        "model": rollout["model"],
        "model_provider": rollout["model_provider"],
        "reasoning_effort": effort,
        "timezone_told_to_model": told_timezone,
        "xcrun_noise_lines": xcrun_noise,
        "isolation": isolation,
        "egress": connections,
        "transcript_scrub_hits": scrubbed,
        "transcripts": f"transcripts/{stem}",
    }
    if setup.annotate:
        record.update(json.loads(scrubber.scrub(json.dumps(setup.annotate(events, rollouts, raw_rollouts)))[0]))
    shutil.rmtree(dirs.root, ignore_errors=True)
    return record


def select_tasks(choice: str) -> dict[str, dict]:
    tasks = load_tasks()
    numbers = {"scored": SCORED_NUMBERS, "reserves": RESERVE_NUMBERS, "all": (*SCORED_NUMBERS, *RESERVE_NUMBERS)}.get(choice)
    if numbers is not None:
        return {task_id: task for task_id, task in tasks.items() if task["number"] in numbers}
    return {task_id: tasks[task_id] for task_id in choice.split(",")}


def all_specs(tasks: dict[str, dict]) -> list[RunSpec]:
    specs = [RunSpec(task_id, rep) for task_id in tasks for rep in range(1, REPETITIONS + 1)]
    random.Random(ORDER_SEED).shuffle(specs)
    return specs


def _heartbeat(stop: threading.Event, status: dict, report) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        report(f"screen: alive, {status['done']} of {status['total']} runs done, running {sorted(status['current'])}, {budget.total()} tokens counted in the stage")


def _run_one(spec: RunSpec, task: dict, endpoint: str, api_key: str, ledger: Ledger, scrubber: scan.Scrubber, retries_allowed: int, status: dict, report, *, setup: Setup = Setup(), spent: Callable[[], int] = budget.total, cap: int = budget.TOKEN_CAP) -> None:
    """One run with its reruns. Everything shared is the ledger, which holds its own lock."""
    if spent() + ledger.largest_run >= cap:
        ledger.stop(f"the token cap {cap} would be reached")
        return
    attempt = 0
    status["current"].add(spec.key)
    try:
        while ledger.stop_reason is None:
            attempt += 1
            record = execute(spec, attempt, task, endpoint, api_key, ledger, scrubber, setup)
            report(f"{spec.key} attempt {attempt}: {record['status']} outcome={record['outcome']} tokens={record['tokens']['total']} {record['duration_seconds']}s")
            retry = False
            if record["status"] == "rate_limited":
                ledger.stop(f"rate limited during {spec.key}")
            elif record["status"] in RERUNNABLE and ledger.retries_used() < retries_allowed:
                retry = record["status"] == "transport_failure" or attempt < 2
            elif record["status"] == "transport_failure":
                ledger.stop(f"{retries_allowed} retries used and {spec.key} failed on transport again")
            record["retried"] = retry
            ledger.record_attempt(record)
            if record["isolation"]["violations"]:
                ledger.stop(f"isolation violation in {spec.key}: {record['isolation']['violations']}")
            if not retry:
                if record["status"] != "rate_limited" and not record["isolation"]["violations"]:
                    ledger.record_run(record)
                    status["done"] += 1
                break
            time.sleep(RETRY_PAUSE_SECONDS * attempt)
    finally:
        status["current"].discard(spec.key)


def latest_runs(results: Path) -> list[dict]:
    """Each run's latest line: a later rerun of a failed run stands."""
    return list({row["key"]: row for row in parse.read_jsonl(results / "runs.jsonl")}.values())


def run_all(tasks: dict[str, dict], results: Path, endpoint: str, api_key: str, scrubber: scan.Scrubber, *, retries_allowed: int = MAX_RETRIES, report=log, concurrency: int = MAX_CONCURRENCY, rerun_failed: bool = False) -> int:
    if not 1 <= concurrency <= MAX_CONCURRENCY:
        raise SystemExit(f"concurrency must be between 1 and {MAX_CONCURRENCY}")
    ledger = Ledger(results)
    done = {row["key"] for row in latest_runs(results) if not (rerun_failed and row["outcome"] == "failed")}
    pending = [spec for spec in all_specs(tasks) if spec.key not in done]
    status = {"done": len(done), "total": len(done) + len(pending), "current": set()}
    stop = threading.Event()
    threading.Thread(target=_heartbeat, args=(stop, status, report), daemon=True).start()

    def work(spec: RunSpec) -> None:
        if ledger.stop_reason is None:
            _run_one(spec, tasks[spec.task], endpoint, api_key, ledger, scrubber, retries_allowed, status, report)

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(work, pending))
    finally:
        stop.set()
    return 3 if ledger.stop_reason else 0


def preconditions(secrets: dict) -> list[str]:
    problems = []
    version = subprocess.run([CODEX_BIN, "--version"], capture_output=True, text=True).stdout.strip()
    if version != f"codex-cli {CODEX_VERSION}":
        problems.append(f"Codex is {version}")
    if secrets["MEMFORGE_RELAY_MODEL"] != MODEL:
        problems.append("the env file names another model")
    return problems


def cmd_run(args: argparse.Namespace) -> int:
    results = Path(args.results).resolve() if args.results else RESULTS
    ledger = Ledger(results)
    if ledger.stop_file.exists() and not args.clear_stop:
        print(f"refusing to continue: {ledger.stop_file.read_text()}", file=sys.stderr)
        return 3
    ledger.stop_file.unlink(missing_ok=True)
    secrets = load_secrets()
    problems = preconditions(secrets)
    if problems:
        print("; ".join(problems), file=sys.stderr)
        return 2
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    code = run_all(select_tasks(args.tasks), results, secrets["MEMFORGE_RELAY_BASE_URL"].rstrip("/"), secrets["MEMFORGE_RELAY_API_KEY"], scan.Scrubber(secrets), concurrency=args.concurrency, rerun_failed=args.rerun_failed)
    write_report(results)
    if args.commit and results.is_relative_to(REPO):
        findings = scan.scan_repository(secrets)
        if findings:
            print(f"scan found hits, nothing committed: {findings}", file=sys.stderr)
            return 1
        subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode:
            subprocess.run(["git", "commit", "-q", "-m", "Record the closed-book screen"], cwd=REPO, check=True)
    return code


def screen_result(counts: dict[str, int], finished: int) -> str:
    if counts["new"] >= 2:
        return "already_known"
    if counts["declined"] >= 2:
        return "inconclusive"
    if finished < REPETITIONS:
        return "incomplete"
    return "kept"


def write_report(results: Path) -> dict:
    """Outcomes per task, and what the screen says about each."""
    runs = latest_runs(results)
    attempts = parse.read_jsonl(results / "attempts.jsonl")
    tasks = load_tasks()
    per_task = {}
    for task_id in tasks:
        rows = sorted((row for row in runs if row["task"] == task_id), key=lambda row: row["rep"])
        if not rows:
            continue
        counts = {outcome: sum(row["outcome"] == outcome for row in rows) for outcome in ("old", "new", "neither", "declined", "failed")}
        finished = len(rows) - counts["failed"]
        per_task[task_id] = {
            "number": tasks[task_id]["number"],
            "role": tasks[task_id]["role"],
            "runs": len(rows),
            "finished_runs": finished,
            **counts,
            "old_rate_baseline": round(counts["old"] / finished, 3) if finished else None,
            "new_rate": round(counts["new"] / finished, 3) if finished else None,
            "declined_rate": round(counts["declined"] / finished, 3) if finished else None,
            "screen_result": screen_result(counts, finished),
            "complete": len(rows) >= REPETITIONS,
            "details": [row["assertion_detail"] for row in rows],
            "total_tokens": [row["tokens"]["total"] for row in rows],
            "duration_seconds": [row["duration_seconds"] for row in rows],
        }
    summary = {
        "rule": "Two or more of three closed-book runs answering `new` drops the task. Two or more declining makes it inconclusive, for the user to decide. A run Codex did not finish is `failed` and out of the rates.",
        "per_task": per_task,
        "attempts": len(attempts),
        "retries": sum(1 for row in attempts if row.get("retried")),
        "attempts_by_status": {status: sum(row["status"] == status for row in attempts) for status in sorted({row["status"] for row in attempts})},
        "tokens_counted_against_the_cap": sum(row["tokens"]["total"] for row in attempts),
        "reasoning_efforts_seen": sorted({str(row.get("reasoning_effort")) for row in attempts}),
        "time_zones_told_to_the_model": sorted({str(row.get("timezone_told_to_model")) for row in attempts}),
        "runs_with_xcrun_noise": sum(1 for row in attempts if row.get("xcrun_noise_lines")),
        "isolation_violations": sum(1 for row in attempts if row["isolation"]["violations"]),
        "egress": {
            "attempts_that_reached_the_endpoint_through_the_logging_proxy": sum(1 for row in attempts if row["egress"]["connections_to_the_endpoint"]),
            "other_hosts_flagged": sorted({label for row in attempts for label in row["egress"]["other_hosts"]}),
            "attempts_with_another_host": sum(1 for row in attempts if row["egress"]["other_hosts"]),
            "sockets_around_the_proxy_flagged": sorted({label for row in attempts for label in row["egress"]["sockets_around_the_proxy"]}),
            "attempts_with_a_socket_around_the_proxy": sum(1 for row in attempts if row["egress"]["sockets_around_the_proxy"]),
            "proxy_errors": sum(row["egress"]["proxy_errors"] for row in attempts),
            "limit": "The proxy sees what Codex sends to it. The poll looks for anything else every half second, so a direct connection that opens and closes between polls is not seen.",
        },
        "outcome_by_group_is_not_a_finding": "These runs only decide which tasks stay.",
    }
    (results / "screen_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def cmd_report(args: argparse.Namespace) -> int:
    print(json.dumps(write_report(Path(args.results).resolve() if args.results else RESULTS), indent=2, ensure_ascii=False))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Replay every recorded diff on a fresh task repository and classify it again."""
    results = Path(args.results).resolve() if args.results else RESULTS
    disagreements = 0
    rows = latest_runs(results)
    for row in rows:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            shutil.copytree(TASKS_DIR / row["task"] / "repo", repo, ignore=shutil.ignore_patterns("__pycache__"))
            diff = (results / f"{row['transcripts']}.diff").read_text(encoding="utf-8")
            if diff.strip():
                # Byte code a run's own Python left behind is recorded without its bytes, and no assertion reads it.
                applied = subprocess.run(["git", "apply", "--exclude=*__pycache__*", "-"], input=diff, text=True, cwd=repo, capture_output=True)
                if applied.returncode != 0:
                    disagreements += 1
                    print(f"{row['key']}: its diff does not apply: {applied.stderr[:200]}")
                    continue
            verdict = run_assertion(row["task"], repo, root)
        if verdict["outcome"] != row["workspace_outcome"]:
            disagreements += 1
            print(f"{row['key']}: recorded {row['workspace_outcome']}, replay {verdict['outcome']}: {verdict.get('detail')}")
    print(f"replayed {len(rows)} diffs, {disagreements} disagreements")
    return 1 if disagreements else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="formal.harness.screen")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--tasks", default="all", help="all, scored, reserves, or comma-separated task ids")
    run.add_argument("--concurrency", type=int, default=MAX_CONCURRENCY)
    run.add_argument("--results", help="another results directory")
    run.add_argument("--clear-stop", action="store_true")
    run.add_argument("--rerun-failed", action="store_true", help="run again the runs whose latest outcome is failed")
    run.add_argument("--commit", action="store_true", help="commit the results after a clean scan")
    run.set_defaults(handler=cmd_run)
    for name, handler in (("report", cmd_report), ("audit", cmd_audit)):
        sub = commands.add_parser(name)
        sub.add_argument("--results", help="another results directory")
        sub.set_defaults(handler=handler)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
