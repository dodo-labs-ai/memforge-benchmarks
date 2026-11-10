"""The sandbox MemForge: one Compose project on loopback with its own volume.

It runs a pinned commit of the public repository and takes its documents the
way the public compose smoke does: a Local Repository source over a folder
mounted into the API container, collected by one pass of the local daemon.
MemForge's code and prompts are not changed. Models are set through the Settings
API, with keys in request bodies and never in a file or a log.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from .common import (
    API_PORT,
    API_URL,
    DOCS_IN_CONTAINER,
    MEMFORGE_COMMIT,
    MEMFORGE_REPOSITORY,
    MODEL,
    PROJECT,
    REPO,
    SANDBOX_ROOT,
    SOURCE_NAME,
    CORPUS_DIR,
    corpus_manifest,
    load_secrets,
)

SOURCE_DIR = SANDBOX_ROOT / "src"
DOCS_DIR = SANDBOX_ROOT / "docs"
ENV_FILE = SANDBOX_ROOT / "mfexp.env"
OVERRIDE_FILE = SANDBOX_ROOT / "compose.override.yaml"
STATE_FILE = SANDBOX_ROOT / "state.json"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_FINISHED_SYNC = {"success", "partial"}
DEFAULT_CONTEXT_WINDOW_TOKENS = 32768
DEFAULT_MAX_OUTPUT_TOKENS = 4096


class SandboxError(RuntimeError):
    pass


# -- Docker --------------------------------------------------------------------


def _docker_env() -> dict[str, str]:
    """Only what Docker needs, so nothing in this shell reaches the project."""
    return {"HOME": os.environ["HOME"], "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "DOCKER_BUILDKIT": "1"}


def compose(*args: str, check: bool = True, capture: bool = False, stdin: str | None = None) -> subprocess.CompletedProcess:
    command = [
        "docker", "compose",
        "--project-name", PROJECT,
        "--project-directory", str(SOURCE_DIR),
        "--env-file", str(ENV_FILE),
        "-f", str(SOURCE_DIR / "compose.yaml"),
        "-f", str(OVERRIDE_FILE),
        *args,
    ]
    return subprocess.run(command, env=_docker_env(), check=check, text=True, capture_output=capture, input=stdin)


def write_inputs() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(
        f"MEMFORGE_DOCKERHUB_PREFIX={os.environ.get('MEMFORGE_DOCKERHUB_PREFIX', '')}\n"
        f"MEMFORGE_API_HOST_PORT={API_PORT}\n"
        f"MEMFORGE_ADMIN_UI_HOST_PORT={API_PORT + 1}\n",
        encoding="utf-8",
    )
    OVERRIDE_FILE.write_text(
        "services:\n"
        "  api:\n"
        "    env_file: !override\n"
        f"      - path: \"{ENV_FILE}\"\n"
        "    volumes:\n"
        "      - type: bind\n"
        f"        source: \"{DOCS_DIR}\"\n"
        f"        target: {DOCS_IN_CONTAINER}\n"
        "        read_only: true\n",
        encoding="utf-8",
    )


def place_documents(target: Path) -> None:
    """Copy the corpus with its file times; every group's copy carries the same times."""
    target.mkdir(parents=True, exist_ok=True)
    for name, document in corpus_manifest()["documents"].items():
        destination = target / name
        shutil.copyfile(CORPUS_DIR / "docs" / name, destination)
        destination.chmod(0o644)
        moment = datetime.fromisoformat(document["mtime"]).timestamp()
        os.utime(destination, (moment, moment))


def clone() -> None:
    if not (SOURCE_DIR / ".git").is_dir():
        SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", "--branch", "main", MEMFORGE_REPOSITORY, str(SOURCE_DIR)], check=True)
    subprocess.run(["git", "-C", str(SOURCE_DIR), "checkout", "--quiet", "--detach", MEMFORGE_COMMIT], check=True)


def up() -> None:
    clone()
    write_inputs()
    place_documents(DOCS_DIR)
    compose("build", "api")
    compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "300", "api")
    print(f"sandbox {PROJECT} healthy at {API_URL}")


