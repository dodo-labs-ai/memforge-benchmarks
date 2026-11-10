"""Keep secrets and developer identifiers out of everything this repository records.

`Scrubber` cleans a transcript as it is copied out of a run. `scan_repository` then
checks every file that would be committed and reports only file names and counts, so
a hit never repeats the value. Patterns specific to one machine or organisation stay
out of the repository: point EXPERIMENT_SCAN_PATTERNS at a file with one regular
expression per line.
"""

from __future__ import annotations

import getpass
import os
import re
import subprocess
import sys
from pathlib import Path

from .common import REPO, endpoint_host, load_secrets, temp_root

_GENERIC = (
    r"\bsk-[A-Za-z0-9_-]{20,}",
    r"Bearer\s+[A-Za-z0-9._-]{20,}",
    r"(?:/private)?/var/folders/[A-Za-z0-9_]{2}/[A-Za-z0-9_+-]+",
)


def _local_patterns() -> list[str]:
    path = os.environ.get("EXPERIMENT_SCAN_PATTERNS", "")
    if not path:
        return []
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


class Scrubber:
    def __init__(self, secrets: dict[str, str]) -> None:
        values = {
            endpoint_host(secrets): "<endpoint>",
            secrets["MEMFORGE_RELAY_BASE_URL"].rstrip("/"): "<endpoint>",
            secrets["MEMFORGE_RELAY_API_KEY"]: "<redacted>",
            secrets["OPENROUTER_API_KEY"]: "<redacted>",
            str(Path.home()): "<developer-home>",
            getpass.getuser(): "<developer>",
            temp_root().parent.name: "<redacted>",
        }
        self._literals = sorted(values.items(), key=lambda item: -len(item[0]))
        self._patterns = [re.compile(pattern, re.IGNORECASE) for pattern in (*_GENERIC, *_local_patterns())]

    def scrub(self, text: str) -> tuple[str, int]:
        count = 0
        for value, replacement in self._literals:
            hits = text.count(value)
            if hits:
                text = text.replace(value, replacement)
                count += hits
        for pattern in self._patterns:
            text, hits = pattern.subn("<redacted>", text)
            count += hits
        return text, count

    def hits(self, text: str) -> int:
        return self.scrub(text)[1]


def scan_repository(secrets: dict[str, str] | None = None) -> dict[str, int]:
    """Every tracked or addable file with a hit, and how many. Empty means clean."""
    scrubber = Scrubber(secrets or load_secrets())
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    findings: dict[str, int] = {}
    for name in listed:
        path = REPO / name
        if not path.is_file():
            continue
        hits = scrubber.hits(path.read_text(encoding="utf-8", errors="replace"))
        if hits:
            findings[name] = hits
    return findings


def main() -> int:
    findings = scan_repository()
    if findings:
        for name, hits in sorted(findings.items()):
            print(f"{name}: {hits} hit(s)")
        return 1
    print("clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
