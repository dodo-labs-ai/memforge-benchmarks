"""Fetch the pinned document sets and the old and new revisions the tasks rest on.

    python3 -m formal.corpus.fetch_corpus            # fetch what is missing, verify against the manifests
    python3 -m formal.corpus.fetch_corpus --write    # as above, and write the manifests from what was fetched
    python3 -m formal.corpus.fetch_corpus --sets     # document sets only, not revisions

Fetched text is data. It goes to formal/corpus/fetched, which git ignores, and only
regular files matching a set's glob are written. Nothing fetched is ever executed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

FORMAL = Path(__file__).resolve().parent.parent
CORPUS = FORMAL / "corpus"
FETCHED = CORPUS / "fetched"
MANIFESTS = CORPUS / "manifests"
SETS_FILE = CORPUS / "sets.json"
REVISIONS_FILE = CORPUS / "revisions.json"
TASKS = FORMAL / "tasks"
USER_AGENT = "memforge-benchmarks-fetch"


def _get(url: str, *, timeout: float = 600, attempts: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = error
            if isinstance(error, urllib.error.HTTPError) and error.code in (400, 401, 403, 404):
                break
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


def archive_url(spec: dict) -> str:
    if spec["host"] == "github":
        return f"https://codeload.github.com/{spec['repo']}/tar.gz/{spec['commit']}"
    project = urllib.parse.quote(spec["repo"], safe="")
    query = urllib.parse.urlencode({"sha": spec["commit"], "path": spec["archive_path"]})
    return f"https://gitlab.com/api/v4/projects/{project}/repository/archive.tar.gz?{query}"


def raw_url(host: str, repo: str, commit: str, path: str) -> str:
    quoted = urllib.parse.quote(path)
    if host == "github":
        return f"https://raw.githubusercontent.com/{repo}/{commit}/{quoted}"
    return f"https://gitlab.com/{repo}/-/raw/{commit}/{quoted}"


def blob_url(host: str, repo: str, commit: str, path: str) -> str:
    if host == "github":
        return f"https://github.com/{repo}/blob/{commit}/{path}"
    return f"https://gitlab.com/{repo}/-/blob/{commit}/{path}"


def in_set(path: str, spec: dict) -> bool:
    return PurePosixPath(path).full_match(spec["glob"]) and path not in spec["exclude"]


def file_row(path: str, data: bytes) -> dict:
    return {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def fetch_set(name: str, spec: dict) -> list[dict]:
    """The set's files on disk, fetched from the pinned archive unless already there."""
    root = FETCHED / "sets" / name
    marker = FETCHED / "sets" / f"{name}.complete"
    rows: list[dict] = []
    if marker.exists() and marker.read_text().strip() == spec["commit"]:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rows.append(file_row(path.relative_to(root).as_posix(), path.read_bytes()))
        rows.sort(key=lambda row: row["path"])
        return rows
    print(f"{name}: downloading the archive at {spec['commit'][:12]}", flush=True)
    blob = _get(archive_url(spec))
    print(f"{name}: {len(blob)} archive bytes", flush=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive:
            if not member.isreg():
                continue
            parts = PurePosixPath(member.name).parts[1:]
            if not parts or ".." in parts or parts[0] == "/":
                continue
            relative = PurePosixPath(*parts).as_posix()
            excluded = "excluded_documents_glob" in spec and PurePosixPath(relative).full_match(spec["excluded_documents_glob"])
            if not excluded and not in_set(relative, spec):
                continue
            stream = archive.extractfile(member)
            data = stream.read() if stream else b""
            target = (FETCHED / "excluded" / name if excluded else root) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if not excluded:
                rows.append(file_row(relative, data))
    marker.write_text(spec["commit"] + "\n")
    rows.sort(key=lambda row: row["path"])
    return rows


def fetch_revisions(sets: dict) -> list[dict]:
    """Every old and new revision named by a task, by commit and path."""
    rows = []
    for task_file in sorted(TASKS.glob("*/task.json")):
        task = json.loads(task_file.read_text(encoding="utf-8"))
        spec = sets[task["doc_set"]]
        for role, revision in sorted(task["revisions"].items()):
            target = FETCHED / "revisions" / task["id"] / f"{role}{PurePosixPath(revision['path']).suffix}"
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_get(raw_url(spec["host"], spec["repo"], revision["commit"], revision["path"]), timeout=120))
            data = target.read_bytes()
            rows.append(
                {
                    "task": task["id"],
                    "role": role,
                    "doc_set": task["doc_set"],
                    "commit": revision["commit"],
                    "path": revision["path"],
                    "url": blob_url(spec["host"], spec["repo"], revision["commit"], revision["path"]),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    return rows


def excluded_rows(name: str) -> list[dict]:
    """Documents a set leaves out, kept on disk so that the contamination count can see them."""
    root = FETCHED / "excluded" / name
    rows = [file_row(path.relative_to(root).as_posix(), path.read_bytes()) for path in root.rglob("*") if path.is_file()]
    return sorted(rows, key=lambda row: row["path"])


def manifest_of(name: str, spec: dict, rows: list[dict]) -> dict:
    excluded = excluded_rows(name)
    return {
        "set": name,
        "repo": spec["repo"],
        "host": spec["host"],
        "commit": spec["commit"],
        "glob": spec["glob"],
        "exclude": spec["exclude"],
        "licence": spec["licence"],
        "archive_url": archive_url(spec),
        "file_count": len(rows),
        "total_bytes": sum(row["bytes"] for row in rows),
        **({"excluded_documents": {"glob": spec["excluded_documents_glob"], "file_count": len(excluded), "total_bytes": sum(row["bytes"] for row in excluded), "files": excluded}} if excluded else {}),
        "files": rows,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write manifests from what was fetched")
    parser.add_argument("--sets", action="store_true", help="only the document sets")
    args = parser.parse_args(argv)
    sets = json.loads(SETS_FILE.read_text(encoding="utf-8"))["sets"]
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    problems = []
    for name, spec in sets.items():
        rows = fetch_set(name, spec)
        manifest = manifest_of(name, spec, rows)
        path = MANIFESTS / f"{name}.json"
        if args.write:
            path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        elif not path.exists() or json.loads(path.read_text(encoding="utf-8"))["files"] != rows:
            problems.append(f"{name} differs from its manifest")
        print(f"{name}: {manifest['file_count']} files, {manifest['total_bytes']} bytes", flush=True)
    if not args.sets:
        rows = fetch_revisions(sets)
        if args.write:
            REVISIONS_FILE.write_text(json.dumps({"revisions": rows}, indent=1) + "\n", encoding="utf-8")
        elif not REVISIONS_FILE.exists() or json.loads(REVISIONS_FILE.read_text(encoding="utf-8"))["revisions"] != rows:
            problems.append("revisions differ from their manifest")
        print(f"revisions: {len(rows)} files", flush=True)
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
