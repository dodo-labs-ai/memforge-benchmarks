"""Run a task's assertion on a workspace: offline, with no key, and no outcome but the four."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..common import OUTCOMES, RUN_PATH, TASKS_DIR, TIMEZONE


def run_assertion(task_id: str, workspace: Path, tmp: Path) -> dict:
    command = [
        "/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)",
        shutil.which("python3", path=RUN_PATH), str(TASKS_DIR / task_id / "assert_outcome.py"), str(workspace),
    ]
    env = {"PATH": RUN_PATH, "HOME": str(tmp), "TZ": TIMEZONE, "PYTHONDONTWRITEBYTECODE": "1", "LANG": "en_US.UTF-8"}
    try:
        result = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"outcome": "neither", "detail": "the assertion timed out after 60 seconds"}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        verdict = json.loads(lines[-1])
        if verdict.get("outcome") in OUTCOMES:
            return verdict
    except (IndexError, ValueError):
        pass
    return {"outcome": "neither", "detail": f"the assertion gave no verdict: exit {result.returncode}: {result.stderr[-300:]}"}
