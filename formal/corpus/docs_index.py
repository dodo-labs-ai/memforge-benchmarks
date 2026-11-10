"""The hand-written docs index that groups C1 and C2 hold as AGENTS.md.

An index a team would really keep: at most 50 lines, one line per document when the set
fits, otherwise a line for each staged pair and a line for each of the largest top-level
directories, the rest counted on one last line. Each pair has one line. C1 and C2 are the same index apart from the line of the run's own task, which
names the new revision in C1 and the old one in C2; every other pair names its new revision.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

MAX_LINES = 50
HEADING = "# Docs index"
PREAMBLE = "What the documents under `docs/` cover."
_FRONT_MATTER_TITLE = re.compile(r"\A---\n(?:.*\n)*?title:\s*[\"']?(.+?)[\"']?\s*\n(?:.*\n)*?---\n")
_HEADING = re.compile(r"^#\s+(.+?)\s*$", flags=re.MULTILINE)


def title_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    found = _FRONT_MATTER_TITLE.match(text) or _HEADING.search(text)
    return found.group(1) if found else path.name


def build(docs: Path, placed: list[dict], task_id: str, pointed_to: str, leak_tokens: list[str]) -> str:
    """The index text. `pointed_to` is the revision the line of task `task_id` names."""

    def line(item: dict) -> str:
        return f"- {title_of(docs / item['target'])}: `docs/{item['target']}`"

    pairs = [item for item in placed if item["kind"] == "revision" and item["role"] == (pointed_to if item["task"] == task_id else "new")]
    others = [item for item in placed if item["kind"] == "set"]
    lines = [HEADING, "", PREAMBLE, ""]
    if len(lines) + len(pairs) + len(others) <= MAX_LINES:
        lines += [line(item) for item in sorted((*pairs, *others), key=lambda item: item["target"])]
    else:
        lines += [line(item) for item in pairs]
        directories = Counter(item["target"].split("/")[0] if "/" in item["target"] else "." for item in others).most_common()
        room = MAX_LINES - len(lines)
        shown = directories if len(directories) <= room else directories[: room - 1]
        lines += [f"- `docs/{name}/`: {count} documents" for name, count in sorted(shown)]
        if len(shown) < len(directories):
            lines.append(f"- Other directories under `docs/`: {sum(count for _, count in directories[len(shown):])} documents")
    pair_lines = " ".join(line(item) for item in pairs).lower()
    if leaked := [token for token in leak_tokens if token.lower() in pair_lines]:
        raise SystemExit(f"the index of {task_id} gives away {leaked}")
    return "\n".join(lines) + "\n"
