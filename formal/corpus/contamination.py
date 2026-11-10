"""Count the other documents in each full set that state a task's old or new rule.

    python3 -m formal.corpus.contamination

Nothing is edited. At full size such a document affects what any agent can find, so the
counts sit beside the results. A pattern finds candidates. Candidates that were read and
do not state the rule are listed in the task's `reviewed_not_stating`, with the reason.
Only paths and counts are recorded, not the text.
"""

from __future__ import annotations

import re

from ..common import FETCHED_SETS, STAGE0, CORPUS_DIR, load_manifest, load_tasks, write_json
from .coexist import revision_file, small_selection


def matches(patterns: list[dict], text: str) -> dict[str, int]:
    return {pattern["label"]: count for pattern in patterns if (count := len(re.findall(pattern["regex"], text, flags=re.MULTILINE)))}


def side(task: dict, role: str, small: set[str]) -> dict:
    set_name = task["doc_set"]
    patterns = task["contamination"][role]
    reviewed = task["contamination"].get("reviewed_not_stating", {}).get(role, {})
    own = {task["revisions"][key]["path"] for key in ("old", "new")}
    states, not_stating = [], []
    for row in load_manifest(set_name)["files"]:
        path = row["path"]
        if path in own:
            continue
        found = matches(patterns, (FETCHED_SETS / set_name / path).read_text(encoding="utf-8", errors="replace"))
        if not found:
            continue
        entry = {"path": path, "matches": found, "in_small_set": path in small}
        if path in reviewed:
            not_stating.append({**entry, "reason": reviewed[path]})
        else:
            states.append(entry)
    stale_reviews = sorted(set(reviewed) - {entry["path"] for entry in not_stating})
    excluded = []
    root = CORPUS_DIR / "fetched" / "excluded" / set_name
    if root.is_dir():
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            found = matches(patterns, path.read_text(encoding="utf-8", errors="replace"))
            if found:
                excluded.append({"path": path.relative_to(root).as_posix(), "matches": found})
    return {
        "documents_stating_it": len(states),
        "of_which_in_small_set": sum(entry["in_small_set"] for entry in states),
        "documents": states,
        "candidates_read_and_not_counted": not_stating,
        "reviews_with_no_match": stale_reviews,
        "matches_in_documents_left_out_of_the_set": excluded,
    }


def main() -> int:
    report = {}
    problems = []
    live = {task_id: task for task_id, task in load_tasks().items() if task["role"] != "dropped"}
    for task_id, task in live.items():
        small = set(small_selection(task["doc_set"]))
        entry = {"number": task["number"], "doc_set": task["doc_set"], "old": side(task, "old", small), "new": side(task, "new", small)}
        # A sibling's staged pair sits beside this task's documents at both sizes.
        siblings = {}
        for other in live.values():
            if other["doc_set"] == task["doc_set"] and other["id"] != task_id:
                for role in ("old", "new"):
                    text = revision_file(other, role).read_text(encoding="utf-8", errors="replace")
                    found = {side_name: matches(task["contamination"][side_name], text) for side_name in ("old", "new")}
                    if any(found.values()):
                        siblings[f"{other['id']}/{role}"] = found
        entry["matches_in_a_sibling_pair"] = siblings
        # Each pattern must find its own rule in its own revision, or a count of zero means nothing.
        for role in ("old", "new"):
            text = revision_file(task, role).read_text(encoding="utf-8", errors="replace")
            found = matches(task["contamination"][role], text)
            entry[f"{role}_patterns_find_the_{role}_revision"] = bool(found)
            if not found:
                problems.append(f"{task_id}: no {role} pattern finds the {role} revision")
            problems += [f"{task_id}: stale review {path}" for path in entry[role]["reviews_with_no_match"]]
        report[task_id] = entry
        print(f"{task_id:34} old {entry['old']['documents_stating_it']:3} (small {entry['old']['of_which_in_small_set']}) new {entry['new']['documents_stating_it']:3} (small {entry['new']['of_which_in_small_set']}) left-out old/new {len(entry['old']['matches_in_documents_left_out_of_the_set'])}/{len(entry['new']['matches_in_documents_left_out_of_the_set'])}")
        for role in ("old", "new"):
            for row in entry[role]["documents"]:
                print(f"    {role}: {row['path']} {row['matches']}{' SMALL' if row['in_small_set'] else ''}")
        for name, found in siblings.items():
            print(f"    sibling {name}: {found}")
    write_json(STAGE0 / "contamination.json", report)
    for problem in problems:
        print(f"PROBLEM: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
