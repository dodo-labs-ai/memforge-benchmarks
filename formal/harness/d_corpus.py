"""The MemForge that group D reads: one folder, with real file times, in its own Compose project.

    EXPERIMENT_MEMFORGE_REPOSITORY=PATH EXPERIMENT_MEMFORGE_COMMIT=SHA python3 -m formal.harness.d_corpus up
    python3 -m formal.harness.d_corpus configure
    python3 -m formal.harness.d_corpus sync --set govuk --size small --token-cap 3000000
    python3 -m formal.harness.d_corpus stop

It runs as project ``mfd`` on port 28777 unless EXPERIMENT_PROJECT and EXPERIMENT_API_PORT say
otherwise, and leaves every other project and volume alone. Models are set through the Settings
API. A sync waits until relation discovery is quiet and stops the project at its token cap.
"""

from __future__ import annotations

import os

os.environ.setdefault("EXPERIMENT_PROJECT", "mfd")
os.environ.setdefault("EXPERIMENT_API_PORT", "28777")

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from harness import sandbox  # noqa: E402
from harness.common import MEMFORGE_COMMIT, PROJECT  # noqa: E402
from harness.sandbox import DOCS_DIR, api, compose, relation_work_counts  # noqa: E402

from ..common import FORMAL, read_json, write_json  # noqa: E402
from ..corpus import coexist, real_times  # noqa: E402

OUT = FORMAL / "stage1" / "sync" / PROJECT
STATE = OUT / "state.json"
POLL_SECONDS = 30
QUIET_SECONDS = 60
STALL_SECONDS = 2400
_SLICE_LINE = re.compile(r"Relation discovery slice attempted=(\d+) completed=(\d+) failed=(\d+) obsolete=(\d+) pairs=(\d+) llm_calls=(\d+)")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generation_usage() -> dict:
    """Generation calls and tokens per operation, from MemForge's own log."""
    operations: dict[str, dict] = {}
    for model in sandbox.model_usage().values():
        for name, calls in model["operations"].items():
            operations.setdefault(name, {"calls": 0})["calls"] += calls
        operations.setdefault("_total", {"prompt_tokens": 0, "completion_tokens": 0, "unreported_calls": 0})
        for key in ("prompt_tokens", "completion_tokens", "unreported_calls"):
            operations["_total"][key] += model[key]
    return operations


def generation_tokens() -> int:
    total = generation_usage().get("_total", {})
    return total.get("prompt_tokens", 0) + total.get("completion_tokens", 0)


def relation_slices() -> dict:
    lines = compose("logs", "--no-color", "--no-log-prefix", "api", capture=True).stdout
    totals = Counter()
    for match in _SLICE_LINE.finditer(lines):
        totals.update(dict(zip(("attempted", "completed", "failed", "obsolete", "pairs", "llm_calls"), map(int, match.groups()))))
    return dict(totals)


def load_state() -> dict:
    return read_json(STATE) if STATE.exists() else {}


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{now()} {message}\n")
    print(message, flush=True)


def up() -> None:
    sandbox.clone()
    sandbox.write_inputs()
    compose("build", "api")
    compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "300", "api")
    write_json(STATE, {"project": PROJECT, "memforge_commit": MEMFORGE_COMMIT, "started_at": now()})
    log(f"up: {PROJECT} at {MEMFORGE_COMMIT}")


def configure() -> None:
    state = load_state()
    state["models"] = sandbox.configure_models()
    write_json(STATE, state)


def sync(set_name: str, size: str, token_cap: int) -> int:
    state = load_state()
    arrangements = {task["id"]: coexist.arrangement_of(task["id"]) for task in coexist.tasks_of(set_name)}
    placed = coexist.materialize(DOCS_DIR, set_name, size, arrangements, times=real_times.times_of(set_name, coexist.layout(set_name, size, arrangements)))
    if "source_id" not in state:
        state["source_id"] = api("POST", "/api/v1/sources", {"type": "local_markdown", "name": "Team docs", "access_policy": "private", "config": {"root": sandbox.DOCS_IN_CONTAINER}})["id"]
    state.update({"set": set_name, "size": size, "documents": len(placed), "sync_started_at": now()})
    write_json(STATE, state)
    api("POST", f"/api/v1/sources/{state['source_id']}/sync", expect=(202,))
    compose("exec", "-T", "-e", "MEMFORGE_API_URL=http://127.0.0.1:8765", "api", "memforge", "adapter", "daemon", "once")
    log(f"sync: {len(placed)} documents placed, sync requested")
    last_seen, last_change, quiet_since = None, time.monotonic(), None
    while True:
        source = sandbox._source(state["source_id"])
        run, counts, tokens = source.get("sync") or {}, relation_work_counts(), generation_tokens()
        if tokens >= token_cap:
            compose("stop")
            log(f"sync: stopped at the cap, {tokens} generation tokens")
            return 3
        seen = (tokens, json.dumps(counts, sort_keys=True), source.get("memory_count"))
        if seen != last_seen:
            last_seen, last_change = seen, time.monotonic()
            log(f"sync: {run.get('status')} documents {source.get('doc_count')} memories {source.get('memory_count')} relation work {counts} tokens {tokens}")
        if time.monotonic() - last_change >= STALL_SECONDS:
            log("sync: nothing changed for 40 minutes, recording what there is")
            break
        if run.get("status") in ("success", "partial", "failed") and not counts.get("pending") and not counts.get("running"):
            quiet_since = quiet_since or time.monotonic()
            if time.monotonic() - quiet_since >= QUIET_SECONDS:
                break
        else:
            quiet_since = None
        time.sleep(POLL_SECONDS)
    source = sandbox._source(state["source_id"])
    state.update({"sync_finished_at": now(), "sync_status": (source.get("sync") or {}).get("status"), "doc_count": source.get("doc_count"), "memory_count": source.get("memory_count"), "relation_work": relation_work_counts(), "relation_slices": relation_slices(), "generation": generation_usage()})
    write_json(STATE, state)
    log(f"sync: finished, {state['memory_count']} memories, {generation_tokens()} generation tokens")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("up")
    commands.add_parser("configure")
    commands.add_parser("stop")
    run = commands.add_parser("sync")
    run.add_argument("--set", dest="set_name", required=True)
    run.add_argument("--size", choices=("small", "large"), required=True)
    run.add_argument("--token-cap", type=int, required=True)
    args = parser.parse_args()
    if args.command == "up":
        up()
    elif args.command == "configure":
        configure()
    elif args.command == "stop":
        compose("stop")
    else:
        return sync(args.set_name, args.size, args.token_cap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
