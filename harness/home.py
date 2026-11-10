"""One isolated Codex home and one history-free task repository per run.

Every run works under ``WORK_ROOT/<opaque id>``: the name tells the agent nothing
about the group or the experiment, and no parent directory is a repository. Group D
copies the plugin out of a template home that was installed through the marketplace
path users take; the copy leaves out the marketplace checkout, whose tree holds the
same synthetic documents the experiment is about.

Permissions are an allowlist. A run reads the system, Homebrew's tools and its own
home, and writes its repository and its own temporary directory. The developer's
home, the sandbox's document folder, this repository and every other run are outside
it, and shell commands have no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets as secrets_module
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .common import (
    API_URL,
    CODEX_BIN,
    CORPUS_DIR,
    MEMORY_READ_TOOLS,
    PLUGIN_ID,
    PLUGIN_VERSION,
    RUN_PATH,
    TASKS_DIR,
    TEMPLATE_HOME,
    WORK_ROOT,
    corpus_manifest,
)

# File time for everything in a task repository that is not a document.
CODE_TIME = "2026-10-20T09:00:00+00:00"
COMMIT_DATE = "2026-10-20T09:00:00+00:00"
PLUGIN_CACHE = Path(".codex/plugins/cache/memforge/memory") / PLUGIN_VERSION


@dataclass(frozen=True)
class RunDirs:
    root: Path
    home: Path
    repo: Path
    tmp: Path

    @property
    def codex_home(self) -> Path:
        return self.home / ".codex"


def new_run_dirs() -> RunDirs:
    root = WORK_ROOT / f"r{secrets_module.token_hex(4)}"
    dirs = RunDirs(root, root / "home", root / "repo", root / "tmp")
    dirs.tmp.mkdir(parents=True)
    dirs.codex_home.mkdir(parents=True)
    return dirs


def config_toml(dirs: RunDirs, group: str, *, plugin_target: bool = True) -> str:
    """The run's config.toml. Only group D differs, by the plugin and its target."""
    lines = ['default_permissions = "iso"', ""]
    if group == "D":
        if plugin_target:
            # The plugin's documented setting. Codex warns that it does not know this
            # table and hands the MCP process no variable of its own, so the plugin
            # reads the origin from here.
            lines += ["[memforge]", f'MEMFORGE_API_URL = "{API_URL}"', ""]
        lines += [f'[plugins."{PLUGIN_ID}"]', "enabled = true", ""]
        for tool in MEMORY_READ_TOOLS:
            lines += [f'[plugins."{PLUGIN_ID}".mcp_servers.memforge.tools.{tool}]', 'approval_mode = "approve"', ""]
    lines += [
        "[permissions.iso.filesystem]",
        '":minimal" = "read"',
        '"/opt/homebrew" = "read"',
        f'"{dirs.home}" = "read"',
        f'"{dirs.codex_home}/.tmp" = "none"',
        f'"{dirs.tmp}" = "write"',
        '"/private/tmp" = "none"',
        '"/private/var/tmp" = "none"',
        '":project_roots" = { "." = "write" }',
        "",
        "[permissions.iso.network]",
        "enabled = false",
        "",
    ]
    return "\n".join(lines)


def prepare_home(dirs: RunDirs, group: str) -> None:
    if group == "D":
        shutil.copytree(TEMPLATE_HOME / ".codex" / "plugins", dirs.codex_home / "plugins", symlinks=True)
    (dirs.codex_home / "config.toml").write_text(config_toml(dirs, group), encoding="utf-8")


def _set_time(path: Path, moment: str) -> None:
    stamp = datetime.fromisoformat(moment).timestamp()
    os.utime(path, (stamp, stamp))


def place_documents(target: Path) -> None:
    """The corpus with its file times; every group that has documents holds the same ones."""
    target.mkdir(parents=True, exist_ok=True)
    for name, document in corpus_manifest()["documents"].items():
        destination = target / name
        shutil.copyfile(CORPUS_DIR / "docs" / name, destination)
        destination.chmod(0o644)
        _set_time(destination, document["mtime"])


def _git_env(dirs: RunDirs) -> dict[str, str]:
    return {
        "PATH": RUN_PATH,
        "HOME": str(dirs.tmp),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "dev",
        "GIT_AUTHOR_EMAIL": "dev@example.com",
        "GIT_COMMITTER_NAME": "dev",
        "GIT_COMMITTER_EMAIL": "dev@example.com",
        "GIT_AUTHOR_DATE": COMMIT_DATE,
        "GIT_COMMITTER_DATE": COMMIT_DATE,
    }


