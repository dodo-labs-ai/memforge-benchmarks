"""Stage the old and new revisions side by side under names that say nothing about them.

    python3 -m formal.corpus.coexist plan [--memforge PATH_TO_A_CLONE]

The rule, written as code here and recorded in formal/stage0/coexistence_plan.json:

Names. Each task has two neutral file names of the same style, in the directory its
document came from. Neither says which revision it holds, and a word of the prompt may
appear in a name only if both names hold it, because an agent picks documents by file
name. `plan` refuses names that break this. `arrangement` 0 gives the old revision the
first name and the new revision the second; arrangement 1 swaps them. The document's own
path is taken out of the set, so no third copy exists. Text is verbatim.

Arrangement. Each task keeps one arrangement in every group and repetition, its position
mod 2. MemForge syncs a folder once, so group D cannot rotate, and a fixed arrangement keeps
every within-task difference free of a difference in file names.

Small set. 30 documents of a set: every pair from that set, reserves included so that
promoting a reserve changes nothing already synced, and the rest drawn from the set's
other documents by ranking them on sha256(seed/set/path), leaving out any document that
states a task's old or new rule, so that the small set tests the pair alone. A dropped task
has no pair: its document stays in the set as any other document.

Large set. Every document of the set plus every pair, so it contains the small set
under the same paths. MemForge continues syncing the same folder as the set grows, and
any size between the two is the same ranking cut further down.

File times. All documents and all code get one fixed time, except in B-t and in the folder
group D syncs, where each document carries its real last-edit time (formal/corpus/real_times.py).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..common import FETCHED_REVISIONS, FETCHED_SETS, SCORED_NUMBERS, STAGE0, load_manifest, load_sets, load_tasks, read_json, write_json

SMALL_SET_SIZE = 30
SMALL_SET_SEED = "stale-doc-formal-2026-11-05"
UNIFORM_TIME = "2026-10-20T09:00:00+00:00"
# Every condition that holds documents, in a fixed order. Group A holds none.
CONDITIONS = (
    ("B", "small"), ("B", "large"), ("B-t", "large"),
    ("C1", "small"), ("C1", "large"), ("C2", "small"), ("C2", "large"),
    ("D", "small"), ("D", "large"),
)
REPETITIONS = (1, 2, 3)
NAME_SUFFIXES = (".html.md", ".md", ".txt")
COMMON_WORDS = {"the", "and", "for", "with", "our", "you", "this", "that"}
FRESHNESS_WORDS = {"old", "new", "current", "latest", "legacy", "deprecated", "stale", "outdated", "archive", "draft"}


def task_position(task_id: str) -> int:
    """A task's place among the staged tasks, by task number."""
    return [task["id"] for task in load_tasks().values() if task["role"] != "dropped"].index(task_id)


def arrangement_of(task_id: str) -> int:
    return task_position(task_id) % 2


def names_for(task: dict, arrangement: int) -> dict[str, str]:
    first, second = task["neutral_names"]
    return {"old": first, "new": second} if arrangement == 0 else {"old": second, "new": first}


def _relative_to_root(path: str, root: str) -> str:
    return path[len(root) + 1:] if root else path


def sets_in_use() -> list[str]:
    """The document sets that stage at least one task."""
    return [set_name for set_name in load_sets() if tasks_of(set_name)]


def tasks_of(set_name: str) -> list[dict]:
    """The tasks staged in a set. A dropped task stages nothing."""
    return [task for task in load_tasks().values() if task["doc_set"] == set_name and task["role"] != "dropped"]


def _words(text: str) -> set[str]:
    return {word for word in re.split(r"[^a-z0-9]+", text.lower()) if len(word) >= 3} - COMMON_WORDS


def _same_word(one: str, other: str) -> bool:
    return one == other or (min(len(one), len(other)) >= 4 and (one.startswith(other) or other.startswith(one)))


def _basename_words(name: str) -> set[str]:
    base = Path(name).name
    for suffix in NAME_SUFFIXES:
        base = base.removesuffix(suffix)
    return _words(base)


