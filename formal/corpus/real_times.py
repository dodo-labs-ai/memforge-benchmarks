"""Each document's real last-edit time, from the commit history behind the pinned text.

    python3 -m formal.corpus.real_times fetch --sets govuk

A set document's time is the last commit touching its path at or before the set's pinned
commit, and a revision's is the same at or before its own commit. Times are the committer's
date and live in formal/corpus/real_times.json, so a run needs no network.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from ..common import CORPUS_DIR, load_manifest, load_sets, read_json, write_json
from . import coexist

TIMES_FILE = CORPUS_DIR / "real_times.json"
WORKERS = 3
ATTEMPTS = 6
RETRY_PAUSE_SECONDS = 20


def _api(query: str) -> str:
    """One GitHub API read, waiting and trying again when the API refuses it."""
    for attempt in range(1, ATTEMPTS + 1):
        result = subprocess.run(["gh", "api", "--hostname", "github.com", query], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        if attempt < ATTEMPTS:
            time.sleep(RETRY_PAUSE_SECONDS * attempt)
    raise SystemExit(f"GitHub refused {query}: {result.stderr[:300]}")


def last_edit(repo: str, commit: str, path: str) -> str:
    commits = json.loads(_api(f"repos/{repo}/commits?path={quote(path, safe='')}&sha={commit}&per_page=1"))
    if not commits:
        raise SystemExit(f"no commit touches {path} at {commit}")
    return commits[0]["commit"]["committer"]["date"]


def fetch_set(set_name: str) -> dict:
    spec = load_sets()[set_name]
    if spec["host"] != "github":
        raise SystemExit(f"{set_name} is on {spec['host']}; only GitHub history is read so far")
    paths = [row["path"] for row in load_manifest(set_name)["files"]]
    revisions = [(task["id"], role, task["revisions"][role]) for task in coexist.tasks_of(set_name) for role in ("old", "new")]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        documents = dict(zip(paths, pool.map(lambda path: last_edit(spec["repo"], spec["commit"], path), paths)))
        edits = list(pool.map(lambda row: last_edit(spec["repo"], row[2]["commit"], row[2]["path"]), revisions))
    by_task: dict[str, dict[str, str]] = {}
    for (task_id, role, _), moment in zip(revisions, edits):
        by_task.setdefault(task_id, {})[role] = moment
    for task_id, pair in by_task.items():
        if pair["old"] >= pair["new"]:
            raise SystemExit(f"{task_id}: the old revision is not older than the new one: {pair}")
    return {"commit": spec["commit"], "documents": documents, "revisions": by_task}


def times_of(set_name: str, placed: list[dict]) -> dict[str, str]:
    """Each target of a layout with its real last-edit time."""
    known = read_json(TIMES_FILE)[set_name]
    return {item["target"]: known["revisions"][item["task"]][item["role"]] if item["kind"] == "revision" else known["documents"][item["source"]] for item in placed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["fetch"])
    parser.add_argument("--sets", required=True, help="comma-separated set names")
    args = parser.parse_args(argv)
    known = read_json(TIMES_FILE) if Path(TIMES_FILE).exists() else {}
    for set_name in args.sets.split(","):
        known[set_name] = fetch_set(set_name)
        print(set_name, len(known[set_name]["documents"]), "documents", known[set_name]["revisions"])
    write_json(TIMES_FILE, known)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