def down() -> None:
    """Remove this project's containers, volume, network and locally built image. Nothing else."""
    compose("down", "-v", "--remove-orphans", "--rmi", "local")


_ACCESS_LINE = re.compile(
    r'^(?P<time>\S+)\s+INFO:\s+(?P<client>[0-9.]+):\d+ - "(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[0-9.]+" (?P<status>\d+)'
)


def access_requests(since: datetime, until: datetime) -> list[dict]:
    """Requests that reached the API through its published port between two moments.

    The container's own health check connects from loopback and is left out. Only
    the access lines are read, so nothing else the API logs can reach a result.
    """
    lines = compose("logs", "--no-color", "--no-log-prefix", "--timestamps", "--since", since.isoformat(), "api", capture=True).stdout
    requests = []
    for line in lines.splitlines():
        match = _ACCESS_LINE.match(line)
        if match is None or match["client"].startswith("127."):
            continue
        moment = datetime.fromisoformat(match["time"].replace("Z", "+00:00"))
        if since <= moment <= until:
            requests.append(
                {"time": moment.isoformat(), "method": match["method"], "path": match["path"].split("?")[0], "status": int(match["status"])}
            )
    return requests


_MODEL_CALL = re.compile(r"structured_llm_call (\{.*\})")


def model_usage(since: datetime | None = None) -> dict:
    """The structured model calls the API logged, with their token totals, per model."""
    args = ["logs", "--no-color", "--no-log-prefix"]
    if since is not None:
        args += ["--since", since.isoformat()]
    usage: dict[str, dict] = {}
    for line in compose(*args, "api", capture=True).stdout.splitlines():
        match = _MODEL_CALL.search(line)
        if match is None:
            continue
        try:
            call = json.loads(match.group(1))
        except ValueError:
            continue
        entry = usage.setdefault(
            str(call.get("model") or "unnamed").split("/")[-1],
            {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "unreported_calls": 0, "operations": {}},
        )
        entry["calls"] += 1
        operation = str(call.get("operation") or "unnamed")
        entry["operations"][operation] = entry["operations"].get(operation, 0) + 1
        if call.get("prompt_tokens") is None or call.get("completion_tokens") is None:
            entry["unreported_calls"] += 1
            continue
        entry["prompt_tokens"] += int(call["prompt_tokens"])
        entry["completion_tokens"] += int(call["completion_tokens"])
    return usage


# -- HTTP ----------------------------------------------------------------------


def api(method: str, path: str, payload=None, *, expect=(200,), timeout: float = 120.0):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{API_URL}{path}", data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read()
    if status not in expect:
        raise SandboxError(f"{method} {path} answered {status}: {body[:300].decode('utf-8', 'replace')}")
    return json.loads(body) if body else None


def _wait(check, *, timeout: float, interval: float, what: str):
    deadline = time.monotonic() + timeout
    while True:
        outcome = check()
        if outcome is not None:
            return outcome
        if time.monotonic() >= deadline:
            raise SandboxError(f"{what} did not finish within {timeout:g}s")
        time.sleep(interval)


# -- Models --------------------------------------------------------------------


