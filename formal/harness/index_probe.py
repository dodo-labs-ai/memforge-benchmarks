"""One real run to establish how much of a long AGENTS.md reaches the model.

    python3 -m formal.harness.index_probe [--egress-check]

Codex's configuration default for `project_doc_max_bytes` is 32 KiB. This writes a 40,000
byte AGENTS.md of numbered lines into a run's repository, asks for one word, and reads the
session record to see which bytes were sent. It also lists what a bare one-line-per-file
index of each document set would weigh, the case the plan's 50-line limit is about.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from harness import parse, scan
from harness.common import load_secrets
from harness.pilot import token_counts

from ..common import MODEL, STAGE0, load_tasks, write_json
from ..corpus import coexist
from . import budget, egress
from . import home as run_home
from . import screen

WRITTEN_BYTES = 40_000
LIMIT_BYTES = 32 * 1024
PROMPT = "Reply with the single word OK. Do not run any command."
_MARKER = "INDEXLINE"


def index_text() -> str:
    lines = [f"{_MARKER}{number:05d} padding padding padding" for number in range(WRITTEN_BYTES // 38 + 2)]
    return "\n".join(lines)[:WRITTEN_BYTES]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def what_reached_the_model(rollouts: list[Path], written: str) -> dict:
    """The longest stretch of the file in any model-facing item of the session record."""
    best = ""
    where = None
    surrounding = ""
    for path in rollouts:
        for row in parse.read_jsonl(path):
            if row.get("type") not in ("response_item", "turn_context", "session_meta"):
                continue
            for text in _strings(row.get("payload")):
                if _MARKER not in text:
                    continue
                start = text.index(_MARKER)
                end = text.rindex(_MARKER)
                closing = re.search(r"[\n<]", text[end:])
                length = 0
                while start + length < len(text) and length < len(written) and text[start + length] == written[length]:
                    length += 1
                if length > len(best):
                    best, where = written[:length], f"{row.get('type')}/{(row.get('payload') or {}).get('type') or (row.get('payload') or {}).get('role')}"
                    surrounding = text[start + length : start + length + 200]
    return {
        "found_in": where,
        "bytes_of_the_file_that_reached_the_model": len(best.encode()),
        "last_line_number_reached": re.findall(rf"{_MARKER}(\d{{5}})", best)[-1] if best else None,
        "text_right_after_the_cut": surrounding,
        "says_it_was_truncated": bool(re.search(r"truncat|omitted|\.\.\.", surrounding, re.IGNORECASE)),
    }


def bare_index_weights() -> dict:
    """Bytes of `- path` lines for each large set, the smallest full listing an index could be."""
    weights = {}
    for set_name in ("govuk", "gitlab", "django", "otel", "grpc", "rustforge"):
        synced = {task["id"]: coexist.run_arrangement(task["id"], "D", "large", 1) for task in coexist.tasks_of(set_name)}
        rows = coexist.layout(set_name, "large", synced)
        size = sum(len(f"- docs/{row['target']}\n".encode()) for row in rows)
        weights[set_name] = {"files": len(rows), "bytes_of_bare_paths": size, "fits_in_the_limit": size <= LIMIT_BYTES}
    return weights


def main(argv: list[str]) -> int:
    egress_check_only = argv == ["--egress-check"]
    secrets = load_secrets()
    endpoint, api_key = secrets["MEMFORGE_RELAY_BASE_URL"].rstrip("/"), secrets["MEMFORGE_RELAY_API_KEY"]
    scrubber = scan.Scrubber(secrets)
    if budget.total() + 200_000 >= budget.TOKEN_CAP:
        raise SystemExit("the token cap would be reached")
    dirs = run_home.new_run_dirs()
    run_home.prepare_home(dirs, "A")
    run_home.prepare_repo(dirs, "t16-rustforge-rollup-approval")
    written = index_text()
    if not egress_check_only:
        (dirs.repo / "AGENTS.md").write_text(written, encoding="utf-8")
    events_path = dirs.root / "events.jsonl"
    begun = datetime.now(timezone.utc)
    with events_path.open("wb") as events_out:
        proxy = egress.LoggingProxy(urlparse(endpoint).hostname, egress.machine_proxy())
        process = subprocess.Popen(screen.codex_argv(dirs.repo, PROMPT, endpoint), cwd=dirs.repo, env={**run_home.run_env(dirs, api_key), **proxy.env()}, stdin=subprocess.DEVNULL, stdout=events_out, stderr=subprocess.PIPE, start_new_session=True)
        watch = egress.Watch(process.pid, proxy)
        _, stderr = process.communicate(timeout=300)
        connections = watch.stop()
    run_home.kill_leftovers(dirs)
    rollouts = sorted(dirs.codex_home.glob("sessions/**/*.jsonl"))
    events = parse.parse_events(events_path)
    tokens = token_counts(events, parse.parse_rollouts(rollouts))
    reached = what_reached_the_model(rollouts, written)
    row = {
        "probe": "index_limit",
        "at": begun.isoformat(),
        "model": MODEL,
        "exit_code": process.returncode,
        "failures": [scrubber.scrub(message)[0][:300] for message in events["failures"]],
        "tokens": {**tokens, "counted_against_the_cap": "total"},
        "egress": connections,
        "final_message": scrubber.scrub(events["messages"][-1] if events["messages"] else "")[0][:200],
    }
    if egress_check_only:
        row["probe"] = "egress_check"
    with budget.PROBES.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(json.loads(scrubber.scrub(json.dumps(row, ensure_ascii=False))[0]), ensure_ascii=False) + "\n")
    if egress_check_only:
        print(json.dumps(row, indent=1))
        shutil.rmtree(dirs.root, ignore_errors=True)
        return 0 if process.returncode == 0 else 1
    report = {
        "codex_version": subprocess.run([screen.CODEX_BIN, "--version"], capture_output=True, text=True).stdout.strip(),
        "configured_value": "left at its default: no project_doc_max_bytes in the run's configuration",
        "bytes_written": len(written.encode()),
        "expected_limit_bytes": LIMIT_BYTES,
        "truncated": reached["bytes_of_the_file_that_reached_the_model"] < len(written.encode()),
        **reached,
        "lines_written": written.count("\n") + 1,
        "probe_run": row,
        "bare_path_index_by_large_set": bare_index_weights(),
    }
    write_json(STAGE0 / "index_limit.json", json.loads(scrubber.scrub(json.dumps(report, ensure_ascii=False))[0]))
    screen.log(f"index limit probe: {report['bytes_of_the_file_that_reached_the_model']} of {report['bytes_written']} bytes reached the model, {tokens['total']} tokens")
    shutil.rmtree(dirs.root, ignore_errors=True)
    print(json.dumps({key: value for key, value in report.items() if key != "bare_path_index_by_large_set"}, indent=1)[:2000])
    return 0 if process.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
