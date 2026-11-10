"""What the task assertions share. Standard library only, no model and no network.

An assertion classifies a finished workspace against the task's untouched `repo/`:

    new       the deliverable follows the new revision
    old       the deliverable follows the old revision
    neither   there is a deliverable, and it follows neither
    declined  no deliverable: the workspace is untouched, or only notes were written,
              or the stub the task asked to fill still raises NotImplementedError

The documents, an index and notes are never read: only code the run changed counts.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

IGNORED_DIRECTORIES = {".git", "docs", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules"}
IGNORED_FILES = {"AGENTS.md"}
NOTE_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".adoc"}
HASH_COMMENT_SUFFIXES = {"", ".sh", ".bash", ".zsh", ".py", ".rb", ".yaml", ".yml", ".mk"}
OUTCOMES = ("old", "new", "neither", "declined")


def verdict(outcome: str, detail: str) -> None:
    """Print the verdict as the last line of output and end the assertion."""
    print(json.dumps({"outcome": outcome, "detail": detail}, ensure_ascii=False))
    raise SystemExit(0)


def _files(root: Path) -> dict[str, Path]:
    found = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if IGNORED_DIRECTORIES & set(relative.parts) or relative.as_posix() in IGNORED_FILES:
            continue
        found[relative.as_posix()] = path
    return found


def changed_files(workspace: Path, baseline: Path) -> list[str]:
    """Files new or different against the task's own repository, documents left out."""
    before = _files(baseline)
    changed = []
    for name, path in sorted(_files(workspace).items()):
        if name not in before or before[name].read_bytes() != path.read_bytes():
            changed.append(name)
    return changed


def deliverables(workspace: Path, baseline: Path, suffixes: tuple[str, ...] | None = None) -> list[str]:
    """Changed files that can be a deliverable: code, not notes."""
    names = [name for name in changed_files(workspace, baseline) if Path(name).suffix.lower() not in NOTE_SUFFIXES]
    if suffixes is not None:
        names = [name for name in names if name.endswith(suffixes)]
    return names


def read(workspace: Path, name: str) -> str:
    return (workspace / name).read_text(encoding="utf-8", errors="replace")


def strip_hash_comments(text: str) -> str:
    """Whole-line and trailing `#` comments, leaving a `#` inside quotes or `${#...}` alone."""
    kept = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        quote = None
        cut = None
        for index, char in enumerate(line):
            if quote:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == "#" and (index == 0 or line[index - 1] in " \t"):
                cut = index
                break
        kept.append(line if cut is None else line[:cut])
    return "\n".join(kept)


def code_text(workspace: Path, names: list[str]) -> str:
    """The changed files' text with comments removed where the file type says how."""
    parts = []
    for name in names:
        text = read(workspace, name)
        if Path(name).suffix.lower() in HASH_COMMENT_SUFFIXES:
            text = strip_hash_comments(text)
        parts.append(text)
    return "\n".join(parts)


_HEREDOC_START = re.compile(r"(?<!<)<<-?\s*(['\"]?)(\w+)\1")
_MESSAGE_WORDS = r"echo|printf|die|fail|usage|err|error|warn|warning|abort|log|info"
_PRINTED_LINE = re.compile(r"^\s*(?:>&2\s+)?(?:echo|printf)\b.*$", re.MULTILINE)
_MESSAGE_CALL = re.compile(rf"""(?:(?<=^)|(?<=[\s;|&(]))(?:{_MESSAGE_WORDS})\s+(?:-\w+\s+)*("[^"\n]*"|'[^'\n]*')""", re.MULTILINE)
_QUOTED = re.compile(r"""\"[^"]*\"|'[^']*'""")


def without_heredocs(text: str) -> str:
    """Here-document bodies, which a script hands to a reader or a command as text."""
    kept = []
    closing = None
    for line in text.splitlines():
        if closing is not None:
            if line.strip() == closing:
                closing = None
            continue
        found = _HEREDOC_START.search(line)
        if found:
            closing = found.group(2)
        kept.append(line)
    return "\n".join(kept)


def without_printed_lines(text: str) -> str:
    """Text a script only shows to a reader: printed lines, here-documents and message helpers."""
    text = _PRINTED_LINE.sub("", without_heredocs(text))
    return _MESSAGE_CALL.sub("", text)


def without_prose_strings(text: str) -> str:
    """Quoted text with spaces in it, unless it is a kubectl command held in a variable."""

    def replace(found: re.Match) -> str:
        body = found.group(0)[1:-1]
        return found.group(0) if not re.search(r"\s", body) or body.lstrip().startswith("kubectl") else '""'

    return _QUOTED.sub(replace, text)


def join_continued_lines(text: str) -> str:
    return re.sub(r"\\\r?\n\s*", " ", text)


def load(workspace: Path, module: str):
    """Import a module from the workspace, nothing else being importable under its name."""
    if str(workspace) not in sys.path:
        sys.path.insert(0, str(workspace))
    return importlib.import_module(module)
