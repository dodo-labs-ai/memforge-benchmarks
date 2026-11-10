"""What MemForge's local file source would take from each document set, with no model call.

    python3 -m formal.corpus.ingest_check --memforge PATH_TO_A_CLONE [--commit SHA]

It lifts the file-selection functions verbatim out of `src/memforge/main.py` at the
given commit and runs them on each fetched set and on a probe folder of file types.
Run it under Python 3.12 as well, the version of MemForge's Docker image: the selection
uses `PurePosixPath.match`, whose wildcard handling has changed between Python versions.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

FORMAL = Path(__file__).resolve().parent.parent
SETS_ROOT = FORMAL / "corpus" / "fetched" / "sets"
OUTPUT = FORMAL / "stage0" / "ingest_report.json"
LIFTED_FUNCTIONS = ("_scan_kb_profile", "_glob_match", "_content_type_for_path", "_markdown_title")
LIFTED_VALUES = ("DEFAULT_KB_INCLUDE", "DEFAULT_KB_EXCLUDE", "_CONTENT_TYPE_BY_SUFFIX")
SIZE_LIMIT_SOURCE_LINE = "max_bytes = 1_000_000"


def lift(source: str) -> dict:
    """The selection functions and their constants, nothing else from the module."""
    wanted = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in LIFTED_FUNCTIONS:
            wanted.append(node)
        elif isinstance(node, ast.Assign) and any(getattr(target, "id", "") in LIFTED_VALUES for target in node.targets):
            wanted.append(node)
    namespace = {"hashlib": hashlib, "datetime": datetime, "timezone": timezone, "Path": Path, "PurePosixPath": PurePosixPath, "Any": Any}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), "memforge-main-lifted", "exec"), namespace)
    missing = [name for name in (*LIFTED_FUNCTIONS, *LIFTED_VALUES) if name not in namespace]
    if missing:
        raise SystemExit(f"could not lift {missing}")
    return namespace


def scan(namespace: dict, root: Path) -> dict:
    counts = {"included": 0, "ignored": 0, "too_large": 0, "invalid_utf8": 0, "unreadable": 0}
    entries = list(namespace["_scan_kb_profile"](root, include=namespace["DEFAULT_KB_INCLUDE"], exclude=namespace["DEFAULT_KB_EXCLUDE"], counts=counts))
    return {"counts": counts, "entries": entries}


def set_report(namespace: dict, root: Path) -> dict:
    result = scan(namespace, root)
    entries = result["entries"]
    return {
        "counts": result["counts"],
        "blocks_the_whole_collection": any(result["counts"][key] for key in ("too_large", "invalid_utf8", "unreadable")),
        "content_types": dict(Counter(entry["content_type"] for entry in entries)),
        "title_from_a_heading": sum(1 for entry in entries if entry["title"] != entry["relative_path"]),
        "title_is_the_path": sum(1 for entry in entries if entry["title"] == entry["relative_path"]),
        "largest_file_bytes": max((entry["bytes"] for entry in entries), default=0),
        "total_bytes": sum(entry["bytes"] for entry in entries),
    }


def probe(namespace: dict) -> list[dict]:
    files = {
        "plain.md": b"# t\n",
        "govuk-style.html.md": b"---\ntitle: t\n---\n",
        "nested/deep/page.html.md": b"x\n",
        "django-style.txt": b"Title\n=====\n",
        "doc.markdown": b"x\n",
        "component.mdx": b"# t\n",
        "page.html.md.erb": b"x\n",
        "page.erb": b"x\n",
        "doc.rst": b"x\n",
        "UPPER.MD": b"x\n",
        "page.html": b"<p>x</p>\n",
        "exactly_the_limit.md": b"x" * 1_000_000,
        "one_byte_over.md": b"x" * 1_000_001,
        "not_utf8.md": b"caf\xe9\n",
    }
    rows = []
    for name, data in files.items():
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            result = scan(namespace, Path(raw))
        kinds = [key for key, value in result["counts"].items() if value]
        rows.append({"file": name, "result": kinds[0] if kinds else "nothing", "content_type": result["entries"][0]["content_type"] if result["entries"] else None})
    return rows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memforge", required=True, help="a clone of the MemForge repository, read with git show")
    parser.add_argument("--commit", default="origin/main")
    args = parser.parse_args(argv)
    commit = subprocess.check_output(["git", "-C", args.memforge, "rev-parse", args.commit], text=True).strip()
    source = subprocess.check_output(["git", "-C", args.memforge, "show", f"{commit}:src/memforge/main.py"], text=True)
    namespace = lift(source)
    report = {
        "memforge_commit": commit,
        "python": sys.version.split()[0],
        "default_include": namespace["DEFAULT_KB_INCLUDE"],
        "default_exclude": namespace["DEFAULT_KB_EXCLUDE"],
        "size_limit_line_in_source": SIZE_LIMIT_SOURCE_LINE in source,
        "probe": probe(namespace),
        "sets": {root.name: set_report(namespace, root) for root in sorted(path for path in SETS_ROOT.iterdir() if path.is_dir())},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    target = OUTPUT if sys.version_info[:2] != (3, 12) else OUTPUT.with_name("ingest_report_py312.json")
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"python": report["python"], "commit": commit, "probe": {row["file"]: row["result"] for row in report["probe"]}, "sets": {name: entry["counts"] for name, entry in report["sets"].items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
