"""One isolated home and one history-free task repository per run.

The pilot's isolation holds and is reused: a fresh HOME and CODEX_HOME under an opaque
directory, an allowlist permission profile, and no network for shell commands. This adds
what the pilot's runs lacked: the real git, one `python`, and one time zone in every shell.

Codex captures a login shell's environment once and starts each command from that. A login
shell reads /etc/zprofile, whose path_helper puts the system's directories first again, so
the path is set once more in the run's own profile, which is read after it. Every shell reads
the run's .zshenv, which clears what this machine's /etc/zshenv exports and gives zsh's
here-documents a temporary directory the run may write to; the default is in /tmp.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from harness import home as pilot_home
from harness.common import TEMPLATE_HOME
from harness.home import RunDirs, new_run_dirs, workspace_diff  # noqa: F401  (reused as they are)

from ..common import REAL_GIT_DIR, RUN_PATH, TASKS_DIR, TIMEZONE

GIT_TOOLS_ROOT = str(Path(REAL_GIT_DIR).parent.parent)
CODE_TIME = "2026-10-20T09:00:00+00:00"


def config_toml(dirs: RunDirs, group: str) -> str:
    """The pilot's profile, plus read access to the directory that holds the real git."""
    base = pilot_home.config_toml(dirs, group)
    anchor = '"/opt/homebrew" = "read"\n'
    if anchor not in base:
        raise SystemExit("the pilot's permission profile changed")
    return base.replace(anchor, f'{anchor}"{GIT_TOOLS_ROOT}" = "read"\n')


def shell_profile() -> str:
    return f'export PATH="{RUN_PATH}"\nexport TZ="{TIMEZONE}"\n'


def shell_env() -> str:
    return 'unset JAVA_HOME\nexport TMPPREFIX="${TMPDIR:-/tmp}/zsh"\n'


def prepare_home(dirs: RunDirs, group: str) -> None:
    if group == "D":
        shutil.copytree(TEMPLATE_HOME / ".codex" / "plugins", dirs.codex_home / "plugins", symlinks=True)
    (dirs.codex_home / "config.toml").write_text(config_toml(dirs, group), encoding="utf-8")
    for name in (".zprofile", ".bash_profile"):
        (dirs.home / name).write_text(shell_profile(), encoding="utf-8")
    (dirs.home / ".zshenv").write_text(shell_env(), encoding="utf-8")


def _git_env(dirs: RunDirs) -> dict[str, str]:
    return {**pilot_home._git_env(dirs), "PATH": RUN_PATH, "TZ": TIMEZONE}


def _set_time(path: Path, moment: str) -> None:
    stamp = datetime.fromisoformat(moment).timestamp()
    os.utime(path, (stamp, stamp))


def prepare_repo(dirs: RunDirs, task_id: str, stage: Callable[[Path], None] | None = None) -> None:
    """A fresh copy of the task's repository with one commit and nothing above it.

    `stage` adds what the run's group holds, with the file times it chooses. Every
    directory ends on the code's time, so no directory says when the run was prepared.
    """
    shutil.copytree(TASKS_DIR / task_id / "repo", dirs.repo, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in dirs.repo.rglob("*"):
        if path.is_file():
            _set_time(path, CODE_TIME)
    if stage:
        stage(dirs.repo)
    for path in sorted(dirs.repo.rglob("*"), reverse=True):
        if path.is_dir():
            _set_time(path, CODE_TIME)
    env = _git_env(dirs)
    for command in (["git", "init", "-q", "-b", "main", "--template="], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "Initial commit"]):
        subprocess.run(command, cwd=dirs.repo, env=env, check=True, capture_output=True)
    _set_time(dirs.repo, CODE_TIME)


def kill_leftovers(dirs: RunDirs) -> None:
    """Anything still running from this run's directory, such as a command the turn left behind."""
    found = subprocess.run(["pgrep", "-f", str(dirs.root)], capture_output=True, text=True).stdout.split()
    for pid in found:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except (ProcessLookupError, ValueError, PermissionError):
            pass


def run_env(dirs: RunDirs, api_key: str | None) -> dict[str, str]:
    env = {"PATH": RUN_PATH, "HOME": str(dirs.home), "CODEX_HOME": str(dirs.codex_home), "TMPDIR": str(dirs.tmp), "TZ": TIMEZONE}
    if api_key is not None:
        env["MEMFORGE_RELAY_API_KEY"] = api_key
    return env