def name_problems(task: dict) -> list[str]:
    """Why a task's two names could steer an agent: a word only one of them shares with the prompt, or another directory."""
    first, second = task["neutral_names"]
    prompt = _words(task["prompt"])
    problems = []
    for name, other in ((first, second), (second, first)):
        mine, theirs = _basename_words(name), _basename_words(other)
        problems += [f"{name} says how fresh it is: {word}" for word in sorted(mine & FRESHNESS_WORDS)]
        for word in sorted(mine - theirs):
            if any(_same_word(word, used) for used in prompt):
                problems.append(f"{name} alone echoes the prompt: {word}")
    root = load_sets()[task["doc_set"]]["root"]
    directories = {Path(first).parent.as_posix(), Path(second).parent.as_posix()}
    source = Path(_relative_to_root(task["revisions"]["new"]["path"], root)).parent.as_posix()
    if directories != {source}:
        problems.append(f"the names are in {sorted(directories)}, and the document came from {source}")
    return problems


def pair_sources(set_name: str) -> set[str]:
    """The paths in the pinned set that the staged pairs replace."""
    return {task["revisions"][role]["path"] for task in tasks_of(set_name) for role in ("old", "new")}


def ranked_documents(set_name: str) -> list[str]:
    """The set's own documents in draw order."""
    others = [row["path"] for row in load_manifest(set_name)["files"] if row["path"] not in pair_sources(set_name)]
    return sorted(others, key=lambda path: hashlib.sha256(f"{SMALL_SET_SEED}/{set_name}/{path}".encode()).hexdigest())


def states_a_task_rule(set_name: str, path: str) -> bool:
    """Whether a document of the set states the old or new rule of a task staged in it."""
    text = (FETCHED_SETS / set_name / path).read_text(encoding="utf-8", errors="replace")
    patterns = (pattern["regex"] for task in tasks_of(set_name) for role in ("old", "new") for pattern in task["contamination"][role])
    return any(re.search(regex, text, flags=re.MULTILINE) for regex in patterns)


def small_selection(set_name: str) -> list[str]:
    """The set's own documents drawn into the small set, in draw order."""
    eligible = [path for path in ranked_documents(set_name) if not states_a_task_rule(set_name, path)]
    return eligible[: SMALL_SET_SIZE - 2 * len(tasks_of(set_name))]


def revision_file(task: dict, role: str) -> Path:
    return FETCHED_REVISIONS / task["id"] / f"{role}{Path(task['revisions'][role]['path']).suffix}"


def layout(set_name: str, size: str | int, arrangements: dict[str, int]) -> list[dict]:
    """Every file of a folder of a named size or a number of files: where it goes and where its text comes from."""
    spec = load_sets()[set_name]
    manifest = {row["path"]: row for row in load_manifest(set_name)["files"]}
    if size == "small":
        chosen = small_selection(set_name)
    elif size == "large":
        chosen = [path for path in manifest if path not in pair_sources(set_name)]
    else:
        chosen = ranked_documents(set_name)[: size - 2 * len(tasks_of(set_name))]
    placed = [{"target": _relative_to_root(path, spec["root"]), "kind": "set", "source": path, "sha256": manifest[path]["sha256"]} for path in chosen]
    revisions = {(row["task"], row["role"]): row for row in read_json(FETCHED_REVISIONS.parent.parent / "revisions.json")["revisions"]}
    for task in tasks_of(set_name):
        for role, name in names_for(task, arrangements[task["id"]]).items():
            placed.append({"target": name, "kind": "revision", "task": task["id"], "role": role, "source": task["revisions"][role]["path"], "sha256": revisions[(task["id"], role)]["sha256"]})
    targets = [item["target"] for item in placed]
    if len(set(targets)) != len(targets):
        raise SystemExit(f"two files of {set_name} {size} have one name")
    return sorted(placed, key=lambda item: item["target"])


def materialize(target: Path, set_name: str, size: str | int, arrangements: dict[str, int], *, times: dict[str, str] | None = None) -> list[dict]:
    """Write a folder with verbatim text and return its layout. `times` gives each target its own file time; without it all share one."""
    tasks = load_tasks()
    placed = layout(set_name, size, arrangements)
    for item in placed:
        source = revision_file(tasks[item["task"]], item["role"]) if item["kind"] == "revision" else FETCHED_SETS / set_name / item["source"]
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise SystemExit(f"{item['source']} is not the pinned text")
        destination = target / item["target"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o644)
        stamp = datetime.fromisoformat(times[item["target"]] if times else UNIFORM_TIME).timestamp()
        os.utime(destination, (stamp, stamp))
    return placed