def prepare_repo(dirs: RunDirs, task_id: str, group: str) -> None:
    """A fresh copy of the task repository with one commit and nothing above it."""
    shutil.copytree(TASKS_DIR / task_id / "repo", dirs.repo, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if group in ("B", "C"):
        place_documents(dirs.repo / "docs")
    if group == "C":
        shutil.copyfile(CORPUS_DIR / "AGENTS.md", dirs.repo / "AGENTS.md")
    for path in sorted(dirs.repo.rglob("*"), reverse=True):
        if path.parent.name == "docs" and path.is_file():
            continue
        _set_time(path, CODE_TIME)
    env = _git_env(dirs)
    for command in (["git", "init", "-q", "-b", "main", "--template="], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "Initial commit"]):
        subprocess.run(command, cwd=dirs.repo, env=env, check=True, capture_output=True)


def workspace_diff(dirs: RunDirs) -> str:
    """Everything the run changed against the one commit, untracked files included."""
    env = _git_env(dirs)
    subprocess.run(["git", "add", "-A", "-N"], cwd=dirs.repo, env=env, capture_output=True)
    result = subprocess.run(["git", "diff", "--no-color", "HEAD"], cwd=dirs.repo, env=env, capture_output=True, text=True)
    return result.stdout


def tree_hash(root: Path) -> str:
    """A digest of a directory's files, ignoring byte code the interpreter leaves behind."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def plugin_tree_hash(home: Path) -> str:
    return tree_hash(home / PLUGIN_CACHE)


def check_template() -> dict:
    """The template home holds the marketplace install, at the expected version, unchanged."""
    marketplace = TEMPLATE_HOME / ".codex" / ".tmp" / "marketplaces" / "memforge"
    cache = TEMPLATE_HOME / PLUGIN_CACHE
    if not cache.is_dir():
        raise SystemExit(f"no plugin {PLUGIN_VERSION} in the template home; run: python3 -m harness.home template")
    env = {"PATH": RUN_PATH, "HOME": str(TEMPLATE_HOME), "CODEX_HOME": str(TEMPLATE_HOME / ".codex")}
    listed = json.loads(
        subprocess.run([CODEX_BIN, "plugin", "list", "--json", "--marketplace", "memforge", "--available"], env=env, capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL).stdout
    )
    server = json.loads(
        subprocess.run([CODEX_BIN, "mcp", "get", "memforge", "--json"], env=env, capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL).stdout
    )
    installed = listed["installed"][0]
    return {
        "plugin_id": installed["pluginId"],
        "version": installed["version"],
        "installed": installed["installed"],
        "marketplace_source": installed["marketplaceSource"],
        "marketplace_commit": subprocess.check_output(["git", "-C", str(marketplace), "rev-parse", "HEAD"], text=True).strip(),
        "cache_matches_marketplace_checkout": tree_hash(cache) == tree_hash(marketplace / "integrations" / "codex" / "memforge-memory"),
        "plugin_tree_sha256": tree_hash(cache),
        "mcp_command": server["transport"]["command"],
        "mcp_args": server["transport"]["args"],
        "mcp_env_names": sorted(server["transport"]["env"]),
    }


def build_template() -> None:
    """Install the plugin the way a user does, from the public marketplace at its release tag."""
    TEMPLATE_HOME.mkdir(parents=True, exist_ok=True)
    env = {"PATH": RUN_PATH, "HOME": str(TEMPLATE_HOME), "CODEX_HOME": str(TEMPLATE_HOME / ".codex")}
    (TEMPLATE_HOME / ".codex").mkdir(exist_ok=True)
    source = f"dodo-labs-ai/mem-forge@memforge-memory-v{PLUGIN_VERSION}"
    subprocess.run([CODEX_BIN, "plugin", "marketplace", "add", source], env=env, check=True, stdin=subprocess.DEVNULL)
    subprocess.run([CODEX_BIN, "plugin", "add", PLUGIN_ID], env=env, check=True, stdin=subprocess.DEVNULL)


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["template"]:
        build_template()
    print(json.dumps(check_template(), indent=2))
