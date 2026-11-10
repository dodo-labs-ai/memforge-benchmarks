"""Paths and settings of the formal experiment. The pilot's own settings stay in harness/common.py."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FORMAL = REPO / "formal"
TASKS_DIR = FORMAL / "tasks"
CORPUS_DIR = FORMAL / "corpus"
FETCHED_SETS = CORPUS_DIR / "fetched" / "sets"
FETCHED_REVISIONS = CORPUS_DIR / "fetched" / "revisions"
MANIFESTS = CORPUS_DIR / "manifests"
STAGE0 = FORMAL / "stage0"
PROGRESS_LOG = STAGE0 / "progress.log"

MODEL = "gpt-6-luna"
# What Codex 0.166.0's bundled model catalog gives gpt-6-luna as default_reasoning_level.
# formal/stage0/harness_check.json shows the same value in requests with and without the pin.
REASONING_EFFORT = "medium"
TIMEZONE = "UTC"

# The first `git` on this path is the real binary, so a sandboxed run never reaches
# Apple's /usr/bin/git shim and its xcrun noise. `python` and `python3` are the same
# Homebrew interpreter, and the shim directory comes after both.
REAL_GIT_DIR = "/Library/Developer/CommandLineTools/usr/bin"
PYTHON_LINK_DIR = "/opt/homebrew/opt/python@3.15/libexec/bin"
RUN_PATH = f"{PYTHON_LINK_DIR}:/opt/homebrew/bin:{REAL_GIT_DIR}:/usr/bin:/bin"

OUTCOMES = ("old", "new", "neither", "declined")
SCORED_NUMBERS = (1, 9, 16, 18, 20, 21, 22, 24)
RESERVE_NUMBERS = ()
DROPPED_NUMBERS = (2, 5, 6, 8, 10, 12, 23)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_tasks() -> dict[str, dict]:
    """Every task by id, in task-number order."""
    tasks = [read_json(spec) for spec in TASKS_DIR.glob("*/task.json")]
    return {task["id"]: task for task in sorted(tasks, key=lambda task: task["number"])}


def load_sets() -> dict[str, dict]:
    return read_json(CORPUS_DIR / "sets.json")["sets"]


def load_manifest(name: str) -> dict:
    return read_json(MANIFESTS / f"{name}.json")