def rotation_table() -> list[dict]:
    rows = []
    for task_id, task in load_tasks().items():
        if task["role"] == "dropped":
            continue
        for group, size in CONDITIONS:
            for repetition in REPETITIONS:
                arrangement = arrangement_of(task_id)
                names = names_for(task, arrangement)
                rows.append({"task": task_id, "group": group, "size": size, "rep": repetition, "arrangement": arrangement, "old_name": names["old"], "new_name": names["new"]})
    return rows


def balance(rows: list[dict]) -> dict:
    tasks = load_tasks()
    scored = [row for row in rows if tasks[row["task"]]["number"] in SCORED_NUMBERS]

    def split(items) -> list[int]:
        counts = Counter(item["arrangement"] for item in items)
        return [counts[0], counts[1]]

    return {
        "scored_runs_holding_documents": len(scored),
        "scored_overall": split(scored),
        "scored_by_group": {group: split(row for row in scored if row["group"] == group) for group in sorted({row["group"] for row in scored})},
        "scored_by_task": {task: split(row for row in scored if row["task"] == task) for task in sorted({row["task"] for row in scored})},
        "scored_by_task_without_D": {task: split(row for row in scored if row["task"] == task and row["group"] != "D") for task in sorted({row["task"] for row in scored})},
        "note": "Each task keeps one arrangement, so a task is all one way and the split is even only across tasks.",
    }


def plan() -> dict:
    tasks = load_tasks()
    echoes = {task["id"]: name_problems(task) for task in tasks.values() if task["role"] != "dropped"}
    if any(echoes.values()):
        raise SystemExit(f"names that could steer an agent: { {key: value for key, value in echoes.items() if value} }")
    sets = {}
    for set_name in sets_in_use():
        synced = {task["id"]: arrangement_of(task["id"]) for task in tasks_of(set_name)}
        small, large = layout(set_name, "small", synced), layout(set_name, "large", synced)
        drawn = small_selection(set_name)
        if len(small) != SMALL_SET_SIZE:
            raise SystemExit(f"{set_name} small set has {len(small)} files")
        if not {item["target"] for item in small} <= {item["target"] for item in large}:
            raise SystemExit(f"{set_name} large set does not contain its small set")
        sets[set_name] = {
            "pairs": {task["id"]: {"replaces": sorted({task["revisions"][role]["path"] for role in ("old", "new")}), "names": task["neutral_names"], "D_arrangement": synced[task["id"]], "D_names": names_for(task, synced[task["id"]])} for task in tasks_of(set_name)},
            "small_set_size": len(small),
            "large_set_size": len(large),
            "small_set_drawn_documents": drawn,
        }
    rows = rotation_table()
    return {
        "rule": "See the docstring of formal/corpus/coexist.py.",
        "seed": SMALL_SET_SEED,
        "uniform_file_time": UNIFORM_TIME,
        "task_positions": {task_id: index for index, task_id in enumerate(tasks)},
        "sets": sets,
        "balance": balance(rows),
        "rotation": rows,
    }


def check(memforge: str | None) -> dict:
    """Materialize every folder and prove its text is pinned and that MemForge would take all of it."""
    from . import ingest_check

    namespace = None
    if memforge:
        import subprocess

        commit = subprocess.check_output(["git", "-C", memforge, "rev-parse", "origin/main"], text=True).strip()
        namespace = ingest_check.lift(subprocess.check_output(["git", "-C", memforge, "show", f"{commit}:src/memforge/main.py"], text=True))
    results = {}
    for set_name in sets_in_use():
        synced = {task["id"]: arrangement_of(task["id"]) for task in tasks_of(set_name)}
        for size in ("small", "large"):
            with tempfile.TemporaryDirectory() as raw:
                placed = materialize(Path(raw), set_name, size, synced)
                on_disk = [path for path in Path(raw).rglob("*") if path.is_file()]
                entry = {"files": len(placed), "on_disk": len(on_disk), "bytes": sum(path.stat().st_size for path in on_disk)}
                entry["one_file_time"] = len({path.stat().st_mtime for path in on_disk}) == 1
                if namespace:
                    entry["memforge_counts"] = ingest_check.scan(namespace, Path(raw))["counts"]
                results[f"{set_name}/{size}"] = entry
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["plan"])
    parser.add_argument("--memforge", help="a clone of MemForge, to run its file selection on every folder")
    args = parser.parse_args(argv)
    result = plan()
    result["folders_checked"] = check(args.memforge)
    write_json(STAGE0 / "coexistence_plan.json", result)
    for name, entry in result["folders_checked"].items():
        print(name, entry)
    print(result["balance"]["scored_overall"], result["balance"]["scored_by_group"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