def _configure_kind(kind: str, provider: str, model: str, endpoint: str | None, key: str, descriptors: dict) -> str:
    descriptor = descriptors[provider]
    if kind not in descriptor.get("kinds", []):
        raise SandboxError(f"{provider} serves no {kind} models")
    discovery = api(
        "POST",
        f"/api/v1/model-settings/{kind}/discover-models",
        {"provider": provider, "endpoint": endpoint, "auth_strategy": "api_key", "api_key": key},
    )
    if not discovery.get("ok"):
        raise SandboxError(f"listing the {kind} models failed: {discovery.get('error_code') or 'not ok'}")
    listed = next(
        (option for option in discovery.get("models", []) if option.get("id") == model), {}
    )
    body = {"provider": provider, "model_id": model, "endpoint": endpoint, "auth_strategy": "api_key", "api_key": key}
    if kind == "generation":
        body["token_limits"] = {
            "context_window_tokens": listed.get("context_window_tokens") or DEFAULT_CONTEXT_WINDOW_TOKENS,
            "max_output_tokens": listed.get("max_output_tokens") or DEFAULT_MAX_OUTPUT_TOKENS,
        }
        if listed.get("native_schema") is not None:
            body["native_schema"] = listed["native_schema"]
    api("PUT", f"/api/v1/model-settings/{kind}/candidate", body)
    outcome = api("POST", f"/api/v1/model-settings/{kind}/candidate/validate", timeout=300)
    if not outcome.get("passed"):
        raise SandboxError(f"{kind} model {model} failed validation: {outcome.get('error_code')}")
    if outcome.get("reindex_required"):
        api("POST", "/api/v1/model-settings/vector-index/reindex", expect=(202,))

        def rebuilt():
            index = api("GET", "/api/v1/model-settings/vector-index")
            rebuild = index.get("reindex") or {}
            if rebuild.get("state") == "failed":
                raise SandboxError(f"the vector index rebuild failed: {rebuild.get('error_code')}")
            return True if rebuild.get("state") == "succeeded" and index.get("serves_search") else None

        _wait(rebuilt, timeout=300, interval=2, what="the vector index rebuild")
    elif not outcome.get("promoted"):
        raise SandboxError(f"{kind} model passed validation but was not put to use")
    return f"{kind} {model} validated"


def configure_models() -> dict:
    keys = load_secrets()
    descriptors = {item["id"]: item for item in api("GET", "/api/v1/model-settings/providers")["providers"]}
    generation_model = keys["MEMFORGE_RELAY_MODEL"]
    notes = [
        _configure_kind(
            "generation", "openai_compatible", generation_model,
            keys["MEMFORGE_RELAY_BASE_URL"].rstrip("/"), keys["MEMFORGE_RELAY_API_KEY"], descriptors,
        ),
        _configure_kind(
            "embedding", "openrouter", "openai/text-embedding-3-small", None, keys["OPENROUTER_API_KEY"], descriptors,
        ),
    ]
    print("; ".join(notes))
    return {
        "generation": {"provider": "openai_compatible", "model": generation_model},
        "embedding": {"provider": "openrouter", "model": "openai/text-embedding-3-small"},
    }


# -- Documents -------------------------------------------------------------------


def _source(source_id: str) -> dict:
    for source in api("GET", "/api/v1/sources").get("data", []):
        if source.get("id") == source_id:
            return source
    raise SandboxError(f"source {source_id} is not listed")


def sync_documents(*, timeout: float = 1500) -> dict:
    created = api(
        "POST",
        "/api/v1/sources",
        {"type": "local_markdown", "name": SOURCE_NAME, "access_policy": "private", "config": {"root": DOCS_IN_CONTAINER}},
    )
    source_id = created["id"]
    api("POST", f"/api/v1/sources/{source_id}/sync", expect=(202,))
    compose("exec", "-T", "-e", "MEMFORGE_API_URL=http://127.0.0.1:8765", "api", "memforge", "adapter", "daemon", "once")

    def synced():
        source = _source(source_id)
        sync = source.get("sync") or {}
        if sync.get("status") == "failed":
            raise SandboxError(f"the sync failed: {sync.get('error_message')}")
        return source if sync.get("status") in _FINISHED_SYNC else None

    source = _wait(synced, timeout=timeout, interval=5, what="the source sync")
    print(f"sync {source['sync']['status']}: {source['doc_count']} documents, {source['memory_count']} memories")
    return {"source_id": source_id, "sync": source["sync"], "doc_count": source["doc_count"], "memory_count": source["memory_count"]}


_WORK_QUERY = """
import glob, json, sqlite3
path = next(iter(glob.glob('/data/**/*.db', recursive=True) + glob.glob('/data/*.sqlite*')), None)
paths = [p for p in glob.glob('/data/**/*', recursive=True) if p.endswith(('.db', '.sqlite', '.sqlite3'))]
found = {}
for p in paths:
    db = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
    try:
        rows = db.execute('select status, count(*) from relation_discovery_work group by status').fetchall()
    except sqlite3.Error:
        continue
    finally:
        db.close()
    found = dict(rows)
    break
print(json.dumps(found))
"""


