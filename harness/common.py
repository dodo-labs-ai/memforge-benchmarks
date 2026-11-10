"""Paths and settings shared by the sandbox, the runner and the report."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO / "corpus"
TASKS_DIR = REPO / "tasks"
RESULTS_DIR = REPO / "results"

# The sandbox Compose project. Every Docker command in this repository names it.
PROJECT = os.environ.get("EXPERIMENT_PROJECT", "mfexp")
API_PORT = int(os.environ.get("EXPERIMENT_API_PORT", "28765"))
API_URL = f"http://127.0.0.1:{API_PORT}"
DOCS_IN_CONTAINER = "/experiment-docs"
SOURCE_NAME = "Team docs"
MEMFORGE_REPOSITORY = os.environ.get("EXPERIMENT_MEMFORGE_REPOSITORY", "https://github.com/dodo-labs-ai/mem-forge.git")
MEMFORGE_COMMIT = os.environ.get("EXPERIMENT_MEMFORGE_COMMIT", "7f0aa5e4a57cd957759912ddc60b95e2caa350bb")

# The agent under test.
CODEX_BIN = "/opt/homebrew/bin/codex"
CODEX_VERSION = "0.167.0"
MODEL = "gpt-6-luna"
PLUGIN_ID = "memory@memforge"
PLUGIN_VERSION = "0.2.0-beta.4"
# The read-only tools a run may call without a prompt. `codex exec` cannot ask, so
# every other plugin tool, including all that write memory, stays refused.
MEMORY_READ_TOOLS = ("search", "get_memory", "get_resource", "list_sources", "list_recent_memories", "list_workspaces")

# Every run works under a directory whose name says nothing about the experiment.
WORK_ROOT = Path(os.environ.get("EXPERIMENT_WORK_ROOT", "/Users/Shared/wk"))
TEMPLATE_HOME = Path(os.environ.get("EXPERIMENT_TEMPLATE_HOME", "/private/var/tmp/wk/_tpl/home"))
RUN_PATH = "/opt/homebrew/bin:/usr/bin:/bin"

GROUPS = ("A", "B", "C", "D")
RUNS_PER_CELL = 3
CONCURRENCY = 3
RUN_TIMEOUT_SECONDS = 600
MAX_RETRIES = 6
TOKEN_CAP = 60_000_000

# Exactly the variables this project reads from the env file. Nothing else in it
# is loaded into this process.
ENV_ALLOWLIST = ("MEMFORGE_RELAY_BASE_URL", "MEMFORGE_RELAY_API_KEY", "MEMFORGE_RELAY_MODEL", "OPENROUTER_API_KEY")


def temp_root() -> Path:
    """A per-user temporary directory whose path says nothing about the experiment."""
    try:
        value = subprocess.check_output(
            ["getconf", "DARWIN_USER_TEMP_DIR"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        value = ""
    return Path(value or tempfile.gettempdir())


SANDBOX_ROOT = temp_root() / PROJECT


def env_file_path() -> str:
    path = os.environ.get("EXPERIMENT_ENV_FILE", "")
    if not path:
        raise SystemExit("set EXPERIMENT_ENV_FILE to the env file holding the API keys")
    return path


def load_secrets() -> dict[str, str]:
    """The allowlisted values of the env file, for this process's own use. Never printed."""
    values: dict[str, str] = {}
    for raw in Path(env_file_path()).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key = key.strip()
        if key in ENV_ALLOWLIST:
            values[key] = value.strip().strip("'\"")
    missing = set(ENV_ALLOWLIST) - set(values)
    if missing:
        raise SystemExit(f"the env file lacks {sorted(missing)}")
    return values


def endpoint_host(secrets: dict[str, str]) -> str:
    return re.sub(r"^https?://", "", secrets["MEMFORGE_RELAY_BASE_URL"]).split("/")[0]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def corpus_manifest() -> dict:
    return read_json(CORPUS_DIR / "manifest.json")


def load_tasks() -> dict[str, dict]:
    tasks = {}
    for spec in sorted(TASKS_DIR.glob("*/task.json")):
        task = read_json(spec)
        tasks[task["id"]] = task
    return tasks
