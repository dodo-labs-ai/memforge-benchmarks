"""Check every task with no model and no network, and record the result.

    python3 -m formal.harness.check_tasks

Reversal: the old and new revisions, opened at their commits, hold the old and the new
rule, each marker is unique to its revision, and neither opens with a banner.
Leak: no answer token of the task or of a sibling on the same document set appears in
the prompt or the code repository.
Assertion: standard library only. Each fixture, and the untouched repository, gets the
expected outcome, with and without the documents and an index in the workspace.
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
import tempfile
from pathlib import Path

from ..common import FETCHED_REVISIONS, OUTCOMES, STAGE0, TASKS_DIR, load_tasks, write_json
from .assertion import run_assertion

BANNER = re.compile(r"\b(deprecated|superseded|obsolete|outdated|out of date|no longer maintained)\b", re.IGNORECASE)


def revision_text(task: dict, role: str) -> str:
    suffix = Path(task["revisions"][role]["path"]).suffix
    return (FETCHED_REVISIONS / task["id"] / f"{role}{suffix}").read_text(encoding="utf-8", errors="replace")


def check_reversal(task: dict) -> dict:
    old, new = revision_text(task, "old"), revision_text(task, "new")
    check = task["reversal_check"]
    problems = []
    for name, text, tokens, wanted in (
        ("old revision lacks", old, check["old_has"], True),
        ("old revision holds", old, check["old_lacks"], False),
        ("new revision lacks", new, check["new_has"], True),
        ("new revision holds", new, check["new_lacks"], False),
    ):
        problems += [f"{name}: {token!r}" for token in tokens if (token in text) is not wanted]
    markers = task["markers"]
    if markers["old"] not in old or markers["old"] in new:
        problems.append("the old marker is not unique to the old revision")
    if markers["new"] not in new or markers["new"] in old:
        problems.append("the new marker is not unique to the new revision")
    head = {role: "\n".join(text.splitlines()[:30]) for role, text in (("old", old), ("new", new))}
    return {
        "confirmed": not problems,
        "problems": problems,
        "old_bytes": len(old.encode()),
        "new_bytes": len(new.encode()),
        "banner_words_in_first_30_lines": {role: sorted({match.lower() for match in BANNER.findall(text)}) for role, text in head.items()},
    }


def check_leaks(task: dict) -> dict:
    repo = TASKS_DIR / task["id"] / "repo"
    hits = []
    tokens = [*task["leak_tokens"], task["markers"]["old"].strip(), task["markers"]["new"].strip()]
    for token in tokens:
        if token in task["prompt"]:
            hits.append(f"prompt holds {token!r}")
    for path in sorted(p for p in repo.rglob("*") if p.is_file()):
        text = path.read_text(encoding="utf-8", errors="replace")
        hits += [f"{path.relative_to(repo).as_posix()} holds {token!r}" for token in tokens if token in text]
    return {"clean": not hits, "hits": hits, "tokens_checked": len(tokens)}


def check_stdlib_only(task: dict) -> dict:
    allowed = set(sys.stdlib_module_names) | {"assertlib"}
    imported: set[str] = set()
    for path in (TASKS_DIR / task["id"] / "assert_outcome.py", TASKS_DIR / "assertlib.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
    outside = sorted(imported - allowed)
    return {"standard_library_only": not outside, "outside": outside, "imports": sorted(imported)}


def _expected(fixture: str) -> str:
    outcome = fixture.split("__")[0]
    if outcome not in OUTCOMES:
        raise SystemExit(f"fixture {fixture} does not name an outcome")
    return outcome


def check_fixtures(task: dict) -> dict:
    root = TASKS_DIR / task["id"]
    fixtures = sorted(path.name for path in (root / "fixtures").iterdir() if path.is_dir())
    missing = [outcome for outcome in OUTCOMES if outcome not in fixtures]
    rows = []
    for fixture, expected in [*((name, _expected(name)) for name in fixtures), ("untouched", "declined")]:
        for documents in (False, True):
            with tempfile.TemporaryDirectory() as raw:
                workspace = Path(raw) / "repo"
                shutil.copytree(root / "repo", workspace, ignore=shutil.ignore_patterns("__pycache__"))
                if fixture != "untouched":
                    shutil.copytree(root / "fixtures" / fixture, workspace, dirs_exist_ok=True)
                if documents:
                    # The harness's own files in the workspace must never change a verdict.
                    target = workspace / "docs"
                    target.mkdir()
                    for role in ("old", "new"):
                        (target / f"{role}.md").write_text(revision_text(task, role), encoding="utf-8")
                    (workspace / "AGENTS.md").write_text("# Docs index\n\n- docs/new.md\n", encoding="utf-8")
                verdict = run_assertion(task["id"], workspace, Path(raw))
            rows.append({"fixture": fixture, "with_documents": documents, "expected": expected, "outcome": verdict["outcome"], "ok": verdict["outcome"] == expected, "detail": verdict.get("detail", "")})
    return {"missing_outcomes": missing, "all_ok": not missing and all(row["ok"] for row in rows), "rows": rows}


def main() -> int:
    report = {}
    failed = False
    for task_id, task in load_tasks().items():
        entry = {
            "number": task["number"],
            "role": task["role"],
            "doc_set": task["doc_set"],
            "reversal": check_reversal(task),
            "leak": check_leaks(task),
            "assertion_imports": check_stdlib_only(task),
            "fixtures": check_fixtures(task),
        }
        report[task_id] = entry
        ok = entry["reversal"]["confirmed"] and entry["leak"]["clean"] and entry["assertion_imports"]["standard_library_only"] and entry["fixtures"]["all_ok"]
        failed = failed or not ok
        passed = sum(row["ok"] for row in entry["fixtures"]["rows"])
        print(f"{task_id:34} reversal={entry['reversal']['confirmed']} leak_clean={entry['leak']['clean']} stdlib={entry['assertion_imports']['standard_library_only']} fixtures={passed}/{len(entry['fixtures']['rows'])}")
        for problem in entry["reversal"]["problems"] + entry["leak"]["hits"]:
            print(f"   {problem}")
        for row in entry["fixtures"]["rows"]:
            if not row["ok"]:
                print(f"   {row['fixture']} docs={row['with_documents']}: expected {row['expected']}, got {row['outcome']}: {row['detail'][:200]}")
    write_json(STAGE0 / "selftest.json", report)
    print("selftest " + ("FAILED" if failed else "ok"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