def relation_work_counts() -> dict:
    """Relation discovery work by status, read-only from the sandbox database."""
    output = compose("exec", "-T", "api", "python", "-c", _WORK_QUERY, capture=True).stdout
    return json.loads(output.strip().splitlines()[-1])


def wait_for_relation_discovery(*, timeout: float = 1200, settle: float = 30) -> dict:
    """Wait until no relation discovery work is pending, running or waiting for a retry."""
    open_states = {"pending", "running", "failed"}
    quiet_since = [None]

    def finished():
        counts = relation_work_counts()
        if not counts or any(counts.get(state) for state in open_states - {"failed"}):
            quiet_since[0] = None
            return None
        if counts.get("failed"):
            # A failed item may be waiting for its scheduled retry, or exhausted.
            exhausted = api("GET", "/api/v1/relation-discovery/work?state=exhausted&limit=200").get("data") or []
            if len(exhausted) < counts["failed"]:
                quiet_since[0] = None
                return None
        quiet_since[0] = quiet_since[0] or time.monotonic()
        return counts if time.monotonic() - quiet_since[0] >= settle else None

    counts = _wait(finished, timeout=timeout, interval=10, what="relation discovery")
    print(f"relation discovery finished: {counts}")
    return counts


# -- What MemForge made of the documents -----------------------------------------


def memories_with_relations() -> list[dict]:
    listed, offset = [], 0
    while True:
        page = api("GET", f"/api/v1/memories?limit=100&offset={offset}")
        rows = page["data"]
        listed += rows
        if len(rows) < 100:
            break
        offset += 100
    return [api("GET", f"/api/v1/memories/{row['id']}") for row in listed]


def _document_of(memory: dict) -> tuple[str | None, str | None]:
    """The corpus file a memory came from and the document time MemForge holds for it."""
    for evidence in memory.get("evidence") or []:
        document = evidence.get("document") or {}
        url = document.get("source_url") or ""
        if url:
            return url.rsplit("/", 1)[-1], document.get("source_updated_at")
    return None, None


def task_summary(memories: list[dict], relations: list[dict]) -> dict:
    """Per task: whether both documents gave memories, whether they are linked, and how."""
    manifest = corpus_manifest()["documents"]
    by_doc: dict[str, list[dict]] = {}
    times: dict[str, str | None] = {}
    for memory in memories:
        name, moment = _document_of(memory)
        if name is None:
            continue
        by_doc.setdefault(name, []).append(
            {"id": memory["id"], "type": memory["memory_type"], "status": memory["status"], "content": memory["content"]}
        )
        times[name] = moment
    summary: dict[str, dict] = {}
    for name, document in manifest.items():
        entry = summary.setdefault(document["task"], {"links": []})
        entry[document["role"]] = {
            "file": name,
            "file_time_set_by_harness": document["mtime"],
            "document_time_memforge_saw": times.get(name),
            "memories": by_doc.get(name, []),
        }
    role_of = {
        item["id"]: (document["task"], document["role"])
        for name, document in manifest.items()
        for item in by_doc.get(name, [])
    }
    for relation in relations:
        ids = [item["memory_id"] for item in relation["memories"]]
        tasks = {role_of[memory_id][0] for memory_id in ids if memory_id in role_of}
        roles = {role_of[memory_id][1] for memory_id in ids if memory_id in role_of}
        for task in tasks:
            summary[task]["links"].append(
                {
                    "label": relation["label"],
                    "newer_memory_id": relation.get("newer_memory_id"),
                    "memory_ids": ids,
                    "evidence_times": [item.get("evidence_time") for item in relation["memories"]],
                    "links_stale_and_current": roles == {"stale", "current"},
                }
            )
    for entry in summary.values():
        entry["both_documents_gave_memories"] = bool(entry["stale"]["memories"]) and bool(entry["current"]["memories"])
        spanning = [link for link in entry["links"] if link["links_stale_and_current"]]
        entry["stale_and_current_linked"] = bool(spanning)
        entry["labels_between_stale_and_current"] = sorted({link["label"] for link in spanning})
    return summary


def snapshot() -> dict:
    """Everything the report needs about the sandbox, free of keys and endpoints."""
    memories = memories_with_relations()
    relations = api("GET", "/api/v1/memories/relations?limit=200")["data"]
    settings = api("GET", "/api/v1/model-settings")
    active = {
        kind: {key: (settings[kind].get("active") or {}).get(key) for key in ("provider", "model_id", "state")}
        for kind in ("generation", "embedding")
    }
    return {
        "memforge_commit": subprocess.check_output(["git", "-C", str(SOURCE_DIR), "rev-parse", "HEAD"], text=True).strip(),
        "models": active,
        "sources": [
            {key: source.get(key) for key in ("id", "name", "type", "doc_count", "memory_count", "sync")}
            for source in api("GET", "/api/v1/sources").get("data", [])
        ],
        "relation_work": relation_work_counts(),
        "model_usage": model_usage(),
        "memories": memories,
        "relations": relations,
        "by_task": task_summary(memories, relations),
    }


def fingerprint(state: dict) -> list:
    """What a run must leave unchanged: every memory's identity and content, and every link."""
    return [
        sorted((memory["id"], memory["content_hash"], memory["status"]) for memory in state["memories"]),
        sorted((relation["label"], relation.get("newer_memory_id"), tuple(sorted(item["memory_id"] for item in relation["memories"]))) for relation in state["relations"]),
    ]


def verify() -> dict:
    """Refuse a sandbox that does not meet the design; return its snapshot when it does."""
    state = snapshot()
    problems = []
    if state["memforge_commit"] != MEMFORGE_COMMIT:
        problems.append(f"sandbox runs {state['memforge_commit']}, not the pinned commit")
    generation, embedding = state["models"]["generation"], state["models"]["embedding"]
    if (generation["provider"], generation["model_id"], generation["state"]) != ("openai_compatible", MODEL, "ready"):
        problems.append(f"generation model is {generation}")
    if (embedding["provider"], embedding["model_id"], embedding["state"]) != ("openrouter", "openai/text-embedding-3-small", "ready"):
        problems.append(f"embedding model is {embedding}")
    if [source["name"] for source in state["sources"]] != [SOURCE_NAME]:
        problems.append(f"sources are {[source['name'] for source in state['sources']]}")
    elif state["sources"][0]["sync"]["status"] != "success":
        problems.append(f"sync status is {state['sources'][0]['sync']['status']}")
    open_work = {key: value for key, value in state["relation_work"].items() if key != "completed" and value}
    if open_work:
        problems.append(f"relation discovery has open work: {open_work}")
    for name in corpus_manifest()["documents"]:
        if (DOCS_DIR / name).read_bytes() != (CORPUS_DIR / "docs" / name).read_bytes():
            problems.append(f"{name} in the sandbox differs from the corpus")
    if problems:
        raise SandboxError("; ".join(problems))
    return state


def main(argv: list[str]) -> int:
    command = argv[0] if argv else ""
    if command == "up":
        up()
    elif command == "down":
        down()
    elif command == "prepare":
        models = configure_models()
        synced = sync_documents()
        counts = wait_for_relation_discovery()
        STATE_FILE.write_text(json.dumps({"models": models, "sync": synced, "relation_work": counts}, indent=2))
    elif command == "verify":
        state = verify()
        print(json.dumps({"commit": state["memforge_commit"], "models": state["models"], "relation_work": state["relation_work"]}, indent=2))
    elif command == "snapshot":
        target = Path(argv[1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(snapshot(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {target.relative_to(REPO) if target.is_relative_to(REPO) else target}")
    else:
        print("usage: python3 -m harness.sandbox up|prepare|verify|snapshot FILE|down", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
